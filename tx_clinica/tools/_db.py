"""Conexión SQLite compartida por las tools de tx_clinica.

create_agent (LangGraph por debajo) ejecuta las tools en un pool de
hilos, no en el hilo principal. sqlite3 por defecto revienta con
"SQLite objects created in a thread can only be used in that same
thread" si la conexión se usa así. check_same_thread=False le dice a
sqlite3 que no valide eso, pero la conexión sigue sin ser segura para
accesos concurrentes reales -- por eso además serializamos todo uso de
_conn con conn_lock (una tool a la vez toca la base).

Nota para producción real: aquí se usa una base en memoria sembrada con
datos sintéticos al arrancar, porque este es un prototipo académico
sobre historia_clinica_mock. Si el repo ya usa un archivo .db
persistente en otra parte, cambiar crear_conexion() por la ruta de ese
archivo para que el agente vea los mismos pacientes que el resto de la
aplicación.
"""

from __future__ import annotations

import sqlite3
import threading
from typing import Optional

from historia_clinica_mock.db import crear_conexion
from historia_clinica_mock.seed import sembrar_datos_sinteticos

_conn: Optional[sqlite3.Connection] = None
conn_lock = threading.Lock()

def obtener_conexion() -> sqlite3.Connection:
    global _conn
    with conn_lock:
        if _conn is None:
            _conn = crear_conexion(":memory:", check_same_thread=False)
            sembrar_datos_sinteticos(_conn)
        return _conn

# DESPUÉS (+ inicializa los 3 esquemas nuevos)
from tx_clinica.justificaciones import inicializar_schema as _init_auditoria
from clinical_decision.registro import inicializar_schema as _init_decision
from patients.medicacion_actual import inicializar_schema as _init_medicacion

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