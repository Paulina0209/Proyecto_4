"""Puente entre la base de datos mock y el generador de notas de IA-02.

Esta es la pieza que "pega" la base de datos con `ia_clinica.notes`: toma
el id de una consulta guardada y construye el `ClinicalContext` que
`ClinicalNoteGenerator` necesita, con un `SourceSpan` por cada oración de
la nota dictada y por cada resultado de laboratorio, imagenología o
biomarcador que esté vinculado a esa consulta puntual (no todo el
historial del paciente — solo lo que corresponde a esa consulta).

Cada `SourceSpan` conserva el id real de la fila de la base de datos que
lo originó (por ejemplo ``lab-7``, ``imagen-3``), así que la trazabilidad
del borrador de nota generado apunta hasta el registro exacto de la base
de datos, no solo a "la consulta" en general.
"""

from __future__ import annotations

import sqlite3

from ia_clinica.notes.models import ClinicalContext, SourceSpan, split_sentences

from historia_clinica_mock.repository import (
    biomarcadores_de_consulta,
    imagenologia_de_consulta,
    laboratorios_de_consulta,
    obtener_consulta,
    obtener_paciente,
)


class ConsultaNoEncontradaError(Exception):
    """La consulta solicitada no existe en la base de datos."""


def construir_contexto_clinico(conn: sqlite3.Connection, consulta_id: int) -> ClinicalContext:
    """Construye el ``ClinicalContext`` de IA-02 a partir de una consulta guardada.

    Lanza ``ConsultaNoEncontradaError`` si el id no existe, en vez de
    devolver silenciosamente un contexto vacío (que el generador de todas
    formas rechazaría, pero es más claro fallar aquí con un mensaje
    específico).
    """

    consulta = obtener_consulta(conn, consulta_id)
    if consulta is None:
        raise ConsultaNoEncontradaError(f"No existe ninguna consulta con id={consulta_id}.")

    paciente = obtener_paciente(conn, consulta.paciente_id)
    segments = []

    for i, oracion in enumerate(split_sentences(consulta.notas_libres), start=1):
        segments.append(
            SourceSpan(
                id=f"consulta-{consulta.id}-nota-{i}",
                text=oracion,
                origin="consulta",
                timestamp=consulta.fecha,
            )
        )

    for lab in laboratorios_de_consulta(conn, consulta_id):
        alerta = " (fuera de rango de referencia)" if lab.alterado else ""
        texto = (
            f"Resultado de laboratorio — {lab.prueba}: {lab.valor}"
            f"{' ' + lab.unidad if lab.unidad else ''}"
            f" (referencia: {lab.rango_referencia or 'no especificada'}){alerta}."
        )
        segments.append(SourceSpan(id=f"lab-{lab.id}", text=texto, origin="laboratorio", timestamp=lab.fecha))

    for imagen in imagenologia_de_consulta(conn, consulta_id):
        texto = f"{imagen.modalidad} de {imagen.region}: {imagen.hallazgos}"
        segments.append(SourceSpan(id=f"imagen-{imagen.id}", text=texto, origin="imagenologia", timestamp=imagen.fecha))

    for biomarcador in biomarcadores_de_consulta(conn, consulta_id):
        texto = f"Biomarcador {biomarcador.biomarcador}: {biomarcador.resultado}."
        segments.append(
            SourceSpan(id=f"biomarcador-{biomarcador.id}", text=texto, origin="biomarcador", timestamp=biomarcador.fecha)
        )

    patient_ref = f"paciente-{paciente.id}" if paciente else f"paciente-{consulta.paciente_id}"
    return ClinicalContext(consult_id=f"consulta-{consulta.id}", patient_ref=patient_ref, segments=segments)
