"""Pruebas de aceptación de DX-02 — Apoyo al diagnóstico diferencial."""

from historia_clinica_mock.adapters import obtener_hallazgos_de_paciente
from historia_clinica_mock.repository import HallazgoClinico, obtener_paciente

from dx_clinica.builder import construir_diagnosticos_diferenciales
from dx_clinica.models import SIN_SUSTENTO_SUFICIENTE


# ---------------------------------------------------------------------------
# AC1 — Dado un caso con datos clínicos suficientes, recibo una lista
# priorizada de posibles diagnósticos diferenciales.
# ---------------------------------------------------------------------------
class TestListaPriorizada:
    def test_devuelve_candidatos_ordenados_por_sustento(self, conn_sembrada):
        conn, ids = conn_sembrada
        paciente = obtener_paciente(conn, ids["paciente_carlos"])
        hallazgos = obtener_hallazgos_de_paciente(conn, ids["paciente_carlos"])

        resultado = construir_diagnosticos_diferenciales(paciente, hallazgos)

        assert not resultado.esta_vacio()
        ordenes = [c.orden for c in resultado.candidatos]
        assert ordenes == list(range(1, len(resultado.candidatos) + 1))
        # Progresión de enfermedad tiene más criterios sustentados que
        # los demás candidatos de Carlos: debe quedar primero.
        assert resultado.candidatos[0].perfil_id == "progresion_enfermedad_base"

    def test_prioridad_nunca_expone_porcentaje_ni_probabilidad(self, conn_sembrada):
        conn, ids = conn_sembrada
        paciente = obtener_paciente(conn, ids["paciente_carlos"])
        hallazgos = obtener_hallazgos_de_paciente(conn, ids["paciente_carlos"])
        resultado = construir_diagnosticos_diferenciales(paciente, hallazgos)

        for candidato in resultado.candidatos:
            assert not hasattr(candidato, "probabilidad")
            assert not hasattr(candidato, "porcentaje")
            assert "%" not in candidato.resumen_sustento


# ---------------------------------------------------------------------------
# AC2 — Puedo identificar los datos clínicos del paciente que sustentan la
# inclusión de cada alternativa.
# ---------------------------------------------------------------------------
class TestSustentoIdentificable:
    def test_candidato_expone_ids_de_hallazgos_reales(self, conn_sembrada):
        conn, ids = conn_sembrada
        paciente = obtener_paciente(conn, ids["paciente_maria"])
        hallazgos = obtener_hallazgos_de_paciente(conn, ids["paciente_maria"])
        resultado = construir_diagnosticos_diferenciales(paciente, hallazgos)

        candidato = resultado.candidatos[0]
        assert candidato.perfil_id == "toxicidad_musculoesqueletica"
        assert len(candidato.hallazgos_ids) > 0
        ids_hallazgos_disponibles = {h.id for h in hallazgos}
        assert set(candidato.hallazgos_ids) <= ids_hallazgos_disponibles

    def test_tambien_se_puede_ver_que_criterios_no_estan_sustentados(self, conn_sembrada):
        conn, ids = conn_sembrada
        paciente = obtener_paciente(conn, ids["paciente_carlos"])
        hallazgos = obtener_hallazgos_de_paciente(conn, ids["paciente_carlos"])
        resultado = construir_diagnosticos_diferenciales(paciente, hallazgos)

        infeccioso = next(c for c in resultado.candidatos if c.perfil_id == "proceso_infeccioso_respiratorio")
        assert "Fiebre o temperatura elevada" in infeccioso.criterios_sin_sustento


