"""Persistencia SQLite para IA-03 — revisión y aprobación de notas clínicas.

Este es el único módulo que escribe en la tabla ``revision_notas``. Cada
función pública corresponde exactamente a una de las acciones explícitas
que permite la historia IA-03 (crear la revisión, guardar una edición,
aprobar). No existe, a propósito, ninguna función genérica tipo
``actualizar_estado(nota_id, nuevo_estado)``: eso permitiría poner
``estado = "APPROVED"`` por cualquier camino, violando la regla de negocio
de que la aprobación requiere siempre una acción explícita con un
identificador de médico autorizado.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ia_clinica.review.models import (
    AprobacionRegistrada,
    EdicionRegistrada,
    EstadoNota,
    NotaEnRevision,
    NotaYaAprobadaError,
    RevisionNoEncontradaError,
    RevisionYaExisteError,
)

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def crear_conexion(ruta: str = ":memory:") -> sqlite3.Connection:
    """Crea una conexión SQLite con el esquema de IA-03 ya inicializado.

    Por defecto usa una base en memoria (``:memory:``), útil para pruebas
    y demos rápidas. Para probar de verdad el criterio de aceptación
    "si cierro sesión, la nota sigue como borrador", hay que pasar una
    ruta de archivo real y abrir una conexión *nueva* apuntando al mismo
    archivo — una base en memoria desaparece con la conexión, así que no
    sirve para simular ese escenario (ver ``tests/ia_clinica/review``).
    """

    conn = sqlite3.connect(ruta)
    conn.row_factory = sqlite3.Row
    inicializar_esquema(conn)
    return conn


def inicializar_esquema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def crear_revision(
    conn: sqlite3.Connection,
    nota_id: str,
    paciente_ref: str,
    contenido_inicial: dict,
    ahora: str,
) -> NotaEnRevision:
    """Registra el inicio de la revisión de un borrador de IA-02.

    Lanza ``RevisionYaExisteError`` si ya existía una revisión con este
    ``nota_id``: regenerar un borrador no debe poder resetear
    silenciosamente el estado (por ejemplo, una nota ya aprobada) de una
    revisión existente.
    """

    existente = conn.execute(
        "SELECT 1 FROM revision_notas WHERE nota_id = ?", (nota_id,)
    ).fetchone()
    if existente is not None:
        raise RevisionYaExisteError(
            f"Ya existe un proceso de revisión para la nota '{nota_id}'."
        )

    conn.execute(
        """
        INSERT INTO revision_notas (
            nota_id, paciente_ref, contenido_ia_original, contenido_actual,
            estado, creado_en, historial_ediciones, aprobado_por, aprobado_en
        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL)
        """,
        (
            nota_id,
            paciente_ref,
            json.dumps(contenido_inicial, ensure_ascii=False),
            json.dumps(contenido_inicial, ensure_ascii=False),
            EstadoNota.DRAFT.value,
            ahora,
            json.dumps([], ensure_ascii=False),
        ),
    )
    conn.commit()
    return obtener_revision(conn, nota_id)


def obtener_revision(conn: sqlite3.Connection, nota_id: str) -> NotaEnRevision:
    fila = conn.execute(
        "SELECT * FROM revision_notas WHERE nota_id = ?", (nota_id,)
    ).fetchone()
    if fila is None:
        raise RevisionNoEncontradaError(f"No existe una revisión con id '{nota_id}'.")
    return _fila_a_nota(fila)


def guardar_edicion(
    conn: sqlite3.Connection,
    nota_id: str,
    seccion_key: str,
    nuevo_contenido: str,
    autor: str,
    ahora: str,
) -> NotaEnRevision:
    """Guarda una modificación manual sobre una sección de la nota (AC1/AC2).

    Lanza ``NotaYaAprobadaError`` si la nota ya fue aprobada: una vez
    oficial, este flujo de borrador deja de aceptar ediciones (ver
    ``NotaYaAprobadaError``).
    """

    actual = obtener_revision(conn, nota_id)
    if actual.es_nota_oficial():
        raise NotaYaAprobadaError(
            f"La nota '{nota_id}' ya fue aprobada; no se puede editar una "
            "nota clínica oficial desde el flujo de borrador de IA-03."
        )

    contenido_anterior = actual.contenido_actual.get(seccion_key, "")
    edicion = EdicionRegistrada(
        autor=autor,
        seccion_key=seccion_key,
        contenido_anterior=contenido_anterior,
        contenido_nuevo=nuevo_contenido,
        editado_en=ahora,
    )

    nuevo_contenido_actual = dict(actual.contenido_actual)
    nuevo_contenido_actual[seccion_key] = nuevo_contenido
    nuevo_historial = [*actual.historial_ediciones, edicion]

    conn.execute(
        """
        UPDATE revision_notas
        SET contenido_actual = ?, historial_ediciones = ?
        WHERE nota_id = ?
        """,
        (
            json.dumps(nuevo_contenido_actual, ensure_ascii=False),
            json.dumps([_edicion_a_dict(e) for e in nuevo_historial], ensure_ascii=False),
            nota_id,
        ),
    )
    conn.commit()
    return obtener_revision(conn, nota_id)


def aprobar_nota(
    conn: sqlite3.Connection,
    nota_id: str,
    aprobado_por: str,
    ahora: str,
) -> NotaEnRevision:
    """Transición explícita DRAFT -> APPROVED (AC4). No hay otro camino.

    Regla de negocio de IA-03: ninguna nota adquiere estado oficial sin
    esta acción explícita, con un identificador no vacío del médico
    autorizado. Lanza ``NotaYaAprobadaError`` si ya estaba aprobada (no
    se permite "reaprobar" ni pisar silenciosamente quién/cuándo aprobó
    originalmente).
    """

    if not aprobado_por or not aprobado_por.strip():
        raise ValueError(
            "aprobado_por no puede estar vacío: la aprobación exige un "
            "identificador explícito del médico autorizado (regla de "
            "negocio de IA-03)."
        )

    actual = obtener_revision(conn, nota_id)
    if actual.es_nota_oficial():
        assert actual.aprobacion is not None  # invariante: si es oficial, hay aprobación registrada.
        raise NotaYaAprobadaError(
            f"La nota '{nota_id}' ya fue aprobada por "
            f"'{actual.aprobacion.aprobado_por}' el {actual.aprobacion.aprobado_en}; "
            "no se puede volver a aprobar."
        )

    conn.execute(
        """
        UPDATE revision_notas
        SET estado = ?, aprobado_por = ?, aprobado_en = ?
        WHERE nota_id = ?
        """,
        (EstadoNota.APPROVED.value, aprobado_por, ahora, nota_id),
    )
    conn.commit()
    return obtener_revision(conn, nota_id)


# -- Helpers internos --------------------------------------------------


def _edicion_a_dict(edicion: EdicionRegistrada) -> dict:
    return {
        "autor": edicion.autor,
        "seccion_key": edicion.seccion_key,
        "contenido_anterior": edicion.contenido_anterior,
        "contenido_nuevo": edicion.contenido_nuevo,
        "editado_en": edicion.editado_en,
    }


def _fila_a_nota(fila: sqlite3.Row) -> NotaEnRevision:
    historial_bruto = json.loads(fila["historial_ediciones"])
    historial = tuple(EdicionRegistrada(**item) for item in historial_bruto)

    aprobacion = None
    if fila["aprobado_por"] is not None:
        aprobacion = AprobacionRegistrada(
            aprobado_por=fila["aprobado_por"], aprobado_en=fila["aprobado_en"]
        )

    return NotaEnRevision(
        nota_id=fila["nota_id"],
        paciente_ref=fila["paciente_ref"],
        contenido_ia_original=json.loads(fila["contenido_ia_original"]),
        contenido_actual=json.loads(fila["contenido_actual"]),
        estado=EstadoNota(fila["estado"]),
        creado_en=fila["creado_en"],
        historial_ediciones=historial,
        aprobacion=aprobacion,
    )
