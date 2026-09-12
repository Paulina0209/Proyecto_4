"""Pruebas de aceptación de DX-01 — Recomendación de estudios necesarios.

Cada clase de prueba está anclada a uno de los dos criterios de
aceptación de la historia de usuario, más pruebas de la regla de "no
inventar una sugerencia genérica" y una integración con el expediente
sintético real (mismos pacientes/escenarios que ``demo_estudios.py``).
"""

from datetime import datetime

import pytest

from historia_clinica_mock.repository import HallazgoClinico

from dx_clinica.recomendacion_estudios import (
    SOSPECHA_NO_RECONOCIDA,
    recomendar_estudios,
)


def _hallazgo(id, origen, texto, fecha):
    return HallazgoClinico(id=id, paciente_id=1, origen=origen, texto=texto, fecha=fecha)


# ---------------------------------------------------------------------------
# AC1 — Dado un caso con sospecha diagnóstica definida, cuando solicito
# recomendación de estudios, recibo una lista priorizada con justificación de
# cada estudio sugerido.
# ---------------------------------------------------------------------------
class TestListaPriorizadaConJustificacion:
    def test_sin_estudios_previos_se_sugieren_todos_los_del_perfil(self):
        resultado = recomendar_estudios(
            paciente_id=1,
            sospecha_diagnostica="Sospecha de toxicidad musculoesquelética asociada a tratamiento",
            hallazgos=[],
            ahora=datetime(2026, 1, 1),
        )

        nombres = {e.nombre for e in resultado.estudios_sugeridos}
        assert len(resultado.estudios_sugeridos) == 2
        assert any("reumatológico" in n for n in nombres)
        assert any("Radiografía" in n for n in nombres)
        assert not resultado.estudios_omitidos_por_redundantes

    def test_cada_estudio_sugerido_trae_justificacion_no_vacia(self):
        resultado = recomendar_estudios(
            paciente_id=1,
            sospecha_diagnostica="sospecha de progresión de enfermedad",
            hallazgos=[],
            ahora=datetime(2026, 1, 1),
        )

        assert resultado.estudios_sugeridos
        for estudio in resultado.estudios_sugeridos:
            assert estudio.justificacion.strip() != ""

    def test_el_orden_es_explicable_por_prioridad_del_catalogo_no_un_puntaje(self):
        resultado = recomendar_estudios(
            paciente_id=1,
            sospecha_diagnostica="sospecha de progresión de enfermedad metastásica",
            hallazgos=[],
            ahora=datetime(2026, 1, 1),
        )

        ordenes = [e.orden for e in resultado.estudios_sugeridos]
        assert ordenes == list(range(1, len(ordenes) + 1))
        # Los de prioridad 1 del catálogo deben quedar antes que los de prioridad 2.
        tipos_por_orden = {e.orden: e.id for e in resultado.estudios_sugeridos}
        assert tipos_por_orden[1] in {"hemograma_completo", "tac_torax_control"}

    def test_resultado_es_siempre_apoyo_a_decision_clinica_no_orden_automatica(self):
        resultado = recomendar_estudios(
            paciente_id=1, sospecha_diagnostica="sospecha de progresión", hallazgos=[], ahora=datetime(2026, 1, 1)
        )
        assert resultado.es_apoyo_a_decision_clinica is True
        assert "no constituye una orden médica automática" in resultado.disclaimer


