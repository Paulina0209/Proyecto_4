"""Capas de datos: base de cBioPortal intocable + capa de trabajo con el escenario.

Sin red: la base se arma con pacientes que imitan los del índice de cBioPortal
(identificación ``CBIO:...``, tipo ``externo``) y una sincronización exitosa
para los que tienen "detalle".
"""
from __future__ import annotations

import hashlib
import sqlite3
from collections import Counter
from pathlib import Path

import pytest

from datos import capas, escenario
from datos.__main__ import estado, preparar, reiniciar
from historia_clinica.db import crear_conexion
from patients import db as db_pacientes
from privacidad.consentimiento_ia import estado_consentimiento_ia

PACIENTES = 40   # en el "índice"
CON_DETALLE = 33  # 3 de la demo + 30 de la cohorte


def _sembrar_base(carpeta: Path) -> None:
    carpeta.mkdir(parents=True, exist_ok=True)
    exp = crear_conexion(str(carpeta / "copiloto.db"))
    pac = db_pacientes.conectar(carpeta / "pacientes.db")
    db_pacientes.inicializar(pac)
    ids_cbio = list(capas.PACIENTES_DEMO) + [f"P-{9000000 + i:07d}" for i in range(PACIENTES - 3)]
    for n, cbio in enumerate(ids_cbio):
        identificacion = f"CBIO:{capas.ESTUDIO}:{cbio}"
        diagnostico = "Lung Adenocarcinoma" if n % 2 else "Breast Invasive Ductal Carcinoma"
        cur = exp.execute(
            "INSERT INTO pacientes (nombre, fecha_nacimiento, sexo, identificacion, diagnostico_principal) VALUES (?, ?, ?, ?, ?)",
            (f"Paciente {cbio} (cBioPortal)", "1960-01-01", "femenino", identificacion, diagnostico),
        )
        if n < CON_DETALLE:
            exp.execute("INSERT INTO sincronizaciones_externas (paciente_id, fuente, formato, estado, fecha) "
                        "VALUES (?, 'cbioportal', 'cbioportal', 'exitosa', '2026-09-29')", (cur.lastrowid,))
            exp.execute("INSERT INTO laboratorios (paciente_id, fecha, prueba, valor, unidad) VALUES (?, '2026-09-01', 'CEA', '3.1', 'ng/ml')",
                        (cur.lastrowid,))
            exp.execute("INSERT INTO biomarcadores (paciente_id, fecha, biomarcador, resultado) VALUES (?, '2026-08-01', 'EGFR', "
                        "'mutación detectada: L858R (Missense_Mutation) · muestra X')", (cur.lastrowid,))
        cur = pac.execute(
            "INSERT INTO pacientes (nombre_completo, sexo, tipo_identificacion, numero_identificacion, oncologo_id, fecha_registro) "
            "VALUES (?, 'femenino', 'externo', ?, 1, '2026-09-29')", (f"Paciente {cbio}", identificacion),
        )
        pac.execute("INSERT INTO diagnosticos (paciente_id, descripcion) VALUES (?, ?)", (cur.lastrowid, diagnostico))
    exp.commit()
    pac.commit()
    exp.close()
    pac.close()


@pytest.fixture()
def entorno(tmp_path, monkeypatch):
    base = tmp_path / "base"
    _sembrar_base(base)
    monkeypatch.setattr(capas, "CARPETA_BASE", base)
    monkeypatch.setattr(capas, "BASE_EXPEDIENTE", base / "copiloto.db")
    monkeypatch.setattr(capas, "BASE_PACIENTES", base / "pacientes.db")
    trabajo = tmp_path / "trabajo"
    trabajo.mkdir()
    rutas = capas.RutasTrabajo(trabajo / "copiloto.db", trabajo / "pacientes.db", trabajo / "usuarios.db")
    monkeypatch.setattr(capas.RutasTrabajo, "por_defecto", classmethod(lambda cls: rutas))
    return rutas


