"""NFR-01 — Rendimiento y tiempos de respuesta.

AC1: bajo carga normal (10 médicos a la vez) el 95 % de las consultas a la API
responde en menos de 2 s y ninguna falla.
AC2: el borrador de nota (IA-02) llega en menos de 10 s aunque el modelo tarde o falle.
AC3: cada petición se mide (Server-Timing y /salud/metricas).
"""
from __future__ import annotations

import socket
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from operacion.latencia import (
    OBJETIVO_CONSULTA_S,
    MedicionLatenciaMiddleware,
    RegistroLatencias,
    percentil,
    plantilla_de_ruta,
)
from operacion.presupuesto import LLMConPresupuesto


# --- AC3: medición ----------------------------------------------------------


def test_percentil_por_rango_mas_cercano():
    valores = list(range(1, 101))
    assert percentil(valores, 50) == 50 and percentil(valores, 95) == 95 and percentil(valores, 100) == 100
    assert percentil([], 95) == 0.0 and percentil([7], 95) == 7


def _app_medida(registro):
    app = FastAPI()
    app.add_middleware(MedicionLatenciaMiddleware, registro=registro)

    @app.get("/pacientes/{paciente_id}/resumen")
    def resumen(paciente_id: int):
        return {"id": paciente_id}

    @app.get("/falla")
    def falla():
        raise RuntimeError("x")

    return app


def test_cada_peticion_se_mide_por_plantilla_sin_ids():
    registro = RegistroLatencias()
    with TestClient(_app_medida(registro), raise_server_exceptions=False) as c:
        for pid in (1, 2, 3):
            r = c.get(f"/pacientes/{pid}/resumen")
            assert r.headers["server-timing"].startswith("app;dur=")
        c.get("/no-existe")
        c.get("/falla")
    rutas = {r.ruta: r for r in registro.resumen()}
    assert rutas["GET /pacientes/{paciente_id}/resumen"].peticiones == 3  # no una entrada por paciente
    assert "GET (sin ruta)" in rutas
    assert rutas["GET /falla"].errores == 1
    assert all("/1/" not in ruta for ruta in rutas)


def test_objetivo_por_ruta():
    registro = RegistroLatencias(objetivos={"POST /notas": 10.0})
    registro.registrar("GET /pacientes/{id}", 0.05)
    registro.registrar("POST /notas", 9.0)
    resumen = {r.ruta: r for r in registro.resumen()}
    assert resumen["GET /pacientes/{id}"].objetivo_ms == OBJETIVO_CONSULTA_S * 1000 and resumen["GET /pacientes/{id}"].cumple
    assert resumen["POST /notas"].objetivo_ms == 10000 and resumen["POST /notas"].cumple


def test_plantilla_de_ruta_sin_resolver():
    assert plantilla_de_ruta({"path": "/x/9"}) == "(sin ruta)"
    assert plantilla_de_ruta({"path": "/p/9/l", "path_params": {"pid": 9}, "endpoint": object()}) == "/p/{pid}/l"


# --- AC2: nota en menos de 10 s ---------------------------------------------


class _Modelo:
    def __init__(self, demora=0.0, error=None, texto="modelo"):
        self.demora, self.error, self.texto = demora, error, texto

    def complete(self, system_prompt, user_prompt):
        time.sleep(self.demora)
        if self.error:
            raise self.error
        return self.texto


def test_modelo_a_tiempo():
    cliente = LLMConPresupuesto(_Modelo(0.01), _Modelo(texto="reglas"), presupuesto_s=1)
    assert cliente.complete("s", "u") == "modelo"
    assert cliente.ultimo_uso.proveedor == "modelo" and not cliente.ultimo_uso.uso_respaldo


def test_modelo_lento_usa_el_respaldo_dentro_del_presupuesto():
    cliente = LLMConPresupuesto(_Modelo(3.0), _Modelo(texto="reglas"), presupuesto_s=0.3)
    inicio = time.perf_counter()
    assert cliente.complete("s", "u") == "reglas"
    assert time.perf_counter() - inicio < 1.0
    assert cliente.ultimo_uso.uso_respaldo and "no respondió" in cliente.ultimo_uso.motivo


def test_modelo_caido_usa_el_respaldo():
    cliente = LLMConPresupuesto(_Modelo(error=ConnectionError("sin red")), _Modelo(texto="reglas"), presupuesto_s=1)
    assert cliente.complete("s", "u") == "reglas"
    assert "ConnectionError" in cliente.ultimo_uso.motivo


def test_el_presupuesto_debe_caber_en_el_objetivo():
    with pytest.raises(ValueError):
        LLMConPresupuesto(_Modelo(), _Modelo(), presupuesto_s=10)


