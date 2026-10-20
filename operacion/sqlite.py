"""SQLite para peticiones concurrentes (NFR-01, NFR-02).

Dos problemas aparecían con varios usuarios a la vez:

    - ``ProgrammingError``: la API abre la conexión de cada petición en un hilo
      y FastAPI ejecuta el endpoint en otro. La conexión es de una sola
      petición (nunca se comparte entre peticiones), así que basta con
      ``check_same_thread=False``.
    - Lectores bloqueados por un escritor: en el modo de diario por defecto,
      una escritura impide leer. En modo WAL los lectores siguen leyendo la
      última versión confirmada mientras alguien escribe.

``busy_timeout`` hace que una escritura que coincide con otra espere en vez de
fallar con "database is locked".
"""

from __future__ import annotations

import sqlite3

#: Lo que espera una escritura a que termine otra antes de fallar.
ESPERA_BLOQUEO_MS = 5000


def preparar_concurrencia(conn: sqlite3.Connection, ruta: object) -> sqlite3.Connection:
    """Activa WAL (en archivos; una base en memoria no lo admite) y la espera por bloqueo."""
    conn.execute(f"PRAGMA busy_timeout = {ESPERA_BLOQUEO_MS}")
    if str(ruta) != ":memory:" and not str(ruta).startswith("file::memory:"):
        conn.execute("PRAGMA journal_mode = WAL")
        # Con WAL, NORMAL sigue siendo seguro ante caídas del proceso y evita un fsync por transacción.
        conn.execute("PRAGMA synchronous = NORMAL")
    return conn
