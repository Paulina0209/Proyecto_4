"""Única base de datos del módulo de pacientes (SQLite).

- schema.sql: todas las tablas (HC-01, PAC-02 y PAC-03).
- pacientes.db: el archivo de datos; se crea solo y no se versiona. Se
  llena con los pacientes que se registran y con los de cBioPortal
  (``python -m cbioportal --indice ...``, ver docs/cbioportal.md).

No trae datos de ejemplo: el resto del módulo solo depende de las tablas
de schema.sql.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from operacion.sqlite import preparar_concurrencia

_CARPETA = Path(__file__).resolve().parent

#: ``COPILOTO_PACIENTES_DB`` la cambia (igual que ``COPILOTO_EXPEDIENTE_DB`` para el
#: expediente): así una réplica, una prueba de carga o una demo trabajan sobre otra base.
RUTA_DB = Path(os.environ.get("COPILOTO_PACIENTES_DB") or _CARPETA / "pacientes.db")
_SCHEMA = _CARPETA / "schema.sql"


def conectar(ruta: str | Path = RUTA_DB, *, check_same_thread: bool = True) -> sqlite3.Connection:
    """Filas accesibles por nombre de columna y claves foráneas activas.
    `ruta=":memory:"` da una base en memoria, útil en pruebas.

    NFR-01/NFR-02: en archivo usa WAL, para que leer no espere a una escritura
    (``operacion.sqlite``). ``check_same_thread=False`` es para la API, que abre
    la conexión de una petición en un hilo y la usa en otro."""
    conn = sqlite3.connect(ruta, check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return preparar_concurrencia(conn, ruta)


def inicializar(conn: sqlite3.Connection) -> None:
    """Crea las tablas que falten (idempotente)."""
    conn.executescript(_SCHEMA.read_text(encoding="utf-8"))
    conn.commit()