def test_nota_real_con_modelo_lento_llega_en_menos_de_10_s():
    """IA-02 completo: el generador valida el borrador de respaldo igual que el de GPT."""
    from expediente.adapters import construir_contexto_clinico
    from historia_clinica.db import crear_conexion
    from ia_clinica.notes.generator import ClinicalNoteGenerator
    from ia_clinica.notes.llm_client import RuleBasedLLMClient
    from tests.datos_sinteticos import sembrar_datos_sinteticos

    conn = crear_conexion()
    ids = sembrar_datos_sinteticos(conn)
    cliente = LLMConPresupuesto(_Modelo(30.0), RuleBasedLLMClient(), presupuesto_s=0.5)
    inicio = time.perf_counter()
    borrador = ClinicalNoteGenerator(llm_client=cliente).generate_draft(
        construir_contexto_clinico(conn, ids["consulta_maria_1"]), format_name="SOAP")
    assert time.perf_counter() - inicio < 10
    assert cliente.ultimo_uso.uso_respaldo and borrador.to_text()


def test_el_cliente_del_presupuesto_no_reintenta():
    from operacion.presupuesto import cliente_openai_para_presupuesto

    cliente = cliente_openai_para_presupuesto(presupuesto_s=8, api_key="sk-prueba")
    assert cliente._timeout == 8 and cliente._max_retries == 0


# --- AC1: carga concurrente sin errores ---------------------------------------


@pytest.fixture()
def servidor_tls(tmp_path, monkeypatch):
    """La API de pacientes real servida por TLS en un hilo, sobre bases temporales con 40 pacientes."""
    import uvicorn

    import patients.api as api
    from patients import db
    from seguridad.servidor_tls import construir_config, generar_certificado_local

    monkeypatch.setattr(api, "DB_PATH", tmp_path / "pacientes.db")
    monkeypatch.setattr(api, "EXPEDIENTE_PATH", tmp_path / "expediente.db")
    conn = db.conectar(tmp_path / "pacientes.db")
    db.inicializar(conn)
    for i in range(40):
        conn.execute(
            "INSERT INTO pacientes (nombre_completo, fecha_nacimiento, sexo, tipo_identificacion, numero_identificacion, "
            "oncologo_id, fecha_registro) VALUES (?, '1970-01-01', 'femenino', 'cedula', ?, 1, '2026-01-01')",
            (f"Paciente {i}", f"{10000000 + i}"),
        )
    conn.commit()
    conn.close()
    cert, clave = generar_certificado_local(tmp_path / "certs")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    config = construir_config(api.app, "127.0.0.1", puerto, str(cert), str(clave))
    config.log_level = "warning"
    servidor = uvicorn.Server(config)
    hilo = threading.Thread(target=servidor.run, daemon=True)
    hilo.start()
    for _ in range(200):
        if servidor.started:
            break
        time.sleep(0.05)
    yield f"https://127.0.0.1:{puerto}", str(cert), tmp_path / "pacientes.db"
    servidor.should_exit = True
    hilo.join(timeout=5)


def test_ac1_diez_medicos_a_la_vez_sin_errores_y_bajo_2_s(servidor_tls):
    """Antes de NFR-02 este caso devolvía 500 en ~80 % de las peticiones (ProgrammingError de SQLite)."""
    from operacion.carga import ejecutar_carga, pacientes_de_muestra
    from seguridad.tls import contexto_tls_cliente

    url, cert, base = servidor_tls
    resultado = ejecutar_carga(url, pacientes_de_muestra(base), usuarios=10, iteraciones=5,
                               verificar=contexto_tls_cliente(cert))
    assert resultado.peticiones == 150
    assert resultado.errores == 0, resultado.primer_error
    assert resultado.p95_ms < OBJETIVO_CONSULTA_S * 1000 and resultado.cumple


def test_las_bases_quedan_en_wal(tmp_path):
    import sqlite3

    from historia_clinica.db import conectar_expediente
    from patients import db

    for conn in (db.conectar(tmp_path / "p.db"), conectar_expediente(tmp_path / "e.db")):
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        conn.close()
    memoria = db.conectar(":memory:")
    assert memoria.execute("PRAGMA journal_mode").fetchone()[0] == "memory"


def test_la_base_de_pacientes_se_puede_cambiar_por_entorno(tmp_path):
    import os
    import subprocess
    import sys

    salida = subprocess.run(
        [sys.executable, "-c", "from patients import db; print(db.RUTA_DB)"],
        env={**os.environ, "COPILOTO_PACIENTES_DB": str(tmp_path / "otra.db")}, capture_output=True, text=True,
        cwd=str(__import__("pathlib").Path(__file__).resolve().parents[2]),
    )
    assert salida.stdout.strip() == str(tmp_path / "otra.db")
