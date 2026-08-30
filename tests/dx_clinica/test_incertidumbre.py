"""Pruebas de aceptación de DX-03 — Manejo de la incertidumbre diagnóstica."""

from datetime import datetime, timezone

from dx_clinica.incertidumbre import TipoIncertidumbre, analizar_incertidumbre
from dx_clinica.models import CriterioEvaluado, DiagnosticoDiferencialCandidato, ResultadoDiagnosticoDiferencial

AHORA = datetime(2026, 8, 30, tzinfo=timezone.utc)


def _candidato(perfil_id, nombre, orden, sustentados_ids, sin_sustento):
    criterios_sustentados = tuple(
        CriterioEvaluado(id=f"{perfil_id}-c{i}", descripcion=f"criterio sustentado #{i}", hallazgos_ids=(hid,))
        for i, hid in enumerate(sustentados_ids, start=1)
    )
    return DiagnosticoDiferencialCandidato(
        perfil_id=perfil_id,
        nombre=nombre,
        orden=orden,
        criterios_sustentados=criterios_sustentados,
        criterios_sin_sustento=tuple(sin_sustento),
        evidencia=None,
    )


def _resultado(*candidatos, advertencia=None):
    return ResultadoDiagnosticoDiferencial(
        paciente_id=1, generado_en=AHORA, candidatos=tuple(candidatos), advertencia_sin_sustento=advertencia
    )


# ---------------------------------------------------------------------------
# AC1 — Dado que los datos clínicos disponibles son insuficientes para
# diferenciar razonablemente entre alternativas, cuando solicito apoyo
# para diagnóstico diferencial, el sistema comunica explícitamente la
# presencia de incertidumbre.
# ---------------------------------------------------------------------------
class TestComunicaIncertidumbreExplicitamente:
    def test_detecta_ambiguedad_cuando_hay_empate_exacto_en_el_primer_lugar(self):
        a = _candidato("perfil_a", "Alternativa A", 1, ["h1", "h2"], ["pendiente A"])
        b = _candidato("perfil_b", "Alternativa B", 2, ["h3", "h4"], ["pendiente B"])
        resultado = _resultado(a, b)

        analisis = analizar_incertidumbre(resultado)

        assert analisis.hay_incertidumbre is True
        assert TipoIncertidumbre.AMBIGUEDAD_ENTRE_ALTERNATIVAS in analisis.tipos
        assert set(analisis.perfiles_ambiguos) == {"perfil_a", "perfil_b"}
        assert "Alternativa A" in analisis.mensaje and "Alternativa B" in analisis.mensaje

    def test_no_reporta_incertidumbre_con_un_lider_claro_completo_y_especifico(self):
        lider = _candidato("perfil_c", "Alternativa C", 1, ["h1", "h2", "h3"], [])
        otro = _candidato("perfil_d", "Alternativa D", 2, ["h4"], [])
        resultado = _resultado(lider, otro)

        analisis = analizar_incertidumbre(resultado)

        assert analisis.hay_incertidumbre is False
        assert analisis.tipos == ()

    def test_caso_vacio_tambien_se_comunica_como_incertidumbre(self):
        resultado = _resultado(advertencia="No hay información suficiente en el expediente.")

        analisis = analizar_incertidumbre(resultado)

        assert analisis.hay_incertidumbre is True
        assert "No hay información suficiente" in analisis.mensaje


# ---------------------------------------------------------------------------
# AC2 — Dado que falta información clínica relevante, cuando el sistema
# identifica esa ausencia, indica qué información adicional podría
# ayudar a diferenciar entre las alternativas diagnósticas.
# ---------------------------------------------------------------------------
class TestSugiereInformacionAdicional:
    def test_sugiere_los_criterios_pendientes_del_lider(self):
        lider = _candidato("perfil_c", "Alternativa C", 1, ["h1"], ["dato pendiente 1", "dato pendiente 2"])
        resultado = _resultado(lider)

        analisis = analizar_incertidumbre(resultado)

        assert TipoIncertidumbre.INFORMACION_FALTANTE in analisis.tipos
        assert set(analisis.informacion_adicional_sugerida) == {"dato pendiente 1", "dato pendiente 2"}

    def test_sugerencias_no_se_presentan_como_ordenes_automaticas(self):
        lider = _candidato("perfil_c", "Alternativa C", 1, ["h1"], ["dato pendiente"])
        resultado = _resultado(lider)

        analisis = analizar_incertidumbre(resultado)

        assert "no" in analisis.disclaimer_sugerencias.lower()
        assert "órdenes automáticas" in analisis.disclaimer_sugerencias
        assert "oncólogo tratante" in analisis.disclaimer_sugerencias

    def test_en_empate_sugiere_lo_pendiente_de_todas_las_alternativas_empatadas(self):
        a = _candidato("perfil_a", "Alternativa A", 1, ["h1"], ["pendiente A"])
        b = _candidato("perfil_b", "Alternativa B", 2, ["h2"], ["pendiente B"])
        resultado = _resultado(a, b)

        analisis = analizar_incertidumbre(resultado)

        assert "pendiente A" in analisis.informacion_adicional_sugerida
        assert "pendiente B" in analisis.informacion_adicional_sugerida

    def test_sin_ningun_candidato_sugiere_criterios_de_todo_el_catalogo_disponible(self):
        resultado = _resultado(advertencia="No hay información suficiente.")

        analisis = analizar_incertidumbre(resultado)

        assert len(analisis.informacion_adicional_sugerida) > 0
        # No se inventa nada más específico de lo que el catálogo realmente conoce.
        assert "Dolor articular u óseo de aparición reciente" in analisis.informacion_adicional_sugerida