# ---------------------------------------------------------------------------
# AC2 — Dado que ya existen estudios equivalentes recientes en el
# expediente, cuando se genera la recomendación, el sistema no vuelve a
# sugerir un estudio redundante.
# ---------------------------------------------------------------------------
class TestNoRepiteEstudiosRedundantes:
    def test_estudio_equivalente_reciente_no_se_vuelve_a_sugerir(self):
        hallazgos = [_hallazgo("lab-1", "laboratorio", "Resultado de laboratorio — Hemograma: 4.2.", "2026-01-10")]

        resultado = recomendar_estudios(
            paciente_id=1,
            sospecha_diagnostica="sospecha de progresión",
            hallazgos=hallazgos,
            ahora=datetime(2026, 1, 20),
        )

        ids_sugeridos = {e.id for e in resultado.estudios_sugeridos}
        assert "hemograma_completo" not in ids_sugeridos
        omitido = next(o for o in resultado.estudios_omitidos_por_redundantes if o.id == "hemograma_completo")
        assert omitido.hallazgo_existente_id == "lab-1"
        assert omitido.fecha_hallazgo_existente == "2026-01-10"
        assert "redundante" in omitido.motivo

    def test_estudio_equivalente_pero_antiguo_si_se_vuelve_a_sugerir(self):
        hallazgos = [
            _hallazgo("biomarcador-1", "biomarcador", "Biomarcador EGFR: positivo (exón 19).", "2023-01-01")
        ]

        resultado = recomendar_estudios(
            paciente_id=1,
            sospecha_diagnostica="sospecha de progresión",
            hallazgos=hallazgos,
            ventana_dias_estudio_reciente=90,
            ahora=datetime(2026, 1, 20),
        )

        ids_sugeridos = {e.id for e in resultado.estudios_sugeridos}
        assert "reevaluacion_biomarcadores_moleculares" in ids_sugeridos
        assert not any(
            o.id == "reevaluacion_biomarcadores_moleculares" for o in resultado.estudios_omitidos_por_redundantes
        )

    def test_estudio_existente_de_otro_tipo_no_cuenta_como_equivalente(self):
        # Un hallazgo de "imagenologia" que mencione la palabra "hemograma"
        # (por error de texto libre, hipotéticamente) no debe poder anular
        # la sugerencia de un estudio de laboratorio: el tipo debe coincidir.
        hallazgos = [_hallazgo("imagen-1", "imagenologia", "Se menciona hemograma previo en el informe.", "2026-01-10")]

        resultado = recomendar_estudios(
            paciente_id=1,
            sospecha_diagnostica="sospecha de progresión",
            hallazgos=hallazgos,
            ahora=datetime(2026, 1, 20),
        )

        ids_sugeridos = {e.id for e in resultado.estudios_sugeridos}
        assert "hemograma_completo" in ids_sugeridos

    def test_ventana_de_recencia_es_configurable(self):
        hallazgos = [_hallazgo("lab-1", "laboratorio", "Perfil hepático dentro de rango.", "2025-11-01")]

        resultado_ventana_corta = recomendar_estudios(
            paciente_id=1,
            sospecha_diagnostica="sospecha de progresión",
            hallazgos=hallazgos,
            ventana_dias_estudio_reciente=30,
            ahora=datetime(2026, 1, 20),
        )
        resultado_ventana_larga = recomendar_estudios(
            paciente_id=1,
            sospecha_diagnostica="sospecha de progresión",
            hallazgos=hallazgos,
            ventana_dias_estudio_reciente=365,
            ahora=datetime(2026, 1, 20),
        )

        assert "perfil_hepatico" in {e.id for e in resultado_ventana_corta.estudios_sugeridos}
        assert "perfil_hepatico" in {o.id for o in resultado_ventana_larga.estudios_omitidos_por_redundantes}


# ---------------------------------------------------------------------------
# Regla de negocio: nunca se inventa una lista genérica para una sospecha
# que el catálogo no reconoce.
# ---------------------------------------------------------------------------
class TestSospechaNoReconocida:
    def test_sospecha_sin_coincidencia_no_sugiere_nada(self):
        resultado = recomendar_estudios(
            paciente_id=1, sospecha_diagnostica="quiste ovárico funcional", hallazgos=[], ahora=datetime(2026, 1, 1)
        )

        assert resultado.esta_vacio()
        assert resultado.estudios_omitidos_por_redundantes == ()
        assert resultado.advertencia_sospecha_no_reconocida == SOSPECHA_NO_RECONOCIDA

    def test_sospecha_negada_no_cuenta_como_coincidencia(self):
        resultado = recomendar_estudios(
            paciente_id=1,
            sospecha_diagnostica="se descarta progresión de la enfermedad",
            hallazgos=[],
            ahora=datetime(2026, 1, 1),
        )

        assert resultado.esta_vacio()
        assert resultado.advertencia_sospecha_no_reconocida is not None


# ---------------------------------------------------------------------------
# Integración con el expediente sintético real (mismos escenarios que
# ``dx_clinica/demo_estudios.py``).
# ---------------------------------------------------------------------------
class TestIntegracionConExpedienteReal:
    def test_maria_toxicidad_musculoesqueletica_sin_estudios_previos(self, conn_sembrada):
        from historia_clinica_mock.adapters import obtener_hallazgos_de_paciente

        conn, ids = conn_sembrada
        hallazgos = obtener_hallazgos_de_paciente(conn, ids["paciente_maria"])

        resultado = recomendar_estudios(
            paciente_id=ids["paciente_maria"],
            sospecha_diagnostica="Sospecha de toxicidad musculoesquelética asociada a tratamiento oncológico",
            hallazgos=hallazgos,
            ahora=datetime(2026, 1, 20),
        )

        assert len(resultado.estudios_sugeridos) == 2
        assert not resultado.estudios_omitidos_por_redundantes

    def test_carlos_progresion_no_repite_estudios_recientes_pero_reevalua_biomarcador_antiguo(self, conn_sembrada):
        from historia_clinica_mock.adapters import obtener_hallazgos_de_paciente

        conn, ids = conn_sembrada
        hallazgos = obtener_hallazgos_de_paciente(conn, ids["paciente_carlos"])

        resultado = recomendar_estudios(
            paciente_id=ids["paciente_carlos"],
            sospecha_diagnostica="Sospecha de progresión de enfermedad pulmonar metastásica",
            hallazgos=hallazgos,
            ahora=datetime(2026, 2, 10),
        )

        ids_sugeridos = {e.id for e in resultado.estudios_sugeridos}
        ids_omitidos = {o.id for o in resultado.estudios_omitidos_por_redundantes}

        assert ids_sugeridos == {"hemograma_completo", "reevaluacion_biomarcadores_moleculares"}
        assert ids_omitidos == {"perfil_hepatico", "tac_torax_control"}
