"""Datos con la forma exacta de la API de cBioPortal (MSK-CHORD), sin red.

Los valores se basan en pacientes reales del estudio público
``msk_chord_2024`` pero están recortados a lo que cada prueba necesita.
"""

import copy
from datetime import date

import pytest

from historia_clinica.db import crear_conexion
from historia_clinica.integracion_externa import ErrorIntegracion

ESTUDIO = "msk_chord_2024"
FECHA_REFERENCIA = date(2026, 9, 29)


def _evento(tipo, inicio, fin=None, **atributos):
    return {"tipo": tipo, "inicio": inicio, "fin": fin, "atributos": atributos}


MAMA = {
    "paciente": "P-0000015",
    "datos_paciente": {
        "GENDER": "Female", "CURRENT_AGE_DEID": "45", "HER2": "No", "HR": "No",
        "STAGE_HIGHEST_RECORDED": "Stage 1-3", "LIVER": "Yes", "BONE": "Yes", "OS_STATUS": "1:DECEASED",
        "SMOKING_PREDICTIONS_3_CLASSES": "Unknown",
    },
    "muestras": {
        "P-0000015-T01-IM3": {
            "CANCER_TYPE": "Breast Cancer", "CANCER_TYPE_DETAILED": "Breast Invasive Ductal Carcinoma",
            "GENE_PANEL": "IMPACT341", "MSI_TYPE": "Stable", "TMB_NONSYNONYMOUS": "7.764087104",
        }
    },
    "eventos": [
        _evento("Diagnosis", -2559, SUBTYPE="Primary", AJCC="I", SUMMARY="Localized",
                DX_DESCRIPTION="INFILTRATING DUCT CARCINOMA | BREAST (M8500/3 | C508)"),
        _evento("Sample acquisition", -7, SAMPLE_ID="P-0000015-T01-IM3"),
        _evento("Sequencing", 0, SAMPLE_ID="P-0000015-T01-IM3"),
        _evento("Treatment", -71, -43, SUBTYPE="Hormone", AGENT="FULVESTRANT"),
        _evento("Treatment", -6, 400, SUBTYPE="Chemo", AGENT="CAPECITABINE"),
        _evento("Treatment", 0, 10, SUBTYPE="Radiation Therapy"),
        _evento("Surgery", -7, SUBTYPE="SAMPLE"),
        _evento("Lab_Test", 398, TEST="CA_15-3", LR_UNIT_MEASURE="Units/ml", RESULT="1412"),
        _evento("Lab_Test", 415, TEST="CA_15-3", LR_UNIT_MEASURE="Units/ml", RESULT="25"),
        _evento("Diagnosis", 273, SUBTYPE="Performance Status", ECOG="0"),
        _evento("Diagnosis", 303, SUBTYPE="Performance Status", ECOG="1"),
        _evento("Diagnosis", 297, SUBTYPE="Progression", PROCEDURE_TYPE="CT", PROGRESSION="Y",
                NLP_PROGRESSION_PROBABILITY="0.9985"),
        _evento("Diagnosis", 297, SUBTYPE="Tumor Sites", TUMOR_SITE="Bone", SOURCE_SPECIFIC="CT",
                CHEST="1", ABDOMEN="1", PELVIS="0", HEAD="0", OTHER="0"),
    ],
    "mutaciones": [
        {"muestra": "P-0000015-T01-IM3", "gen": "PIK3CA", "cambio_proteico": "H1047R", "tipo": "Missense_Mutation"},
    ],
    "fusiones": [],
}

PULMON = {
    "paciente": "P-0000036",
    "datos_paciente": {"GENDER": "Male", "CURRENT_AGE_DEID": "70", "STAGE_HIGHEST_RECORDED": "Stage 4",
                       "OS_STATUS": "0:LIVING", "SMOKING_PREDICTIONS_3_CLASSES": "Former/Current Smoker"},
    "muestras": {
        "P-0000036-T01-IM3": {"CANCER_TYPE": "Non-Small Cell Lung Cancer",
                              "CANCER_TYPE_DETAILED": "Lung Adenocarcinoma", "GENE_PANEL": "IMPACT341"}
    },
    "eventos": [
        _evento("Diagnosis", -30, SUBTYPE="Primary", AJCC="IV", SUMMARY="Distant",
                DX_DESCRIPTION="ADENOCARCINOMA, NOS | LUNG, LOWER LOBE (M8140/3 | C343)"),
        _evento("Sample acquisition", -5, SAMPLE_ID="P-0000036-T01-IM3"),
        _evento("Treatment", 10, 200, SUBTYPE="Targeted", AGENT="ALECTINIB"),
        _evento("Pathology", 5, SUBTYPE="PD-L1 Positive", PDL1_POSITIVE="Yes"),
        _evento("Diagnosis", 20, SUBTYPE="HasCancer", PROCEDURE_TYPE="CT", HAS_CANCER="Y",
                NLP_HAS_CANCER_PROBABILITY="0.99", CHEST="TRUE", ABDOMEN="FALSE", PELVIS="FALSE", HEAD="FALSE", OTHER="FALSE"),
    ],
    "mutaciones": [
        {"muestra": "P-0000036-T01-IM3", "gen": "EGFR", "cambio_proteico": "V834L", "tipo": "Missense_Mutation"},
    ],
    "fusiones": [
        {"muestra": "P-0000036-T01-IM3", "gen_1": "EML4", "gen_2": "ALK", "descripcion": "Protein fusion: in frame (EML4-ALK)"},
    ],
}