# ---------------------------------------------------------------------------
# AC3 — Dado que el sistema no cuenta con información suficiente, cuando
# analiza el caso, no fuerza una priorización artificial de diagnósticos
# diferenciales.
# ---------------------------------------------------------------------------
class TestNoFuerzaPriorizacionArtificial:
    def test_el_empate_se_reporta_pero_no_se_elimina_ninguna_alternativa_del_resultado_original(self):
        a = _candidato("perfil_a", "Alternativa A", 1, ["h1"], [])
        b = _candidato("perfil_b", "Alternativa B", 2, ["h2"], [])
        resultado = _resultado(a, b)

        analizar_incertidumbre(resultado)  # el análisis es de solo lectura

        assert len(resultado.candidatos) == 2
        assert resultado.candidatos[0].orden == 1
        assert resultado.candidatos[1].orden == 2

    def test_no_existe_ningun_metodo_que_elija_un_ganador_artificial(self):
        a = _candidato("perfil_a", "Alternativa A", 1, ["h1"], [])
        b = _candidato("perfil_b", "Alternativa B", 2, ["h2"], [])
        analisis = analizar_incertidumbre(_resultado(a, b))

        assert not hasattr(analisis, "elegir_ganador")
        assert not hasattr(analisis, "candidatos")
        assert not hasattr(analisis, "forzar_prioridad")

    def test_resultado_vacio_sigue_vacio_tras_el_analisis(self):
        resultado = _resultado(advertencia="No hay información suficiente.")

        analizar_incertidumbre(resultado)

        assert resultado.esta_vacio()
        assert resultado.candidatos == ()


# ---------------------------------------------------------------------------
# Nota técnica de DX-03: distinguir información faltante, información
# contradictoria (aquí: ambigüedad por evidencia compartida entre
# alternativas empatadas) e incertidumbre inherente al caso.
# ---------------------------------------------------------------------------
class TestDistincionEntreTiposDeIncertidumbre:
    def test_perfil_de_un_solo_criterio_ya_completo_es_incertidumbre_inherente_no_informacion_faltante(self):
        lider = _candidato("perfil_pobre", "Alternativa de un solo criterio", 1, ["h1"], [])
        resultado = _resultado(lider)

        analisis = analizar_incertidumbre(resultado)

        assert analisis.tipos == (TipoIncertidumbre.INCERTIDUMBRE_INHERENTE_AL_CASO,)
        assert TipoIncertidumbre.INFORMACION_FALTANTE not in analisis.tipos

    def test_puede_reportar_mas_de_un_tipo_a_la_vez(self):
        # Perfil de un solo criterio total, y ese único criterio aún sin sustento.
        lider = _candidato("perfil_pobre_incompleto", "Alternativa pobre e incompleta", 1, [], ["único criterio del perfil"])
        resultado = _resultado(lider)

        analisis = analizar_incertidumbre(resultado)

        assert TipoIncertidumbre.INFORMACION_FALTANTE in analisis.tipos
        assert TipoIncertidumbre.INCERTIDUMBRE_INHERENTE_AL_CASO in analisis.tipos

    def test_umbral_de_especificidad_del_perfil_es_configurable(self):
        lider = _candidato("perfil_dos_criterios", "Alternativa de dos criterios", 1, ["h1", "h2"], [])
        resultado = _resultado(lider)

        # Con el umbral por defecto (2), un perfil de 2 criterios no cuenta como pobre.
        assert TipoIncertidumbre.INCERTIDUMBRE_INHERENTE_AL_CASO not in analizar_incertidumbre(resultado).tipos
        # Con un umbral más exigente, sí.
        analisis_exigente = analizar_incertidumbre(resultado, minimo_criterios_perfil_confiable=3)
        assert TipoIncertidumbre.INCERTIDUMBRE_INHERENTE_AL_CASO in analisis_exigente.tipos
