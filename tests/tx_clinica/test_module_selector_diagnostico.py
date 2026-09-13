"""Tests de module_selector.seleccionar_modulo_con_diagnostico (Fase 1
de TX-01/TX-03/TX-04) -- distingue "ningún módulo aplica" (negativa
real) de "no se puede determinar porque falta un dato clínico", algo
que seleccionar_modulo() (sin tocar, usada por builder.py) no podía
hacer.

Usa el mismo fixture guidelines_root de conftest.py (los 4 módulos de
prueba ya definidos para test_builder.py) -- no se inventa un fixture
aparte, para probar el diagnóstico contra escenarios reales.
"""

from __future__ import annotations

from tx_clinica.module_selector import seleccionar_modulo, seleccionar_modulo_con_diagnostico


class TestEstadoResuelto:
    def test_datos_completos_resuelve_el_modulo_correcto(self, guidelines_root):
        facts = {
            "cancer_type": "breast", "breast_subtype": "triple_negative",
            "metastatic_disease": "no",
        }
        resultado = seleccionar_modulo_con_diagnostico(facts, guidelines_root)
        assert resultado.estado == "resuelto"
        assert resultado.modulo_id == "breast_early_tnbc"
        assert resultado.variables_faltantes_por_modulo == {}

    def test_coincide_con_seleccionar_modulo_original_cuando_esta_resuelto(self, guidelines_root):
        """Mismos facts, misma respuesta que la función original -- el
        diagnóstico no cambia el resultado cuando SÍ se puede resolver,
        solo agrega información cuando no se puede."""
        facts = {"cancer_type": "NSCLC", "molecular_pathway_status": "non_oncogene_addicted"}
        via_diagnostico = seleccionar_modulo_con_diagnostico(facts, guidelines_root)
        via_original = seleccionar_modulo(facts, guidelines_root)
        assert via_diagnostico.estado == "resuelto"
        assert via_diagnostico.modulo_id == via_original


class TestEstadoVariablesFaltantes:
    def test_falta_un_dato_de_elegibilidad_no_se_confunde_con_no_aplica(self, guidelines_root):
        """ESTE es el hueco real que corrige: antes, un dato faltante en
        la regla de scope (eligibility.yaml) terminaba indistinguible de
        'este módulo no aplica'. cancer_type=breast coincide con el
        scope de breast_early_tnbc, pero falta breast_subtype y
        metastatic_disease -- eso es 'no se sabe todavía', no 'no
        aplica'."""
        facts = {"cancer_type": "breast"}
        resultado = seleccionar_modulo_con_diagnostico(facts, guidelines_root)

        assert resultado.estado == "variables_faltantes"
        assert resultado.modulo_id is None
        assert "breast_early_tnbc" in resultado.variables_faltantes_por_modulo
        faltantes = set(resultado.variables_faltantes_por_modulo["breast_early_tnbc"])
        assert faltantes == {"breast_subtype", "metastatic_disease"}

    def test_la_funcion_original_no_distingue_esto_confirma_el_hueco(self, guidelines_root):
        """Documenta el comportamiento VIEJO (sin tocar, sigue igual):
        con el mismo faltante de arriba, seleccionar_modulo() original
        simplemente devuelve None -- indistinguible de 'ningún módulo
        aplica'. Por eso hizo falta la función nueva."""
        facts = {"cancer_type": "breast"}
        assert seleccionar_modulo(facts, guidelines_root) is None

    def test_puede_haber_mas_de_un_modulo_candidato_con_huecos_distintos(self, guidelines_root):
        """Si el dato falta de forma tal que más de un módulo queda en
        'no evaluable' (no en 'no aplica'), deben listarse todos, no solo
        el primero -- el oncólogo necesita ver todas las opciones para
        decidir qué completar."""
        # cancer_type ausente por completo: ningún módulo puede ni
        # siquiera evaluar su primera condición de scope.
        facts = {}
        resultado = seleccionar_modulo_con_diagnostico(facts, guidelines_root)
        assert resultado.estado == "variables_faltantes"
        assert "cancer_type" in resultado.variables_faltantes_por_modulo.get("breast_early_tnbc", [])
        assert "cancer_type" in resultado.variables_faltantes_por_modulo.get("cutaneous_melanoma", [])


class TestEstadoNingunModuloAplica:
    def test_negativa_real_no_confundida_con_dato_faltante(self, guidelines_root):
        """cancer_type con un valor que NINGÚN módulo reconoce -- esto sí
        es una negativa real y completa, no un dato faltante (el dato
        está presente, solo que no calza con ningún scope)."""
        facts = {
            "cancer_type": "unknown_cancer_type", "breast_subtype": "other",
            "metastatic_disease": "yes", "disease_setting": "adjuvant",
            "melanoma_primary_site": "mucosal", "molecular_pathway_status": "oncogene_addicted",
        }
        resultado = seleccionar_modulo_con_diagnostico(facts, guidelines_root)
        assert resultado.estado == "ningun_modulo_aplica"
        assert resultado.modulo_id is None
        assert resultado.variables_faltantes_por_modulo == {}

    def test_valor_presente_que_descarta_por_corto_circuito_no_es_variables_faltantes(self, guidelines_root):
        """Caso límite, contraste con el anterior: cancer_type='melanoma'
        descarta por sí solo (corto circuito del AND de 3 valores) a los
        4 módulos de prueba -- ninguno necesita el resto de los datos
        para saber que no aplica (breast_* piden cancer_type==breast,
        nsclc pide cancer_type==NSCLC, y cutaneous_melanoma sí acepta
        cancer_type==melanoma pero descarta por melanoma_primary_site=
        mucosal, no en ['cutaneous']). Con las 4 condiciones ya resueltas
        a False de forma explícita, el resultado es una negativa REAL,
        no falta de datos -- aunque otros campos (breast_subtype, etc.)
        nunca se hayan proporcionado."""
        facts = {"cancer_type": "melanoma", "melanoma_primary_site": "mucosal"}
        resultado = seleccionar_modulo_con_diagnostico(facts, guidelines_root)
        assert resultado.estado == "ningun_modulo_aplica"
        assert resultado.variables_faltantes_por_modulo == {}
