"""Pruebas de aceptación de DX-03 — el juicio clínico del médico prevalece (AC4/AC5)."""

from datetime import datetime, timezone

import pytest

from dx_clinica.juicio_clinico import (
    JuicioClinicoInvalidoError,
    crear_conexion,
    obtener_decision_diagnostica_vigente,
    obtener_historial_juicios,
    registrar_juicio_clinico,
)
from dx_clinica.models import CriterioEvaluado, DiagnosticoDiferencialCandidato, ResultadoDiagnosticoDiferencial

AHORA = datetime(2026, 8, 30, tzinfo=timezone.utc)


@pytest.fixture
def conn():
    connection = crear_conexion(":memory:")
    yield connection
    connection.close()


def _resultado_sistema_de_ejemplo():
    candidato = DiagnosticoDiferencialCandidato(
        perfil_id="progresion_enfermedad_base",
        nombre="Progresión de la enfermedad oncológica de base",
        orden=1,
        criterios_sustentados=(CriterioEvaluado(id="c1", descripcion="hallazgo", hallazgos_ids=("h1",)),),
        criterios_sin_sustento=(),
        evidencia=None,
    )
    return ResultadoDiagnosticoDiferencial(paciente_id=1, generado_en=AHORA, candidatos=(candidato,))


# ---------------------------------------------------------------------------
# AC4 — Dado que el médico no está de acuerdo con la priorización
# propuesta por el sistema, cuando registra su propio juicio diagnóstico,
# el sistema permite que se conserve sin bloquearlo ni sobreescribirlo.
# ---------------------------------------------------------------------------
class TestElMedicoPuedeRegistrarSuPropioJuicio:
    def test_se_acepta_un_juicio_que_contradice_al_sistema(self, conn):
        resultado_sistema = _resultado_sistema_de_ejemplo()

        juicio = registrar_juicio_clinico(
            conn,
            paciente_id=1,
            diagnostico_registrado="Toxicidad hepática, no progresión de enfermedad.",
            autor="dr. Gómez",
            resultado_sistema=resultado_sistema,
            ahora=AHORA,
        )

        assert juicio.diagnostico_registrado == "Toxicidad hepática, no progresión de enfermedad."
        # El sistema no rechazó el juicio por no coincidir con su propia sugerencia.
        assert "progresion_enfermedad_base" in juicio.perfiles_sugeridos_por_sistema

    def test_no_hay_ninguna_validacion_contra_la_priorizacion_del_sistema(self, conn):
        # Ni siquiera pasar un resultado_sistema es obligatorio: el juicio se
        # acepta igual, sin comparación alguna.
        juicio = registrar_juicio_clinico(
            conn,
            paciente_id=1,
            diagnostico_registrado="Diagnóstico completamente distinto a cualquier alternativa del catálogo.",
            autor="dr. Gómez",
            ahora=AHORA,
        )
        assert juicio.perfiles_sugeridos_por_sistema == ()

    def test_rechaza_un_juicio_vacio_por_validacion_de_forma_no_por_desacuerdo(self, conn):
        with pytest.raises(JuicioClinicoInvalidoError):
            registrar_juicio_clinico(conn, paciente_id=1, diagnostico_registrado="   ", autor="dr. Gómez", ahora=AHORA)

    def test_rechaza_un_autor_vacio(self, conn):
        with pytest.raises(JuicioClinicoInvalidoError):
            registrar_juicio_clinico(conn, paciente_id=1, diagnostico_registrado="algo", autor="", ahora=AHORA)

    def test_un_juicio_nuevo_no_borra_el_historial_de_juicios_anteriores(self, conn):
        registrar_juicio_clinico(conn, paciente_id=1, diagnostico_registrado="Juicio inicial", autor="dr. Gómez", ahora=AHORA)
        registrar_juicio_clinico(conn, paciente_id=1, diagnostico_registrado="Juicio revisado", autor="dr. Gómez", ahora=AHORA)

        historial = obtener_historial_juicios(conn, paciente_id=1)

        assert len(historial) == 2
        assert historial[0].diagnostico_registrado == "Juicio revisado"  # más reciente primero
        assert historial[1].diagnostico_registrado == "Juicio inicial"


