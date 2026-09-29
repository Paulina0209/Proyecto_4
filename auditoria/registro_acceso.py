"""AUD-01 — Registro de auditoría de accesos y acciones.

Como administrador, quiero un registro de auditoría de accesos y acciones
sobre cada expediente, para poder reconstruir quién hizo qué y cuándo.

Diseño: igual que el resto de tablas de auditoría del proyecto
(``confirmaciones_estadificacion`` de EST-02, ``juicios_clinicos_dx`` de
DX-03, ``decisiones_tratamiento`` de TX-04): ``eventos_acceso`` es de
solo-inserción. Este módulo, a propósito, no expone ninguna función de
UPDATE ni DELETE -- la única forma de dejar constancia de algo nuevo es
registrar un evento nuevo; el historial nunca se edita ni se borra
(criterio de aceptación de AUD-01: "de forma no editable").
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from auditoria.models import EventoAcceso, TipoAccion

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema_auditoria.sql"


def crear_conexion(ruta: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(ruta)
    conn.row_factory = sqlite3.Row
    inicializar_schema(conn)
    return conn


def inicializar_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def registrar_acceso(
    conn: sqlite3.Connection,
    usuario_id: int,
    accion: TipoAccion,
    paciente_id: Optional[int] = None,
    detalle: Optional[str] = None,
    ahora: Optional[datetime] = None,
) -> EventoAcceso:
    """Registra un evento de acceso/acción sobre un expediente.

    Criterio de aceptación de AUD-01: cualquier acceso queda registrado
    con usuario, fecha/hora y acción realizada, en formato no editable.
    """
    fecha = (ahora or datetime.now(timezone.utc)).isoformat()
    cursor = conn.execute(
        """
        INSERT INTO eventos_acceso (usuario_id, paciente_id, accion, fecha, detalle)
        VALUES (?, ?, ?, ?, ?)
        """,
        (usuario_id, paciente_id, accion.value, fecha, detalle),
    )
    conn.commit()
    return obtener_evento_por_id(conn, cursor.lastrowid)


def obtener_evento_por_id(conn: sqlite3.Connection, evento_id: int) -> EventoAcceso:
    fila = conn.execute("SELECT * FROM eventos_acceso WHERE id = ?", (evento_id,)).fetchone()
    if fila is None:
        raise KeyError(f"No existe ningún evento de acceso con id={evento_id}.")
    return _fila_a_evento(fila)


def obtener_eventos_de_paciente(
    conn: sqlite3.Connection, paciente_id: int
) -> tuple[EventoAcceso, ...]:
    """Todo el historial de accesos a un expediente, del más reciente al más antiguo."""
    filas = conn.execute(
        "SELECT * FROM eventos_acceso WHERE paciente_id = ? ORDER BY id DESC",
        (paciente_id,),
    ).fetchall()
    return tuple(_fila_a_evento(f) for f in filas)


def obtener_eventos_de_usuario(
    conn: sqlite3.Connection, usuario_id: int
) -> tuple[EventoAcceso, ...]:
    """Todo lo que un usuario concreto hizo, del más reciente al más antiguo
    (reconstruir "quién hizo qué" también desde el usuario, no solo desde
    el paciente)."""
    filas = conn.execute(
        "SELECT * FROM eventos_acceso WHERE usuario_id = ? ORDER BY id DESC",
        (usuario_id,),
    ).fetchall()
    return tuple(_fila_a_evento(f) for f in filas)


def _fila_a_evento(fila: sqlite3.Row) -> EventoAcceso:
    return EventoAcceso(
        id=fila["id"],
        usuario_id=fila["usuario_id"],
        paciente_id=fila["paciente_id"],
        accion=TipoAccion(fila["accion"]),
        fecha=fila["fecha"],
        detalle=fila["detalle"],
    )
