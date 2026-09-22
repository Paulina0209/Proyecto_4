"""Pruebas de Fase 1 para clinical_decision/registro.py (C2, C4, S5).

Usa una base SQLite real en memoria. FakeChequeo/FakeInteraccion imitan
por duck-typing la forma de ResultadoChequeoInteracciones (paciente_id,
regimen_evaluado, bloquea_confirmacion(), requiere_justificacion()), así
que corren contra el confirmar_tratamiento REAL de
tx_clinica.justificaciones sin necesitar interacciones_farmacologicas.
"""
import sqlite3
from dataclasses import dataclass, field

from clinical_decision import registro
from tx_clinica.justificaciones import inicializar_schema as _init_justificaciones


def _conn():
    # En el proyecto real, _db.py llama a ambos inicializadores (ver S4/S5
    # en el plan): el de decisiones_tratamiento (este módulo) y el de
    # justificaciones_continuacion (tx_clinica.justificaciones), porque
    # accept/modify puede escribir en las dos tablas dentro de la misma
    # transacción.
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys = ON")
    registro.inicializar_schema(c)
    _init_justificaciones(c)
    return c


@dataclass
class FakeInteraccion:
    interaccion_id: str
    audit_effect: str = "informational"


@dataclass
class FakeChequeo:
    paciente_id: int
    regimen_evaluado: str
    interacciones: list = field(default_factory=list)

    def bloquea_confirmacion(self):
        return [i for i in self.interacciones if i.audit_effect == "blocks_confirmation"]

    def requiere_justificacion(self):
        return [i for i in self.interacciones if i.audit_effect == "requires_justification"]


def _kwargs_base(**overrides):
    base = dict(
        paciente_id=10,
        oncologo_id=1,
        tipo_decision="accept",
        recomendacion_ia_snapshot={"module_id": "m", "candidatos": []},
        regimenes_candidatos_ids=["reg_a", "reg_b"],
        regimen_sugerido_id="reg_a",
        chequeo_interacciones=FakeChequeo(paciente_id=10, regimen_evaluado="reg_a"),
    )
    base.update(overrides)
    return base


def test_accept_ok_persiste_y_commitea():
    conn = _conn()
    r = registro.registrar_decision_tratamiento(conn, **_kwargs_base())
    assert r.exito, r.motivo_rechazo
    assert r.decision.regimen_final_id == "reg_a"
    filas = conn.execute("SELECT COUNT(*) FROM decisiones_tratamiento").fetchone()[0]
    assert filas == 1


def test_c2_chequeo_de_otro_regimen_se_rechaza():
    conn = _conn()
    kwargs = _kwargs_base(
        chequeo_interacciones=FakeChequeo(paciente_id=10, regimen_evaluado="reg_b"),  # distinto al sugerido/final
    )
    r = registro.registrar_decision_tratamiento(conn, **kwargs)
    assert not r.exito
    assert "no corresponde" in r.motivo_rechazo
    assert conn.execute("SELECT COUNT(*) FROM decisiones_tratamiento").fetchone()[0] == 0


def test_c2_chequeo_de_otro_paciente_se_rechaza():
    conn = _conn()
    kwargs = _kwargs_base(
        chequeo_interacciones=FakeChequeo(paciente_id=999, regimen_evaluado="reg_a"),
    )
    r = registro.registrar_decision_tratamiento(conn, **kwargs)
    assert not r.exito
    assert "no corresponde" in r.motivo_rechazo


def test_c4_rollback_no_deja_justificaciones_huerfanas():
    """Si _persistir falla DESPUES de que confirmar_tratamiento ya guardó
    una justificación (sin commit), el rollback debe descartar ambas
    escrituras, no solo la de la decisión."""
    conn = _conn()
    chequeo = FakeChequeo(
        paciente_id=10,
        regimen_evaluado="reg_a",
        interacciones=[FakeInteraccion("int-1", audit_effect="requires_justification")],
    )
    kwargs = _kwargs_base(
        chequeo_interacciones=chequeo,
        textos_justificacion={"int-1": "Justificación real del oncólogo."},
    )

    original_persistir = registro._persistir

    def _persistir_que_falla(conn, decision):
        # Simula un fallo justo después de que confirmar_tratamiento ya
        # insertó la justificación (sin commit) pero antes del commit final.
        raise sqlite3.OperationalError("fallo simulado")

    registro._persistir = _persistir_que_falla
    try:
        try:
            registro.registrar_decision_tratamiento(conn, **kwargs)
            assert False, "debía propagar la excepción simulada"
        except sqlite3.OperationalError:
            pass
    finally:
        registro._persistir = original_persistir

    assert conn.execute("SELECT COUNT(*) FROM decisiones_tratamiento").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM justificaciones_continuacion").fetchone()[0] == 0, (
        "la justificación debía revertirse junto con la decisión (rollback atómico)"
    )


def test_c4_justificacion_exitosa_persiste_ambas_cosas():
    conn = _conn()
    chequeo = FakeChequeo(
        paciente_id=10,
        regimen_evaluado="reg_a",
        interacciones=[FakeInteraccion("int-1", audit_effect="requires_justification")],
    )
    kwargs = _kwargs_base(
        chequeo_interacciones=chequeo,
        textos_justificacion={"int-1": "Justificación real del oncólogo."},
    )
    r = registro.registrar_decision_tratamiento(conn, **kwargs)
    assert r.exito, r.motivo_rechazo
    assert conn.execute("SELECT COUNT(*) FROM decisiones_tratamiento").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM justificaciones_continuacion").fetchone()[0] == 1


def test_s5_decisiones_tratamiento_es_append_only():
    conn = _conn()
    registro.registrar_decision_tratamiento(conn, **_kwargs_base())
    try:
        conn.execute("UPDATE decisiones_tratamiento SET tipo_decision = 'reject' WHERE id = 1")
        assert False, "el UPDATE debía abortar"
    except sqlite3.IntegrityError:
        pass
    try:
        conn.execute("DELETE FROM decisiones_tratamiento WHERE id = 1")
        assert False, "el DELETE debía abortar"
    except sqlite3.IntegrityError:
        pass
    assert conn.execute("SELECT COUNT(*) FROM decisiones_tratamiento").fetchone()[0] == 1


def test_reject_no_pasa_por_gate_de_interacciones():
    conn = _conn()
    r = registro.registrar_decision_tratamiento(
        conn,
        paciente_id=10, oncologo_id=1, tipo_decision="reject",
        recomendacion_ia_snapshot={}, regimenes_candidatos_ids=[], regimen_sugerido_id="reg_a",
        motivo_rechazo="El paciente prefiere otra línea de tratamiento.",
        chequeo_interacciones=None,
    )
    assert r.exito, r.motivo_rechazo


def test_modify_regimen_fuera_de_candidatos_se_rechaza():
    conn = _conn()
    kwargs = _kwargs_base(tipo_decision="modify", regimen_final_id="reg_inventado")
    r = registro.registrar_decision_tratamiento(conn, **kwargs)
    assert not r.exito
    assert "no es uno de los regímenes ya evaluados" in r.motivo_rechazo