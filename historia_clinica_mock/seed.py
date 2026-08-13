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

    conn.commit()
    return ids
