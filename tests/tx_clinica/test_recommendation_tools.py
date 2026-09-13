"""Tests de tx_clinica/tools/recommendation_tools.py.

No depende de historia_clinica_mock real -- para las tools que reciben
patient_id, se monkeypatchea obtener_paciente_o_error/
construir_facts_paciente/obtener_conexion dentro del propio módulo
recommendation_tools (son imports de nombre, se pueden reemplazar ahí
sin tocar el paquete real). Para el caso de texto libre
(obtener_recomendaciones_tratamiento_con_datos) ni siquiera hace falta
eso -- no toca base de datos en absoluto.

Reutiliza el guidelines_root de conftest.py (compartido con
test_builder.py/test_module_selector_diagnostico.py).
"""

from __future__ import annotations

import json

import pytest

from tx_clinica.tools import recommendation_tools as rt
from tx_clinica.tools.patients_tools import ErrorPacienteNoEncontrado, PacienteResuelto


@pytest.fixture(autouse=True)
def _guidelines_root_de_prueba(monkeypatch, guidelines_root):
    """Todas las tools de este archivo deben resolver módulo contra el
    guidelines_root de prueba, no el real del repo."""
    monkeypatch.setattr(rt, "GUIDELINES_ROOT", guidelines_root)


class TestObtenerRecomendacionesConDatosTextoLibre:
    """El camino más simple: no toca base de datos para nada."""

    def test_datos_completos_da_candidatos(self):
        facts = {
            "cancer_type": "breast", "breast_subtype": "triple_negative",
            "metastatic_disease": "no", "clinical_stage": "II", "treatment_phase": None,
        }
        resultado = json.loads(
            rt.obtener_recomendaciones_tratamiento_con_datos.invoke({"facts_paciente": facts})
        )
        assert resultado["requiere_mas_datos"] is False
        assert resultado["sin_guia_aplicable"] is False
        assert resultado["module_id"] == "breast_early_tnbc"
        assert len(resultado["candidatos"]) == 1
        assert resultado["candidatos"][0]["regimen_id"] == "pembro_neoadjuvant_sequence"

    def test_falta_un_dato_de_elegibilidad_pide_datos_no_dice_sin_guia(self):
        """EL comportamiento central que se corrigió en el refactor,
        ahora probado también a través de la tool real (no solo de
        module_selector directo)."""
        facts = {"cancer_type": "breast"}  # falta breast_subtype y metastatic_disease
        resultado = json.loads(
            rt.obtener_recomendaciones_tratamiento_con_datos.invoke({"facts_paciente": facts})
        )
        assert resultado["requiere_mas_datos"] is True
        assert resultado["sin_guia_aplicable"] is False
        assert "breast_early_tnbc" in resultado["variables_faltantes_por_modulo"]

    def test_ningun_modulo_aplica_es_una_negativa_real(self):
        facts = {
            "cancer_type": "unknown_cancer_type", "breast_subtype": "other",
            "metastatic_disease": "yes", "disease_setting": "adjuvant",
            "melanoma_primary_site": "mucosal", "molecular_pathway_status": "oncogene_addicted",
        }
        resultado = json.loads(
            rt.obtener_recomendaciones_tratamiento_con_datos.invoke({"facts_paciente": facts})
        )
        assert resultado["requiere_mas_datos"] is False
        assert resultado["sin_guia_aplicable"] is True