# ---------------------------------------------------------------------------
# AC5 — Dado que el médico registra un juicio distinto al sugerido por el
# sistema, cuando el flujo clínico continúa, la decisión del médico
# prevalece como el juicio clínico final.
# ---------------------------------------------------------------------------
class TestElJuicioDelMedicoPrevalece:
    def test_sin_juicio_registrado_la_decision_vigente_es_apoyo_del_sistema(self, conn):
        resultado_sistema = _resultado_sistema_de_ejemplo()

        decision = obtener_decision_diagnostica_vigente(conn, paciente_id=1, resultado_sistema=resultado_sistema)

        assert decision.fuente == "apoyo_sistema"
        assert decision.es_juicio_medico() is False
        assert resultado_sistema.candidatos[0].nombre in decision.contenido

    def test_tras_registrar_un_juicio_la_decision_vigente_es_del_medico(self, conn):
        resultado_sistema = _resultado_sistema_de_ejemplo()
        registrar_juicio_clinico(
            conn,
            paciente_id=1,
            diagnostico_registrado="Toxicidad hepática, no progresión de enfermedad.",
            autor="dr. Gómez",
            resultado_sistema=resultado_sistema,
            ahora=AHORA,
        )

        decision = obtener_decision_diagnostica_vigente(conn, paciente_id=1, resultado_sistema=resultado_sistema)

        assert decision.fuente == "juicio_medico"
        assert decision.es_juicio_medico() is True
        assert decision.contenido == "Toxicidad hepática, no progresión de enfermedad."

    def test_prevalece_incluso_si_el_sistema_sigue_sugiriendo_lo_mismo_despues(self, conn):
        # El juicio del médico no cambia aunque se vuelva a evaluar el caso
        # y el sistema arroje exactamente la misma sugerencia otra vez.
        resultado_sistema_1 = _resultado_sistema_de_ejemplo()
        registrar_juicio_clinico(
            conn, paciente_id=1, diagnostico_registrado="Diagnóstico del médico", autor="dr. Gómez",
            resultado_sistema=resultado_sistema_1, ahora=AHORA,
        )

        resultado_sistema_2 = _resultado_sistema_de_ejemplo()  # "nueva" corrida, misma sugerencia
        decision = obtener_decision_diagnostica_vigente(conn, paciente_id=1, resultado_sistema=resultado_sistema_2)

        assert decision.fuente == "juicio_medico"
        assert decision.contenido == "Diagnóstico del médico"

    def test_el_juicio_mas_reciente_es_el_que_prevalece(self, conn):
        registrar_juicio_clinico(conn, paciente_id=1, diagnostico_registrado="Primer juicio", autor="dr. Gómez", ahora=AHORA)
        registrar_juicio_clinico(conn, paciente_id=1, diagnostico_registrado="Juicio actualizado", autor="dr. Gómez", ahora=AHORA)

        decision = obtener_decision_diagnostica_vigente(conn, paciente_id=1, resultado_sistema=None)

        assert decision.contenido == "Juicio actualizado"

    def test_juicios_de_otro_paciente_no_se_mezclan(self, conn):
        registrar_juicio_clinico(conn, paciente_id=1, diagnostico_registrado="Juicio paciente 1", autor="dr. Gómez", ahora=AHORA)
        registrar_juicio_clinico(conn, paciente_id=2, diagnostico_registrado="Juicio paciente 2", autor="dr. Gómez", ahora=AHORA)

        decision_1 = obtener_decision_diagnostica_vigente(conn, paciente_id=1, resultado_sistema=None)
        decision_2 = obtener_decision_diagnostica_vigente(conn, paciente_id=2, resultado_sistema=None)

        assert decision_1.contenido == "Juicio paciente 1"
        assert decision_2.contenido == "Juicio paciente 2"
