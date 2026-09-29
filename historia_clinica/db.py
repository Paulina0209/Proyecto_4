"""Conexión y esquema del paquete historia_clinica (HC-01, HC-05).

El esquema se aplica encima del de ``historia_clinica_mock``: una sola
base de datos para todo el expediente clínico.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from historia_clinica_mock.db import inicializar_esquema as inicializar_esquema_mock

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema_historia_clinica.sql"


def crear_conexion(ruta: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(ruta)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    inicializar_esquema(conn)
    return conn


def inicializar_esquema(conn: sqlite3.Connection) -> None:
    """Crea las tablas del mock (si faltan) y las de HC-01. Idempotente."""
    inicializar_esquema_mock(conn)
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def ahora_iso(ahora: Optional[datetime] = None) -> str:
    return (ahora or datetime.now(timezone.utc)).isoformat()


def normalizar_texto(texto: str) -> str:
    """Minúsculas, sin tildes y con espacios simples: para comparar nombres
    de pacientes, pruebas y biomarcadores sin depender de cómo los escribió
    cada sistema de origen."""
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^a-z0-9%+.]+", " ", texto.casefold())
    return re.sub(r"\s+", " ", texto).strip()
