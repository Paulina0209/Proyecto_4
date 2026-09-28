"""Medicación concomitante del paciente y estado de su conciliación.

No pertenece a HC-01/PAC-02/PAC-03: lo usa tx_clinica (chequeo de
interacciones, TX-03) sobre SU propia conexión (historia_clinica_mock),
por eso crea solo sus dos tablas y no depende de db/schema.sql.
Los datos de prueba los inserta paciente_de_prueba.sql.
"""
from __future__ import annotations

import sqlite3

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