#: Paciente con dos cánceres primarios y muestras de dos tipos.
DOS_CANCERES = {
    "paciente": "P-0000012",
    "datos_paciente": {"GENDER": "Female", "CURRENT_AGE_DEID": "60"},
    "muestras": {
        "P-0000012-T01-IM3": {"CANCER_TYPE": "Breast Cancer", "CANCER_TYPE_DETAILED": "Breast Invasive Ductal Carcinoma"},
        "P-0000012-T03-IM3": {"CANCER_TYPE": "Non-Small Cell Lung Cancer", "CANCER_TYPE_DETAILED": "Lung Adenocarcinoma"},
    },
    "eventos": [
        _evento("Diagnosis", -900, SUBTYPE="Primary", AJCC=None, DX_DESCRIPTION="INFILTRATING DUCT CARCINOMA | BREAST"),
        _evento("Diagnosis", -10, SUBTYPE="Primary", AJCC="IIIB", DX_DESCRIPTION="ADENOCARCINOMA, NOS | LUNG"),
    ],
    "mutaciones": [],
    "fusiones": [],
}

PACIENTES = {p["paciente"]: p for p in (MAMA, PULMON, DOS_CANCERES)}
PANEL_IMPACT341 = {"PIK3CA", "ESR1", "BRCA1", "BRCA2", "EGFR", "KRAS", "BRAF", "MET", "ERBB2",
                   "ALK", "ROS1", "RET", "NTRK1", "NTRK2", "NTRK3"}
ENTREZ = {"PIK3CA": 5290, "ESR1": 2099, "BRCA1": 672, "BRCA2": 675, "EGFR": 1956, "KRAS": 3845, "BRAF": 673,
          "MET": 4233, "ERBB2": 2064, "ALK": 238, "ROS1": 6098, "RET": 5979, "NTRK1": 4914, "NTRK2": 4915, "NTRK3": 4916}


class ClienteFalso:
    """Mismos métodos que ``ClienteCBioPortal``, respondiendo desde ``PACIENTES``."""

    def __init__(self, pacientes=None, falla_en=()):
        self.pacientes = copy.deepcopy(pacientes if pacientes is not None else PACIENTES)
        self.falla_en = set(falla_en)
        self.llamadas = []

    def _p(self, paciente):
        self.llamadas.append(paciente)
        if paciente in self.falla_en:
            raise ErrorIntegracion("cBioPortal respondió HTTP 502 en /studies/msk_chord_2024/patients.")
        return self.pacientes[paciente]

    def tipo_de_cancer_por_muestra(self, estudio):
        return [
            {"paciente": p, "muestra": m, "tipo_cancer": d["CANCER_TYPE"]}
            for p, datos in self.pacientes.items() for m, d in datos["muestras"].items()
        ]

    def perfiles_moleculares(self, estudio):
        return {"MUTATION_EXTENDED": f"{estudio}_mutations", "STRUCTURAL_VARIANT": f"{estudio}_structural_variants"}

    def datos_clinicos_paciente(self, estudio, paciente):
        return dict(self._p(paciente)["datos_paciente"])

    def muestras_de_paciente(self, estudio, paciente):
        return sorted(self._p(paciente)["muestras"])

    def datos_clinicos_muestra(self, estudio, muestra):
        paciente = next(p for p, d in self.pacientes.items() if muestra in d["muestras"])
        return dict(self.pacientes[paciente]["muestras"][muestra])

    def eventos_clinicos(self, estudio, paciente):
        return copy.deepcopy(self._p(paciente)["eventos"])

    def entrez_ids(self, simbolos):
        return {s: ENTREZ[s] for s in simbolos if s in ENTREZ}

    def genes_de_panel(self, panel):
        return set(PANEL_IMPACT341)

    def mutaciones(self, perfil, muestras, genes):
        return [m for d in self.pacientes.values() for m in d["mutaciones"] if m["muestra"] in muestras and m["gen"] in genes]

    def fusiones(self, perfil, muestras, genes):
        return [f for d in self.pacientes.values() for f in d["fusiones"]
                if f["muestra"] in muestras and ({f["gen_1"], f["gen_2"]} & set(genes))]


@pytest.fixture
def conn():
    connection = crear_conexion(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def cliente():
    return ClienteFalso()


@pytest.fixture
def fuente(cliente):
    from cbioportal import FuenteCBioPortal

    return FuenteCBioPortal(cliente, FECHA_REFERENCIA)
