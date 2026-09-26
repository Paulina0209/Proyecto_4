
from __future__ import annotations

import sqlite3
import threading
from typing import Optional

from historia_clinica_mock.db import crear_conexion
from historia_clinica_mock.seed import sembrar_datos_sinteticos
from tx_clinica.justificaciones import inicializar_schema as _init_auditoria
from clinical_decision.registro import inicializar_schema as _init_decision
from patients.medicacion_actual import inicializar_schema as _init_medicacion

_conn: Optional[sqlite3.Connection] = None
conn_lock = threading.Lock()


def obtener_conexion() -> sqlite3.Connection:
    global _conn
    with conn_lock:
        if _conn is None:
            _conn = crear_conexion(":memory:", check_same_thread=False)
            sembrar_datos_sinteticos(_conn)
            _init_medicacion(_conn)
            _init_auditoria(_conn)
            _init_decision(_conn)
        return _conn