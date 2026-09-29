"""Conexión y creación del esquema del expediente clínico."""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def crear_conexion(ruta: str = ":memory:", *, check_same_thread: bool = True) -> sqlite3.Connection:
    """Crea una conexión SQLite con el esquema ya inicializado.

    Por defecto usa una base de datos en memoria (``:memory:``), útil en
    pruebas. La base real del copiloto se abre con
    ``historia_clinica.db.conectar_expediente``.
    """

    conn = sqlite3.connect(ruta, check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    inicializar_esquema(conn)
    return conn


def inicializar_esquema(conn: sqlite3.Connection) -> None:
    schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    conn.commit()