# ---------------------------------------------------------------------------
# AC3 — Puedo consultar la evidencia asociada mediante la funcionalidad
# definida en IA-04 (aquí: EvidenceReference.resumen_citable()).
# ---------------------------------------------------------------------------
class TestEvidenciaConsultable:
    def test_candidato_con_evidencia_permite_consultar_la_cita_completa(self, conn_sembrada):
        conn, ids = conn_sembrada
        paciente = obtener_paciente(conn, ids["paciente_maria"])
        hallazgos = obtener_hallazgos_de_paciente(conn, ids["paciente_maria"])
        resultado = construir_diagnosticos_diferenciales(paciente, hallazgos)

        candidato = resultado.candidatos[0]
        assert candidato.evidencia is not None
        cita = candidato.evidencia.resumen_citable()
        assert "ESMO" in cita
        assert candidato.evidencia.doi is not None

    def test_candidato_sin_guia_relevante_no_inventa_evidencia(self, conn_sembrada):
        conn, ids = conn_sembrada
        paciente = obtener_paciente(conn, ids["paciente_carlos"])
        hallazgos = obtener_hallazgos_de_paciente(conn, ids["paciente_carlos"])
        resultado = construir_diagnosticos_diferenciales(paciente, hallazgos)

        infeccioso = next(c for c in resultado.candidatos if c.perfil_id == "proceso_infeccioso_respiratorio")
        assert infeccioso.evidencia is None


# ---------------------------------------------------------------------------
# AC4 — El resultado indica explícitamente que es apoyo a la decisión
# clínica y no un diagnóstico definitivo.
# ---------------------------------------------------------------------------
class TestApoyoNoDefinitivo:
    def test_resultado_expone_disclaimer_fijo(self, conn_sembrada):
        conn, ids = conn_sembrada
        paciente = obtener_paciente(conn, ids["paciente_maria"])
        hallazgos = obtener_hallazgos_de_paciente(conn, ids["paciente_maria"])
        resultado = construir_diagnosticos_diferenciales(paciente, hallazgos)

        assert resultado.es_apoyo_a_decision_clinica is True
        assert "NO constituye un diagnóstico definitivo" in resultado.disclaimer

    def test_no_existe_forma_de_confirmar_un_candidato_como_diagnostico_definitivo(self, conn_sembrada):
        conn, ids = conn_sembrada
        paciente = obtener_paciente(conn, ids["paciente_maria"])
        hallazgos = obtener_hallazgos_de_paciente(conn, ids["paciente_maria"])
        resultado = construir_diagnosticos_diferenciales(paciente, hallazgos)

        assert not hasattr(resultado, "confirmar_diagnostico")
        assert not hasattr(resultado, "aceptar")
        for candidato in resultado.candidatos:
            assert not hasattr(candidato, "confirmar")


# ---------------------------------------------------------------------------
# AC5 — Si la información disponible no sustenta una alternativa, el
# sistema no inventa datos clínicos ni evidencia para justificarla.
# ---------------------------------------------------------------------------
class TestNoInventaSinSustento:
    def test_perfil_sin_ningun_hallazgo_que_lo_sustente_no_aparece(self, conn_sembrada):
        conn, ids = conn_sembrada
        # María: su imagen dice explícitamente "sin hallazgos de progresión".
        paciente = obtener_paciente(conn, ids["paciente_maria"])
        hallazgos = obtener_hallazgos_de_paciente(conn, ids["paciente_maria"])
        resultado = construir_diagnosticos_diferenciales(paciente, hallazgos)

        perfiles_incluidos = {c.perfil_id for c in resultado.candidatos}
        assert "progresion_enfermedad_base" not in perfiles_incluidos

    def test_sin_ningun_hallazgo_el_resultado_queda_vacio_con_advertencia_explicita(self):
        resultado = construir_diagnosticos_diferenciales(paciente=None, hallazgos=[])

        assert resultado.esta_vacio()
        assert resultado.advertencia_sin_sustento == SIN_SUSTENTO_SUFICIENTE
        assert resultado.candidatos == ()

    def test_hallazgos_irrelevantes_no_generan_candidatos_falsos(self):
        hallazgos_irrelevantes = [
            HallazgoClinico(id="h1", paciente_id=1, origen="consulta", texto="El paciente saluda cordialmente.", fecha="2026-01-01"),
            HallazgoClinico(id="h2", paciente_id=1, origen="consulta", texto="Se agenda próxima cita administrativa.", fecha="2026-01-01"),
        ]
        resultado = construir_diagnosticos_diferenciales(paciente=None, hallazgos=hallazgos_irrelevantes)
        assert resultado.esta_vacio()
        assert resultado.advertencia_sin_sustento == SIN_SUSTENTO_SUFICIENTE
