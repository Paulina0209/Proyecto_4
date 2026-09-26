"""Conexión y creación del esquema de la base MOCK de resumen 360 (PAC-03).

Mismo patrón que historia_clinica_mock/db.py: por defecto una base en
memoria (para pruebas/demos), o una ruta de archivo si se quiere
conservar entre ejecuciones -- api.py usa un archivo (resumen_360_mock.db)
para que sobreviva entre peticiones, igual que ya hace con pacientes_api.db.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def crear_conexion(ruta: str = ":memory:", *, check_same_thread: bool = True) -> sqlite3.Connection:
    conn = sqlite3.connect(ruta, check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    inicializar_esquema(conn)
    return conn


def inicializar_esquema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def esta_vacia(conn: sqlite3.Connection) -> bool:
    """Para decidir si sembrar datos ficticios: solo si la base recién
    creada no tiene nada -- evita el bug ya conocido en otras semillas
    de este proyecto (historia_clinica_mock.seed no es idempotente,
    ver Apéndice C del plan) reventando con UNIQUE/IntegrityError al
    reiniciar el servidor sobre un archivo que ya tenía datos."""
    return conn.execute("SELECT COUNT(*) FROM pacientes_360").fetchone()[0] == 0
