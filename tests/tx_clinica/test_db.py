"""Prueba de Fase 1 para 1.6 (_db.py sin la definición duplicada de
obtener_conexion, y comportamiento de singleton perezoso)."""
import ast
from pathlib import Path

import tx_clinica.tools._db  # noqa: F401 -- confirma que el módulo importa sin errores


def _ruta_db_py() -> Path:
    return Path(tx_clinica.tools._db.__file__)


def test_1_6_no_hay_definicion_duplicada_de_obtener_conexion():
    codigo = _ruta_db_py().read_text(encoding="utf-8")
    arbol = ast.parse(codigo)
    nombres_funciones = [
        n.name for n in ast.walk(arbol)
        if isinstance(n, ast.FunctionDef) and n.name == "obtener_conexion"
    ]
    assert len(nombres_funciones) == 1, f"esperaba 1 definición, hay {len(nombres_funciones)}"


def test_1_6_obtener_conexion_es_singleton_perezoso_e_inicializa_una_sola_vez(monkeypatch):
    from tx_clinica.tools import _db

    llamadas = {"crear_conexion": 0, "medicacion": 0, "auditoria": 0, "decision": 0}

    class FakeConn:
        pass

    def fake_conectar_expediente(ruta=None, check_same_thread=False):
        llamadas["crear_conexion"] += 1
        return FakeConn()

    monkeypatch.setattr(_db, "conectar_expediente", fake_conectar_expediente)
    monkeypatch.setattr(_db, "_init_medicacion", lambda c: llamadas.__setitem__("medicacion", llamadas["medicacion"] + 1))
    monkeypatch.setattr(_db, "_init_auditoria", lambda c: llamadas.__setitem__("auditoria", llamadas["auditoria"] + 1))
    monkeypatch.setattr(_db, "_init_decision", lambda c: llamadas.__setitem__("decision", llamadas["decision"] + 1))
    _db._conn = None  # reset del singleton global entre pruebas

    c1 = _db.obtener_conexion()
    c2 = _db.obtener_conexion()

    assert c1 is c2, "debe reutilizar la misma conexión (singleton)"
    assert llamadas == {"crear_conexion": 1, "medicacion": 1, "auditoria": 1, "decision": 1}, (
        "la inicialización completa debe ocurrir UNA sola vez, en la primera llamada"
    )

    _db._conn = None  # limpieza
