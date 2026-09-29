"""Única base de datos del módulo de pacientes (SQLite).

- schema.sql: todas las tablas (HC-01, PAC-02 y PAC-03).
- pacientes.db: el archivo de datos; se crea solo y no se versiona. Se
  llena con los pacientes que se registran y con los de cBioPortal
  (``python -m cbioportal --indice ...``, ver docs/cbioportal.md).

No trae datos de ejemplo: el resto del módulo solo depende de las tablas
de schema.sql.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

_CARPETA = Path(__file__).resolve().parent

RUTA_DB = _CARPETA / "pacientes.db"
_SCHEMA = _CARPETA / "schema.sql"


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
