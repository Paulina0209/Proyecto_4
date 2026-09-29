"""Conexión y esquema del paquete historia_clinica (HC-01, HC-05).

El esquema se aplica encima del de ``expediente``: una sola
base de datos para todo el expediente clínico.

La base real del copiloto es ``data/copiloto.db`` (se llena desde
cBioPortal con ``python -m cbioportal``, ver docs/cbioportal.md). Se puede
cambiar con la variable de entorno ``COPILOTO_EXPEDIENTE_DB``.
"""

from __future__ import annotations

import os
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from expediente.db import inicializar_esquema as inicializar_esquema_expediente

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema_historia_clinica.sql"
RUTA_EXPEDIENTE_POR_DEFECTO = Path(__file__).resolve().parent.parent / "data" / "copiloto.db"


def ruta_expediente() -> Path:
    """Ruta de la base real del expediente (``COPILOTO_EXPEDIENTE_DB`` o ``data/copiloto.db``)."""
    return Path(os.environ.get("COPILOTO_EXPEDIENTE_DB") or RUTA_EXPEDIENTE_POR_DEFECTO)


def conectar_expediente(ruta: Optional[Path] = None, *, check_same_thread: bool = True) -> sqlite3.Connection:
    """Conexión a la base real del expediente, con el esquema completo."""
    ruta = Path(ruta or ruta_expediente())
    ruta.parent.mkdir(parents=True, exist_ok=True)
    return crear_conexion(str(ruta), check_same_thread=check_same_thread)


def crear_conexion(ruta: str = ":memory:", *, check_same_thread: bool = True) -> sqlite3.Connection:
    conn = sqlite3.connect(ruta, check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    inicializar_esquema(conn)
    return conn


def inicializar_esquema(conn: sqlite3.Connection) -> None:
    """Crea las tablas del expediente (si faltan) y las de HC-01. Idempotente."""
    inicializar_esquema_expediente(conn)
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
