"""Medicación concomitante del paciente y estado de su conciliación.

No pertenece a HC-01/PAC-02/PAC-03: lo usa tx_clinica (chequeo de
interacciones, TX-03) sobre SU propia conexión (el expediente real),
por eso crea solo sus dos tablas y no depende de db/schema.sql.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Optional

ESTADO_NO_REALIZADA = "no_realizada"
ESTADO_SIN_MEDICACION_CONCOMITANTE = "sin_medicacion_concomitante"
ESTADO_CON_MEDICACION_REGISTRADA = "con_medicacion_registrada"


def inicializar_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS medicacion_actual (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente_id INTEGER NOT NULL,
            medicamento TEXT NOT NULL,
            dosis TEXT,
            frecuencia TEXT,
            indicacion TEXT,
            fecha_inicio TEXT,
            fecha_fin TEXT,  -- NULL = activo
            registrado_por INTEGER NOT NULL,
            fecha_registro TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_medicacion_actual_paciente ON medicacion_actual(paciente_id);

        CREATE TABLE IF NOT EXISTS conciliacion_medicamentos (
            paciente_id INTEGER PRIMARY KEY,
            estado TEXT NOT NULL DEFAULT 'no_realizada',
            fecha TEXT,
            registrado_por INTEGER
        );
        """
    )
    conn.commit()


def listar_medicacion_activa(conn: sqlite3.Connection, paciente_id: int) -> list[str]:
    """Solo los nombres de medicamento activos: la entrada directa de
    interacciones_farmacologicas.checker."""
    filas = conn.execute(
        "SELECT medicamento FROM medicacion_actual WHERE paciente_id = ? AND fecha_fin IS NULL",
        (paciente_id,),
    ).fetchall()
    return [fila[0] for fila in filas]


def obtener_estado_conciliacion(conn: sqlite3.Connection, paciente_id: int) -> str:
    """Sin fila significa, por definición, que la conciliación no se ha hecho."""
    fila = conn.execute(
        "SELECT estado FROM conciliacion_medicamentos WHERE paciente_id = ?", (paciente_id,)
    ).fetchone()
    return fila[0] if fila else ESTADO_NO_REALIZADA


def registrar_conciliacion(
    conn: sqlite3.Connection,
    paciente_id: int,
    medicamentos: list[str],
    registrado_por: int,
    fecha: Optional[str] = None,
) -> str:
    """El oncólogo concilia la medicación concomitante del paciente.

    Reemplaza la lista activa por ``medicamentos`` (los anteriores quedan
    con ``fecha_fin``, no se borran) y deja el estado de conciliación:
    lista vacía = "sin medicación concomitante" (un dato confirmado, no un
    "no se sabe"). Devuelve el estado registrado.
    """
    dia = fecha or date.today().isoformat()
    nombres = [m.strip() for m in medicamentos if m and m.strip()]
    conn.execute(
        "UPDATE medicacion_actual SET fecha_fin = ? WHERE paciente_id = ? AND fecha_fin IS NULL",
        (dia, paciente_id),
    )
    for nombre in nombres:
        conn.execute(
            "INSERT INTO medicacion_actual (paciente_id, medicamento, fecha_inicio, registrado_por, fecha_registro) "
            "VALUES (?, ?, ?, ?, ?)",
            (paciente_id, nombre, dia, registrado_por, dia),
        )
    estado = ESTADO_CON_MEDICACION_REGISTRADA if nombres else ESTADO_SIN_MEDICACION_CONCOMITANTE
    conn.execute(
        "INSERT INTO conciliacion_medicamentos (paciente_id, estado, fecha, registrado_por) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(paciente_id) DO UPDATE SET estado = excluded.estado, fecha = excluded.fecha, "
        "registrado_por = excluded.registrado_por",
        (paciente_id, estado, dia, registrado_por),
    )
    conn.commit()
    return estado
