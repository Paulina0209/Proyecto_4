"""Punto de entrada de IA-03: conecta un borrador de IA-02 con el flujo de
revisión y aprobación, y expone las operaciones con nombres/fechas listos
para usar (sin que quien llame tenga que manejar ``datetime`` a mano).

Este módulo es una capa fina sobre :mod:`ia_clinica.review.store`: no
agrega reglas de negocio nuevas, solo traduce entre ``ClinicalNoteDraft``
(el borrador inmutable que produce IA-02) y el almacenamiento de IA-03.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional

from ia_clinica.notes.models import ClinicalNoteDraft
from ia_clinica.review import store
from ia_clinica.review.models import NotaEnRevision


def _ahora_iso(ahora: Optional[datetime] = None) -> str:
    return (ahora or datetime.now(timezone.utc)).isoformat()


def iniciar_revision(
    conn: sqlite3.Connection,
    borrador: ClinicalNoteDraft,
    ahora: Optional[datetime] = None,
) -> NotaEnRevision:
    """Registra el inicio de la revisión de un borrador generado por IA-02.

    El ``ClinicalNoteDraft`` de IA-02 nunca se modifica: esta función solo
    copia el contenido de cada sección como punto de partida mutable para
    la revisión. Se usa ``borrador.consult_id`` como identificador de la
    nota en revisión, porque IA-02 ya garantiza que ese id es único por
    consulta — así hay una sola revisión posible por consulta, y volver a
    generar un borrador para la misma consulta no puede pisar
    silenciosamente una revisión (o aprobación) ya existente
    (``RevisionYaExisteError``).
    """

    contenido_inicial = {seccion.key: seccion.content for seccion in borrador.sections}
    return store.crear_revision(
        conn,
        nota_id=borrador.consult_id,
        paciente_ref=borrador.patient_ref,
        contenido_inicial=contenido_inicial,
        ahora=_ahora_iso(ahora),
    )


def editar_seccion(
    conn: sqlite3.Connection,
    nota_id: str,
    seccion_key: str,
    nuevo_contenido: str,
    autor: str,
    ahora: Optional[datetime] = None,
) -> NotaEnRevision:
    """Modifica manualmente el contenido de una sección (AC1) y lo persiste (AC2)."""

    return store.guardar_edicion(conn, nota_id, seccion_key, nuevo_contenido, autor, _ahora_iso(ahora))


def aprobar_nota(
    conn: sqlite3.Connection,
    nota_id: str,
    aprobado_por: str,
    ahora: Optional[datetime] = None,
) -> NotaEnRevision:
    """Acción explícita de aprobación (AC4): única forma de llegar a APPROVED."""

    return store.aprobar_nota(conn, nota_id, aprobado_por, _ahora_iso(ahora))


def obtener_revision(conn: sqlite3.Connection, nota_id: str) -> NotaEnRevision:
    """Recupera el estado actual de una revisión (AC3/AC5: refleja el estado
    persistido, no el de un objeto en memoria de una sesión anterior)."""

    return store.obtener_revision(conn, nota_id)
