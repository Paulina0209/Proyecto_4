"""Puentes entre la base de datos mock y los módulos de IA que la consumen.

Dos adaptadores conviven aquí, porque cada historia necesita un recorte
distinto del expediente:

    - ``construir_contexto_clinico`` (IA-02): arma el ``ClinicalContext``
      de una consulta puntual (solo lo registrado/vinculado a esa
      consulta), para generar el borrador de nota de esa consulta.
    - ``obtener_hallazgos_de_paciente`` (DX-02): arma la lista completa de
      ``HallazgoClinico`` de un paciente a lo largo de todo su expediente
      (todas las consultas, laboratorios, imágenes y biomarcadores, estén
      o no vinculados a una consulta concreta), porque el diagnóstico
      diferencial debe poder combinar toda la información clínica
      disponible, no solo la de un encuentro.

En ambos casos cada fragmento conserva el id real de la fila de la base
de datos que lo originó, para que la trazabilidad llegue hasta el
registro exacto, no solo a "la consulta" o "el paciente" en general.
"""

from __future__ import annotations

import sqlite3
from typing import List

from ia_clinica.notes.models import ClinicalContext, SourceSpan, split_sentences

from historia_clinica_mock.repository import (
    Biomarcador,
    EstudioImagenologico,
    HallazgoClinico,
    ResultadoLaboratorio,
    biomarcadores_de_consulta,
    biomarcadores_de_paciente,
    imagenologia_de_consulta,
    imagenologia_de_paciente,
    laboratorios_de_consulta,
    laboratorios_de_paciente,
    listar_consultas,
    obtener_consulta,
    obtener_paciente,
)


class ConsultaNoEncontradaError(Exception):
    """La consulta solicitada no existe en la base de datos."""


class PacienteNoEncontradoError(Exception):
    """El paciente solicitado no existe en la base de datos."""


def _texto_laboratorio(lab: ResultadoLaboratorio) -> str:
    alerta = " (fuera de rango de referencia)" if lab.alterado else ""
    return (
        f"Resultado de laboratorio — {lab.prueba}: {lab.valor}"
        f"{' ' + lab.unidad if lab.unidad else ''}"
        f" (referencia: {lab.rango_referencia or 'no especificada'}){alerta}."
    )


def _texto_imagen(imagen: EstudioImagenologico) -> str:
    return f"{imagen.modalidad} de {imagen.region}: {imagen.hallazgos}"


def _texto_biomarcador(biomarcador: Biomarcador) -> str:
    return f"Biomarcador {biomarcador.biomarcador}: {biomarcador.resultado}."


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
        segments.append(
            SourceSpan(id=f"lab-{lab.id}", text=_texto_laboratorio(lab), origin="laboratorio", timestamp=lab.fecha)
        )

    for imagen in imagenologia_de_consulta(conn, consulta_id):
        segments.append(
            SourceSpan(id=f"imagen-{imagen.id}", text=_texto_imagen(imagen), origin="imagenologia", timestamp=imagen.fecha)
        )

    for biomarcador in biomarcadores_de_consulta(conn, consulta_id):
        segments.append(
            SourceSpan(
                id=f"biomarcador-{biomarcador.id}",
                text=_texto_biomarcador(biomarcador),
                origin="biomarcador",
                timestamp=biomarcador.fecha,
            )
        )

    patient_ref = f"paciente-{paciente.id}" if paciente else f"paciente-{consulta.paciente_id}"
    return ClinicalContext(consult_id=f"consulta-{consulta.id}", patient_ref=patient_ref, segments=segments)


def obtener_hallazgos_de_paciente(conn: sqlite3.Connection, paciente_id: int) -> List[HallazgoClinico]:
    """Reúne todos los hallazgos clínicos disponibles de un paciente.

    A diferencia de ``construir_contexto_clinico``, no se acota a una sola
    consulta: recorre todas las consultas (notas dictadas), laboratorios,
    estudios de imagenología y biomarcadores del paciente, estén o no
    vinculados a una consulta puntual. Pensado para historias que razonan
    sobre "toda la información clínica disponible del paciente" (DX-02),
    no sobre una consulta aislada (IA-02).

    Lanza ``PacienteNoEncontradoError`` si el id no existe.
    """

    paciente = obtener_paciente(conn, paciente_id)
    if paciente is None:
        raise PacienteNoEncontradoError(f"No existe ningún paciente con id={paciente_id}.")

    hallazgos: List[HallazgoClinico] = []

    for consulta in listar_consultas(conn, paciente_id):
        for i, oracion in enumerate(split_sentences(consulta.notas_libres), start=1):
            hallazgos.append(
                HallazgoClinico(
                    id=f"consulta-{consulta.id}-nota-{i}",
                    paciente_id=paciente_id,
                    origen="consulta",
                    texto=oracion,
                    fecha=consulta.fecha,
                )
            )

    for lab in laboratorios_de_paciente(conn, paciente_id):
        hallazgos.append(
            HallazgoClinico(id=f"lab-{lab.id}", paciente_id=paciente_id, origen="laboratorio", texto=_texto_laboratorio(lab), fecha=lab.fecha)
        )

    for imagen in imagenologia_de_paciente(conn, paciente_id):
        hallazgos.append(
            HallazgoClinico(id=f"imagen-{imagen.id}", paciente_id=paciente_id, origen="imagenologia", texto=_texto_imagen(imagen), fecha=imagen.fecha)
        )

    for biomarcador in biomarcadores_de_paciente(conn, paciente_id):
        hallazgos.append(
            HallazgoClinico(
                id=f"biomarcador-{biomarcador.id}",
                paciente_id=paciente_id,
                origen="biomarcador",
                texto=_texto_biomarcador(biomarcador),
                fecha=biomarcador.fecha,
            )
        )

    return hallazgos
