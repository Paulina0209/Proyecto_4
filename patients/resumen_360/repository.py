"""Consultas de lectura sobre la base MOCK de resumen 360 (PAC-03).

Solo SQL -- la lógica de negocio (qué cuenta como "información faltante",
cómo se ordenan las alertas por severidad) vive en service.py, no aquí.
"""
from __future__ import annotations

import sqlite3
from typing import Optional


def obtener_paciente_360(
    conn: sqlite3.Connection, paciente_id: int, oncologo_id: int
) -> Optional[sqlite3.Row]:
    """None tanto si el id no existe como si pertenece a otro oncólogo
    -- mismo criterio de no distinguir los dos casos que ya se usa en
    patients/api.py::leer_paciente (D2 del plan), para no confirmar con
    un error distinto que el registro sí existe."""
    return conn.execute(
        "SELECT * FROM pacientes_360 WHERE id = ? AND oncologo_id = ?",
        (paciente_id, oncologo_id),
    ).fetchone()


def tratamiento_mas_reciente(conn: sqlite3.Connection, paciente_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM tratamientos_360 WHERE paciente_id = ? "
        "ORDER BY fecha_inicio DESC, id DESC LIMIT 1",
        (paciente_id,),
    ).fetchone()


def alertas_activas(conn: sqlite3.Connection, paciente_id: int) -> list[sqlite3.Row]:
    """Sin resolver, más recientes primero. El orden por SEVERIDAD (alta
    antes que media antes que baja) lo aplica service.py -- se deja
    aquí solo el orden temporal, que es lo que la consulta SQL puede
    expresar sin codificar a mano el orden de las severidades en SQL."""
    return conn.execute(
        "SELECT * FROM alertas_360 WHERE paciente_id = ? AND resuelta = 0 "
        "ORDER BY fecha DESC, id DESC",
        (paciente_id,),
    ).fetchall()


def labs_recientes(conn: sqlite3.Connection, paciente_id: int, limite: int = 5) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM labs_360 WHERE paciente_id = ? ORDER BY fecha DESC, id DESC LIMIT ?",
        (paciente_id, limite),
    ).fetchall()


def imagenes_recientes(conn: sqlite3.Connection, paciente_id: int, limite: int = 5) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM imagenes_360 WHERE paciente_id = ? ORDER BY fecha DESC, id DESC LIMIT ?",
        (paciente_id, limite),
    ).fetchall()


def notas_recientes(conn: sqlite3.Connection, paciente_id: int, limite: int = 5) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM notas_360 WHERE paciente_id = ? ORDER BY fecha DESC, id DESC LIMIT ?",
        (paciente_id, limite),
    ).fetchall()
