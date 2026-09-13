"""Alcance MÍNIMO de AUD-02 — solo lo que la historia de interacciones
necesita como dependencia (AC2: justificar y registrar la decisión de
continuar pese a una alerta). AUD-02 como historia completa (auditoría
general de decisiones clínicas) sigue sin diseñarse.

Patrón: paquete aditivo, tabla nueva, sin tocar nada existente — igual
que pacientes_clinica y tx_clinica.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from interacciones_farmacologicas.models import JustificacionContinuacion, ResultadoChequeoInteracciones


@dataclass
class ResultadoConfirmacionTratamiento:
    confirmado: bool
    motivo_rechazo: str | None = None
    justificaciones_registradas: list[JustificacionContinuacion] | None = None


def inicializar_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS justificaciones_continuacion (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente_id INTEGER NOT NULL,
            interaccion_id TEXT NOT NULL,
            regimen_id TEXT,
            oncologo_id INTEGER NOT NULL,
            texto_justificacion TEXT NOT NULL,
            fecha TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _registrar_justificacion(
    conn: sqlite3.Connection, justificacion: JustificacionContinuacion
) -> JustificacionContinuacion:
    cursor = conn.execute(
        """
        INSERT INTO justificaciones_continuacion
            (paciente_id, interaccion_id, regimen_id, oncologo_id,
             texto_justificacion, fecha)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            justificacion.paciente_id,
            justificacion.interaccion_id,
            justificacion.regimen_id,
            justificacion.oncologo_id,
            justificacion.texto_justificacion,
            justificacion.fecha,
        ),
    )
    conn.commit()
    justificacion.id = cursor.lastrowid
    return justificacion


def confirmar_tratamiento(
    conn: sqlite3.Connection,
    resultado_chequeo: ResultadoChequeoInteracciones,
    oncologo_id: int,
    textos_justificacion: dict[str, str] | None = None,
) -> ResultadoConfirmacionTratamiento:
    """
    textos_justificacion: {interaccion_id: texto} — debe traer una entrada
    no vacía por cada interacción con audit_effect="requires_justification".
    """
    textos_justificacion = textos_justificacion or {}

    bloqueantes = resultado_chequeo.bloquea_confirmacion()
    if bloqueantes:
        ids = ", ".join(i.interaccion_id for i in bloqueantes)
        return ResultadoConfirmacionTratamiento(
            confirmado=False,
            motivo_rechazo=f"Contraindicación absoluta, no se puede confirmar: {ids}",
        )

    pendientes_de_justificar = resultado_chequeo.requiere_justificacion()
    faltantes = [
        i.interaccion_id
        for i in pendientes_de_justificar
        if not textos_justificacion.get(i.interaccion_id, "").strip()
    ]
    if faltantes:
        return ResultadoConfirmacionTratamiento(
            confirmado=False,
            motivo_rechazo=(
                "Falta justificación explícita para continuar pese a: "
                + ", ".join(faltantes)
            ),
        )

    ahora = datetime.now(timezone.utc).isoformat()
    justificaciones_guardadas = []
    for interaccion in pendientes_de_justificar:
        justificacion = JustificacionContinuacion(
            paciente_id=resultado_chequeo.paciente_id,
            interaccion_id=interaccion.interaccion_id,
            regimen_id=resultado_chequeo.regimen_evaluado,
            oncologo_id=oncologo_id,
            texto_justificacion=textos_justificacion[interaccion.interaccion_id].strip(),
            fecha=ahora,
        )
        justificaciones_guardadas.append(_registrar_justificacion(conn, justificacion))

    return ResultadoConfirmacionTratamiento(
        confirmado=True, justificaciones_registradas=justificaciones_guardadas
    )