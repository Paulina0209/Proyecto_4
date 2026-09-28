"""Única base de datos del módulo de pacientes (SQLite).

- schema.sql: todas las tablas (HC-01, PAC-02 y PAC-03).
- datos_prueba.sql: pacientes de ejemplo para probar sin registrar nada.
- pacientes.db: el archivo de datos; se crea solo y no se versiona.

Se reemplaza por la base de datos real cuando se integre: el resto del
módulo solo depende de las tablas de schema.sql.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

_CARPETA = Path(__file__).resolve().parent

RUTA_DB = _CARPETA / "pacientes.db"
_SCHEMA = _CARPETA / "schema.sql"
_DATOS_PRUEBA = _CARPETA / "datos_prueba.sql"


def conectar(ruta: str | Path = RUTA_DB) -> sqlite3.Connection:
    """Filas accesibles por nombre de columna y claves foráneas activas.
    `ruta=":memory:"` da una base en memoria, útil en pruebas."""
    conn = sqlite3.connect(ruta)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def inicializar(conn: sqlite3.Connection) -> None:
    """Crea las tablas que falten (idempotente)."""
    conn.executescript(_SCHEMA.read_text(encoding="utf-8"))
    conn.commit()


def sembrar_datos_prueba(conn: sqlite3.Connection) -> bool:
    """Carga datos_prueba.sql solo si no hay ningún paciente. Devuelve si
    los cargó."""
    if conn.execute("SELECT COUNT(*) FROM pacientes").fetchone()[0]:
        return False
    conn.executescript(_DATOS_PRUEBA.read_text(encoding="utf-8"))
    conn.commit()
    return True