def _hash(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def test_preparar_arma_la_capa_de_trabajo_sin_tocar_la_base(entorno):
    antes = (_hash(capas.BASE_EXPEDIENTE), _hash(capas.BASE_PACIENTES))
    assert preparar(aviso=lambda t: None) == 0
    assert capas.es_trabajo_de_escenario(entorno)
    assert (_hash(capas.BASE_EXPEDIENTE), _hash(capas.BASE_PACIENTES)) == antes  # la base no se modifica


def test_usuarios_con_ids_fijos_y_un_rol_cada_uno(entorno):
    preparar(aviso=lambda t: None)
    from seguridad.autenticacion import autenticar

    conn = sqlite3.connect(entorno.usuarios)
    conn.row_factory = sqlite3.Row
    filas = {f["nombre_usuario"]: (f["id"], f["rol"]) for f in conn.execute("SELECT id, nombre_usuario, rol FROM usuarios")}
    assert {n: i for n, (i, _) in filas.items()} == escenario.IDS
    assert filas["dra.gomez"] == (escenario.ONCOLOGO_DEMO_ID, "oncologo")
    assert autenticar(conn, "dra.gomez", escenario.CLAVE_ESCENARIO).exito
    conn.close()


def test_pacientes_repartidos_y_los_de_la_demo_son_de_la_dra_gomez(entorno):
    preparar(aviso=lambda t: None)
    conn = sqlite3.connect(entorno.pacientes)
    por_oncologo = dict(conn.execute("SELECT oncologo_id, COUNT(*) FROM pacientes GROUP BY 1").fetchall())
    assert set(por_oncologo) == set(escenario.ONCOLOGOS)
    for cbio in capas.PACIENTES_DEMO:
        assert conn.execute("SELECT oncologo_id FROM pacientes WHERE numero_identificacion LIKE ?",
                            (f"%{cbio}",)).fetchone()[0] == escenario.ONCOLOGO_DEMO_ID
    conn.close()


def test_todos_los_casos_de_consentimiento(entorno):
    preparar(aviso=lambda t: None)
    conn = crear_conexion(str(entorno.expediente))
    cohorte = escenario.cohorte_con_detalle(conn)
    assert len(cohorte) == CON_DETALLE
    estados = {cbio: estado_consentimiento_ia(conn, pid) for pid, cbio in cohorte}
    etiquetas = Counter(e.etiqueta for e in estados.values())
    assert set(etiquetas) == {"otorgada", "pendiente", "denegada", "revocada"}
    assert etiquetas["otorgada"] > len(cohorte) / 2  # la mayoría
    assert all(estados[c].ia_habilitada for c in capas.PACIENTES_DEMO)  # la demo unificada usa IA con ellos
    # Los retirados y vueltos a otorgar tienen tres registros, y la IA habilitada.
    from privacidad.tratamiento_datos import historial_autorizaciones

    historiales = [[a.estado.value for a in historial_autorizaciones(conn, pid) if a.finalidad == "asistencia_ia"]
                   for pid, _ in cohorte]
    assert ["otorgada", "revocada", "otorgada"] in historiales
    assert ["revocada", "otorgada"] in historiales
    # Los del índice sin detalle quedan pendientes.
    sin_detalle = conn.execute("SELECT id FROM pacientes WHERE id NOT IN (SELECT paciente_id FROM sincronizaciones_externas)").fetchone()[0]
    assert estado_consentimiento_ia(conn, sin_detalle).etiqueta == "pendiente"
    conn.close()


def test_consentimientos_y_consultas_quedan_auditados_a_nombre_de_quien_corresponde(entorno):
    preparar(aviso=lambda t: None)
    conn = crear_conexion(str(entorno.expediente))
    quienes = {f[0] for f in conn.execute("SELECT DISTINCT usuario_id FROM eventos_acceso WHERE accion = 'registrar_autorizacion'")}
    assert quienes <= set(escenario.ONCOLOGOS) | {escenario.ADMINISTRATIVO_ID}
    consultas = conn.execute("SELECT motivo, notas_libres FROM consultas").fetchall()
    assert len(consultas) == CON_DETALLE - len(capas.PACIENTES_DEMO)
    assert all("escenario" in m and "Revisión del expediente importado" in n for m, n in consultas)
    assert "EGFR" in consultas[0][1] and "CEA 3.1" in consultas[0][1]  # solo datos que ya estaban
    conn.close()


def test_la_primera_vez_respalda_lo_que_habia(entorno):
    vieja = crear_conexion(str(entorno.expediente))
    vieja.execute("CREATE TABLE dato_del_equipo (x)")
    vieja.execute("INSERT INTO dato_del_equipo VALUES ('decisión registrada a mano')")
    vieja.commit()
    vieja.close()
    preparar(aviso=lambda t: None)
    respaldos = list(entorno.expediente.parent.glob("respaldo_*/copiloto.db"))
    assert len(respaldos) == 1
    with sqlite3.connect(respaldos[0]) as c:
        assert c.execute("SELECT x FROM dato_del_equipo").fetchone()[0] == "decisión registrada a mano"


def test_preparar_otra_vez_no_toca_nada(entorno):
    preparar(aviso=lambda t: None)
    conn = crear_conexion(str(entorno.expediente))
    conn.execute("INSERT INTO consultas (paciente_id, fecha, motivo, notas_libres) VALUES (1, '2026-10-01', 'Control', 'nota')")
    conn.commit()
    conn.close()
    assert preparar(aviso=lambda t: None) == 0
    with sqlite3.connect(entorno.expediente) as c:
        assert c.execute("SELECT COUNT(*) FROM consultas WHERE motivo = 'Control'").fetchone()[0] == 1


def test_reiniciar_descarta_los_cambios(entorno):
    preparar(aviso=lambda t: None)
    conn = crear_conexion(str(entorno.expediente))
    conn.execute("INSERT INTO consultas (paciente_id, fecha, motivo, notas_libres) VALUES (1, '2026-10-01', 'Control', 'nota')")
    conn.commit()
    conn.close()
    assert reiniciar(confirmar=False, aviso=lambda t: None) == 1  # pide confirmación
    assert reiniciar(confirmar=True, aviso=lambda t: None) == 0
    with sqlite3.connect(entorno.expediente) as c:
        assert c.execute("SELECT COUNT(*) FROM consultas WHERE motivo = 'Control'").fetchone()[0] == 0
    assert capas.es_trabajo_de_escenario(entorno)


def test_el_escenario_no_se_aplica_dos_veces(entorno):
    preparar(aviso=lambda t: None)
    with pytest.raises(RuntimeError, match="ya está aplicado"):
        escenario.aplicar_escenario(entorno)


def test_sin_red_adopta_las_bases_existentes(entorno, tmp_path, monkeypatch):
    nueva_base = tmp_path / "otra_base"
    monkeypatch.setattr(capas, "CARPETA_BASE", nueva_base)
    monkeypatch.setattr(capas, "BASE_EXPEDIENTE", nueva_base / "copiloto.db")
    monkeypatch.setattr(capas, "BASE_PACIENTES", nueva_base / "pacientes.db")
    # Las bases "de antes" (sin escenario) en las rutas de trabajo.
    capas.copiar_base_sqlite(tmp_path / "base" / "copiloto.db", entorno.expediente)
    capas.copiar_base_sqlite(tmp_path / "base" / "pacientes.db", entorno.pacientes)
    assert preparar(sin_red=True, aviso=lambda t: None) == 0
    assert capas.base_existe() and capas.es_trabajo_de_escenario(entorno)


def test_elegir_cohorte_incluye_la_demo_y_ambos_tipos(entorno):
    conn = db_pacientes.conectar(capas.BASE_PACIENTES)
    cohorte = capas.elegir_cohorte(conn, tamano=13)
    conn.close()
    assert cohorte[:3] == list(capas.PACIENTES_DEMO) and len(cohorte) == 13 and len(set(cohorte)) == 13


def test_estado(entorno, capsys):
    assert estado(aviso=print) == 1  # sin capa de trabajo
    preparar(aviso=lambda t: None)
    assert estado(aviso=print) == 0
    salida = capsys.readouterr().out
    assert "Escenario v1" in salida and "pendiente" in salida and "denegada" in salida
