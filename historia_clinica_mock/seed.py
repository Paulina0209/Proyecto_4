"""Datos sintéticos de ejemplo para la base de datos mock.

Todos los pacientes, consultas y resultados de este archivo son
ficticios (inventados para pruebas), igual que los "casos sintéticos" que
ya usa este repositorio en `tests/guidelines/cases`. No representan
pacientes reales.
"""

from __future__ import annotations

import sqlite3
from typing import Dict


def sembrar_datos_sinteticos(conn: sqlite3.Connection) -> Dict[str, int]:
    """Inserta pacientes, consultas, laboratorios, imagenología y biomarcadores.

    Devuelve un diccionario con los ids de las filas clave, para que las
    pruebas y los demos puedan referirse a ellas por nombre en vez de por
    número mágico (por ejemplo ``ids["consulta_maria_1"]``).
    """

    cur = conn.cursor()
    ids: Dict[str, int] = {}

    # --- Paciente 1: cáncer de mama triple negativo, estadio temprano ----
    cur.execute(
        "INSERT INTO pacientes (nombre, fecha_nacimiento, sexo, identificacion, "
        "diagnostico_principal, estadio) VALUES (?, ?, ?, ?, ?, ?)",
        (
            "María Fernanda Ríos (sintético)",
            "1973-04-12",
            "femenino",
            "SINT-0001",
            "Cáncer de mama triple negativo",
            "II",
        ),
    )
    ids["paciente_maria"] = cur.lastrowid

    cur.execute(
        "INSERT INTO consultas (paciente_id, fecha, motivo, notas_libres) VALUES (?, ?, ?, ?)",
        (
            ids["paciente_maria"],
            "2026-01-15",
            "Control post-quimioterapia neoadyuvante",
            (
                "La paciente refiere fatiga leve y dolor articular ocasional desde el último ciclo de quimioterapia. "
                "No reporta fiebre ni sangrados. "
                "Examen físico: sin adenopatías axilares palpables, herida quirúrgica previa sin signos de infección. "
                "Impresión diagnóstica: buena respuesta clínica a la quimioterapia neoadyuvante, sin evidencia de progresión. "
                "Plan: se solicita resonancia mamaria de control y se programa evaluación quirúrgica en cuatro semanas."
            ),
        ),
    )
    ids["consulta_maria_1"] = cur.lastrowid

    cur.execute(
        "INSERT INTO laboratorios (paciente_id, consulta_id, fecha, prueba, valor, unidad, rango_referencia, alterado) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (ids["paciente_maria"], ids["consulta_maria_1"], "2026-01-15", "Hemograma - neutrófilos", "2.1", "10^3/uL", "1.8-7.7", 0),
    )
    ids["lab_maria_1"] = cur.lastrowid

    cur.execute(
        "INSERT INTO imagenologia (paciente_id, consulta_id, fecha, modalidad, region, hallazgos) VALUES (?, ?, ?, ?, ?, ?)",
        (
            ids["paciente_maria"],
            ids["consulta_maria_1"],
            "2026-01-14",
            "Ecografía",
            "mama izquierda",
            "Resultado de imagenología: reducción del tamaño tumoral respecto al estudio previo, sin hallazgos de progresión.",
        ),
    )
    ids["imagen_maria_1"] = cur.lastrowid

    cur.execute(
        "INSERT INTO biomarcadores (paciente_id, consulta_id, fecha, biomarcador, resultado) VALUES (?, ?, ?, ?, ?)",
        (ids["paciente_maria"], ids["consulta_maria_1"], "2025-11-02", "HER2", "negativo"),
    )
    ids["biomarcador_maria_1"] = cur.lastrowid

    # Segunda consulta de María: a propósito NO se vincula ningún
    # laboratorio ni imagen a esta consulta, para poder probar que el
    # borrador marca esas secciones como faltantes en vez de inventarlas.
    cur.execute(
        "INSERT INTO consultas (paciente_id, fecha, motivo, notas_libres) VALUES (?, ?, ?, ?)",
        (
            ids["paciente_maria"],
            "2026-04-20",
            "Seguimiento a tres meses",
            (
                "La paciente refiere sentirse mejor, sin dolor articular. "
                "Reporta que retomó su actividad laboral habitual. "
                "Plan: se indica continuar con controles clínicos cada tres meses."
            ),
        ),
    )
    ids["consulta_maria_2"] = cur.lastrowid

    # --- Paciente 2: cáncer de pulmón no microcítico metastásico --------
    cur.execute(
        "INSERT INTO pacientes (nombre, fecha_nacimiento, sexo, identificacion, "
        "diagnostico_principal, estadio) VALUES (?, ?, ?, ?, ?, ?)",
        (
            "Carlos Andrés Muñoz (sintético)",
            "1964-09-03",
            "masculino",
            "SINT-0002",
            "Cáncer de pulmón no microcítico metastásico",
            "IV",
        ),
    )
    ids["paciente_carlos"] = cur.lastrowid

    cur.execute(
        "INSERT INTO consultas (paciente_id, fecha, motivo, notas_libres) VALUES (?, ?, ?, ?)",
        (
            ids["paciente_carlos"],
            "2026-02-03",
            "Consulta inicial por sospecha de recaída",
            (
                "El paciente refiere tos persistente y disnea progresiva de tres semanas de evolución. "
                "Reporta pérdida de apetito y de aproximadamente tres kilogramos de peso. "
                "Examen físico: signos vitales estables, saturación de oxígeno 94% al ambiente, murmullo vesicular disminuido en base derecha. "
                "Impresión diagnóstica: sospecha de progresión de enfermedad pulmonar metastásica. "
                "Plan: se inicia manejo sintomático y se solicita nueva biopsia para reevaluar biomarcadores."
            ),
        ),
    )
    ids["consulta_carlos_1"] = cur.lastrowid

    cur.execute(
        "INSERT INTO laboratorios (paciente_id, consulta_id, fecha, prueba, valor, unidad, rango_referencia, alterado) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (ids["paciente_carlos"], ids["consulta_carlos_1"], "2026-02-03", "Resultado de laboratorio - función hepática (ALT)", "78", "U/L", "7-56", 1),
    )
    ids["lab_carlos_1"] = cur.lastrowid

    cur.execute(
        "INSERT INTO imagenologia (paciente_id, consulta_id, fecha, modalidad, region, hallazgos) VALUES (?, ?, ?, ?, ?, ?)",
        (
            ids["paciente_carlos"],
            ids["consulta_carlos_1"],
            "2026-02-02",
            "TAC",
            "tórax",
            "TAC de tórax: hallazgo de nuevo nódulo pulmonar derecho de 1.2 cm respecto al estudio previo.",
        ),
    )
    ids["imagen_carlos_1"] = cur.lastrowid

    cur.execute(
        "INSERT INTO biomarcadores (paciente_id, consulta_id, fecha, biomarcador, resultado) VALUES (?, ?, ?, ?, ?)",
        (ids["paciente_carlos"], ids["consulta_carlos_1"], "2024-06-10", "EGFR", "positivo (exón 19)"),
    )
    ids["biomarcador_carlos_1"] = cur.lastrowid

 
    facts_maria = {
        "cancer_type": "breast",
        "breast_subtype": "triple_negative",
        "disease_setting": "early",
        "metastatic_disease": "no",
        "clinical_stage": "II",
        "clinical_t_category": "cT2",
        "clinical_n_status": "N0",
        "immune_checkpoint_inhibitor_toxicity_risk": "not_excessive",
        "guideline_temporal_applicability": "applicable",
        "neoadjuvant_chemotherapy_given": "yes",
    }
    for variable, valor in facts_maria.items():
        cur.execute(
            "INSERT INTO datos_clinicos_estructurados "
            "(paciente_id, consulta_id, fecha, variable, valor) VALUES (?, ?, ?, ?, ?)",
            (ids["paciente_maria"], ids["consulta_maria_1"], "2026-01-15", variable, valor),
        )
 
    cur.execute(
        "INSERT INTO comorbilidades "
        "(paciente_id, consulta_id, fecha_registro, condicion, severidad, tipo_contraindicacion_ici) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (ids["paciente_maria"], ids["consulta_maria_1"], "2026-01-15", "ninguna_registrada", None, None),
    )
 
    facts_carlos = {
        "cancer_type": "NSCLC",
        "disease_setting": "metastatic",
        "molecular_pathway_status": "oncogene_addicted",
        "molecular_testing_complete": "yes",
        "guideline_temporal_applicability": "applicable",
        "ecog_ps": "1",
        "histology": "non_squamous",
    }
    for variable, valor in facts_carlos.items():
        cur.execute(
            "INSERT INTO datos_clinicos_estructurados "
            "(paciente_id, consulta_id, fecha, variable, valor) VALUES (?, ?, ?, ?, ?)",
            (ids["paciente_carlos"], ids["consulta_carlos_1"], "2026-02-03", variable, valor),
        )
 
    cur.execute(
        "INSERT INTO comorbilidades "
        "(paciente_id, consulta_id, fecha_registro, condicion, severidad, tipo_contraindicacion_ici) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (ids["paciente_carlos"], ids["consulta_carlos_1"], "2026-02-03", "ninguna_registrada", None, None),
    )
 
    # =====================================================================
    # Paciente 3: melanoma cutáneo, adyuvante estadio IIB
    # =====================================================================
    # Diseñado para calificar en ESMO-MEL-CUT-ADJ-001 (pembro adyuvante
    # 12 meses, estadio IIB-IIC, resección completa, sin NED, ICI elegible).
    cur.execute(
        "INSERT INTO pacientes (nombre, fecha_nacimiento, sexo, identificacion, "
        "diagnostico_principal, estadio) VALUES (?, ?, ?, ?, ?, ?)",
        (
            "Laura Beatriz Gómez (sintético)",
            "1978-02-20",
            "femenino",
            "SINT-0003",
            "Melanoma cutáneo",
            "IIB",
        ),
    )
    ids["paciente_laura"] = cur.lastrowid
 
    cur.execute(
        "INSERT INTO consultas (paciente_id, fecha, motivo, notas_libres) VALUES (?, ?, ?, ?)",
        (
            ids["paciente_laura"],
            "2026-03-10",
            "Control post-resección de melanoma",
            (
                "Paciente con resección completa de melanoma cutáneo estadio IIB. "
                "Sin evidencia de enfermedad residual. "
                "Se discute inicio de terapia adyuvante con pembrolizumab."
            ),
        ),
    )
    ids["consulta_laura_1"] = cur.lastrowid
 
    facts_laura = {
        "cancer_type": "melanoma",
        "melanoma_primary_site": "cutaneous",
        "diagnosis_confirmed": "yes",
        "invasive_disease": "yes",
        "guideline_temporal_applicability": "applicable",
        "treatment_phase": "adjuvant",
        "stage_group": "IIB",
        "complete_resection": "yes",
        "no_evidence_of_disease": "yes",
        "age_years": "47",
        "ici_suitability": "eligible",
        "weeks_since_complete_resection": "4",
    }
    for variable, valor in facts_laura.items():
        cur.execute(
            "INSERT INTO datos_clinicos_estructurados "
            "(paciente_id, consulta_id, fecha, variable, valor) VALUES (?, ?, ?, ?, ?)",
            (ids["paciente_laura"], ids["consulta_laura_1"], "2026-03-10", variable, valor),
        )
 
    cur.execute(
        "INSERT INTO comorbilidades "
        "(paciente_id, consulta_id, fecha_registro, condicion, severidad, tipo_contraindicacion_ici) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (ids["paciente_laura"], ids["consulta_laura_1"], "2026-03-10", "ninguna_registrada", None, None),
    )
 
    # =====================================================================
    # Paciente 4: NSCLC metastásico sin oncogén, primera línea
    # =====================================================================
    # Diseñado para calificar en ESMO-NSCLC-M-FL-001 (pembro monoterapia,
    # PD-L1 >=50, ECOG 0-1, sin contraindicación).
    cur.execute(
        "INSERT INTO pacientes (nombre, fecha_nacimiento, sexo, identificacion, "
        "diagnostico_principal, estadio) VALUES (?, ?, ?, ?, ?, ?)",
        (
            "Roberto Iván Salazar (sintético)",
            "1958-11-30",
            "masculino",
            "SINT-0004",
            "Cáncer de pulmón no microcítico metastásico sin oncogén conductor",
            "IV",
        ),
    )
    ids["paciente_roberto"] = cur.lastrowid
 
    cur.execute(
        "INSERT INTO consultas (paciente_id, fecha, motivo, notas_libres) VALUES (?, ?, ?, ?)",
        (
            ids["paciente_roberto"],
            "2026-04-05",
            "Consulta de inicio de tratamiento sistémico",
            (
                "Paciente con NSCLC metastásico, PD-L1 alto, sin alteraciones "
                "moleculares accionables. Se evalúa inicio de inmunoterapia en "
                "primera línea."
            ),
        ),
    )
    ids["consulta_roberto_1"] = cur.lastrowid
 
    facts_roberto = {
        "cancer_type": "NSCLC",
        "disease_setting": "metastatic",
        "molecular_pathway_status": "non_oncogene_addicted",
        "treatment_line": "1",
        "ecog_ps": "1",
        "pdl1_tps": "70",
        "smoking_status": "former_smoker",
        "immunotherapy_contraindication": "no",
        "histology": "non_squamous",
    }
    for variable, valor in facts_roberto.items():
        cur.execute(
            "INSERT INTO datos_clinicos_estructurados "
            "(paciente_id, consulta_id, fecha, variable, valor) VALUES (?, ?, ?, ?, ?)",
            (ids["paciente_roberto"], ids["consulta_roberto_1"], "2026-04-05", variable, valor),
        )
 
    cur.execute(
        "INSERT INTO comorbilidades "
        "(paciente_id, consulta_id, fecha_registro, condicion, severidad, tipo_contraindicacion_ici) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (ids["paciente_roberto"], ids["consulta_roberto_1"], "2026-04-05", "ninguna_registrada", None, None),
    )
 
    # =====================================================================
    # Paciente 5: RCC de células claras, avanzado, primera línea
    # =====================================================================
    # Diseñado para calificar en ESMO-RCC-ADV-FL-001/002 (pembro +
    # lenvatinib o pembro + axitinib, cualquier riesgo IMDC).
    cur.execute(
        "INSERT INTO pacientes (nombre, fecha_nacimiento, sexo, identificacion, "
        "diagnostico_principal, estadio) VALUES (?, ?, ?, ?, ?, ?)",
        (
            "Patricia Elena Vargas (sintético)",
            "1966-06-15",
            "femenino",
            "SINT-0005",
            "Carcinoma de células renales de células claras, metastásico",
            "IV",
        ),
    )
    ids["paciente_patricia"] = cur.lastrowid
 
    cur.execute(
        "INSERT INTO consultas (paciente_id, fecha, motivo, notas_libres) VALUES (?, ?, ?, ?)",
        (
            ids["paciente_patricia"],
            "2026-05-12",
            "Consulta de inicio de tratamiento sistémico",
            (
                "Paciente con carcinoma renal de células claras metastásico, "
                "histología confirmada. Se evalúa combinación de "
                "inmunoterapia con terapia antiangiogénica en primera línea."
            ),
        ),
    )
    ids["consulta_patricia_1"] = cur.lastrowid
 
    facts_patricia = {
        "cancer_type": "renal_cell_carcinoma",
        "diagnosis_confirmed": "yes",
        "histopathology_confirmed": "yes",
        "rcc_histology": "clear_cell",
        "disease_setting": "metastatic_active",
        "treatment_line": "1",
        "ici_suitability": "eligible",
        "guideline_temporal_applicability": "applicable",
        "imdc_risk_group": "intermediate",
    }
    for variable, valor in facts_patricia.items():
        cur.execute(
            "INSERT INTO datos_clinicos_estructurados "
            "(paciente_id, consulta_id, fecha, variable, valor) VALUES (?, ?, ?, ?, ?)",
            (ids["paciente_patricia"], ids["consulta_patricia_1"], "2026-05-12", variable, valor),
        )
 
    cur.execute(
        "INSERT INTO comorbilidades "
        "(paciente_id, consulta_id, fecha_registro, condicion, severidad, tipo_contraindicacion_ici) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (ids["paciente_patricia"], ids["consulta_patricia_1"], "2026-05-12", "ninguna_registrada", None, None),
    )
    conn.commit()
    return ids