class TestObtenerRecomendacionesPorId:
    """Estas sí reciben patient_id -- se monkeypatchea todo lo que toca
    base de datos, dentro del namespace de recommendation_tools."""

    def test_paciente_inexistente_da_error_explicito(self, monkeypatch):
        monkeypatch.setattr(
            rt, "obtener_paciente_o_error", lambda pid: ErrorPacienteNoEncontrado(pid)
        )
        resultado = json.loads(rt.obtener_recomendaciones_tratamiento_por_id.invoke({"patient_id": 999}))
        assert resultado["error"] == "paciente_no_registrado"

    def test_paciente_con_datos_completos_da_candidatos(self, monkeypatch):
        monkeypatch.setattr(
            rt, "obtener_paciente_o_error", lambda pid: PacienteResuelto(paciente_id=pid, paciente=object())
        )
        monkeypatch.setattr(rt, "obtener_conexion", lambda: None)
        monkeypatch.setattr(
            rt,
            "construir_facts_paciente",
            lambda conn, pid: {
                "cancer_type": "NSCLC", "molecular_pathway_status": "non_oncogene_addicted",
                "treatment_line": 1, "pdl1_tps": 70, "histology": "non_squamous",
                "immunotherapy_contraindication": "no",
            },
        )
        resultado = json.loads(rt.obtener_recomendaciones_tratamiento_por_id.invoke({"patient_id": 4}))
        assert resultado["requiere_mas_datos"] is False
        assert resultado["module_id"] == "nsclc_metastatic_non_oncogene"
        regimenes = {c["regimen_id"] for c in resultado["candidatos"]}
        assert "pembro_monotherapy" in regimenes

    def test_paciente_con_dato_faltante_pide_datos_nunca_reutiliza_tool_de_texto_libre(self, monkeypatch):
        """Confirma que el paciente REGISTRADO, no solo el de texto
        libre, se beneficia de la Fase 1 corregida.

        Importante: 'dato faltante' acá debe ser un campo de
        ELEGIBILIDAD (el que decide si el módulo aplica -- cancer_type/
        molecular_pathway_status), no un campo de SELECCIÓN de régimen
        (treatment_line/pdl1_tps/histology) -- esos últimos, si faltan,
        no disparan requiere_mas_datos: el módulo igual se resuelve, solo
        que ese régimen en particular queda fuera de los candidatos (ver
        test_dato_faltante_simplemente_omite_el_regimen_sin_error en
        test_builder.py)."""
        monkeypatch.setattr(
            rt, "obtener_paciente_o_error", lambda pid: PacienteResuelto(paciente_id=pid, paciente=object())
        )
        monkeypatch.setattr(rt, "obtener_conexion", lambda: None)
        monkeypatch.setattr(
            rt,
            "construir_facts_paciente",
            # Falta molecular_pathway_status -- ESE sí es un campo de
            # elegibilidad de nsclc_metastatic_non_oncogene.
            lambda conn, pid: {"cancer_type": "NSCLC"},
        )
        resultado = json.loads(rt.obtener_recomendaciones_tratamiento_por_id.invoke({"patient_id": 4}))
        assert resultado["requiere_mas_datos"] is True
        assert resultado["sin_guia_aplicable"] is False
        assert "molecular_pathway_status" in resultado["variables_faltantes_por_modulo"].get(
            "nsclc_metastatic_non_oncogene", []
        )


class TestCompletarDatosPacienteYRecomendar:
    def test_variables_adicionales_se_combinan_con_los_reales_y_ganan_en_conflicto(self, monkeypatch):
        monkeypatch.setattr(
            rt, "obtener_paciente_o_error", lambda pid: PacienteResuelto(paciente_id=pid, paciente=object())
        )
        monkeypatch.setattr(rt, "obtener_conexion", lambda: None)
        monkeypatch.setattr(
            rt,
            "construir_facts_paciente",
            # Facts reales: faltan histology, pdl1_tps e
            # immunotherapy_contraindication a propósito.
            lambda conn, pid: {
                "cancer_type": "NSCLC", "molecular_pathway_status": "non_oncogene_addicted",
                "treatment_line": 1,
            },
        )
        resultado = json.loads(
            rt.completar_datos_paciente_y_recomendar.invoke(
                {
                    "patient_id": 4,
                    "variables_adicionales": {
                        "pdl1_tps": 70,
                        "histology": "non_squamous",
                        "immunotherapy_contraindication": "no",
                    },
                }
            )
        )
        assert resultado["requiere_mas_datos"] is False
        regimenes = {c["regimen_id"] for c in resultado["candidatos"]}
        assert "pembro_monotherapy" in regimenes

    def test_paciente_inexistente_da_error_explicito(self, monkeypatch):
        monkeypatch.setattr(
            rt, "obtener_paciente_o_error", lambda pid: ErrorPacienteNoEncontrado(pid)
        )
        resultado = json.loads(
            rt.completar_datos_paciente_y_recomendar.invoke(
                {"patient_id": 999, "variables_adicionales": {}}
            )
        )
        assert resultado["error"] == "paciente_no_registrado"
