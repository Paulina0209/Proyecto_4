"""NFR-05 — Varias réplicas de la interfaz atienden al mismo usuario.

Dos instancias de la pasarela (como dos procesos de ``--workers 2`` o dos
máquinas detrás de un balanceador) comparten las sesiones por
``COPILOTO_SESIONES_DB``: la sesión que abre una la reconoce la otra, y
cerrarla en una la cierra en ambas.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from frontend.demo import construir_app
from frontend.sesiones import AlmacenSesiones, AlmacenSesionesSQLite

from .conftest import H, PUERTO, iniciar_sesion


def _replicas(entorno, tmp_path, monkeypatch):
    monkeypatch.setenv("COPILOTO_SESIONES_DB", str(tmp_path / "sesiones.db"))
    rutas = {"accesos": entorno.carpeta / "metricas_accesos.db", "expediente": entorno.carpeta / "metricas_expediente.db"}
    return construir_app(entorno, PUERTO, metricas=rutas), construir_app(entorno, PUERTO, metricas=rutas)


def test_la_sesion_abierta_en_una_replica_sirve_en_la_otra(entorno, tmp_path, monkeypatch):
    app_a, app_b = _replicas(entorno, tmp_path, monkeypatch)
    with TestClient(app_a, base_url="https://testserver") as a, TestClient(app_b, base_url="https://testserver") as b:
        assert iniciar_sesion(a, "dra.rios").status_code == 200
        b.cookies.update(a.cookies)

        sesion = b.get("/api/sesion").json()
        assert sesion["autenticado"] and sesion["usuario"]["nombre_usuario"] == "dra.rios"
        assert b.get("/api/pacientes").status_code == 200

        # Cerrar sesión en la réplica B la cierra también en A.
        assert b.delete("/api/sesion", headers=H).status_code == 204
        assert a.get("/api/sesion").json() == {"autenticado": False}


def test_sin_almacen_compartido_cada_replica_tiene_sus_sesiones(entorno, monkeypatch):
    """El comportamiento de siempre (un solo proceso): sesiones en memoria."""
    monkeypatch.delenv("COPILOTO_SESIONES_DB", raising=False)
    rutas = {"accesos": entorno.carpeta / "metricas_accesos.db", "expediente": entorno.carpeta / "metricas_expediente.db"}
    app_a, app_b = construir_app(entorno, PUERTO, metricas=rutas), construir_app(entorno, PUERTO, metricas=rutas)
    with TestClient(app_a, base_url="https://testserver") as a, TestClient(app_b, base_url="https://testserver") as b:
        assert iniciar_sesion(a, "dra.rios").status_code == 200
        b.cookies.update(a.cookies)
        assert b.get("/api/sesion").json() == {"autenticado": False}


def test_las_sondas_de_la_pasarela(entorno, tmp_path, monkeypatch):
    app_a, _ = _replicas(entorno, tmp_path, monkeypatch)
    with TestClient(app_a, base_url="https://testserver") as c:
        listo = c.get("/salud/listo")
        nombres = {v["nombre"]: v["estado"] for v in listo.json()["verificaciones"]}
        assert listo.status_code == 200
        assert nombres["usuarios"] == nombres["base de pacientes"] == nombres["sesiones compartidas"] == "ok"
        assert "server-timing" in c.get("/api/sesion").headers
    with TestClient(app_a, base_url="http://testserver") as en_claro:
        assert en_claro.get("/salud/vivo").status_code == 200   # la sonda de vida, sin datos
        assert en_claro.get("/salud/listo").status_code == 403  # lo demás sigue exigiendo HTTPS


def test_el_almacen_compartido_respeta_las_caducidades(tmp_path):
    reloj = [1000.0]
    almacen = AlmacenSesionesSQLite(tmp_path / "s.db", inactividad_s=60, duracion_maxima_s=300, reloj=lambda: reloj[0])
    otro = AlmacenSesionesSQLite(tmp_path / "s.db", inactividad_s=60, duracion_maxima_s=300, reloj=lambda: reloj[0])
    token = almacen.abrir(7)
    assert otro.resolver(token) == 7
    reloj[0] += 59
    assert otro.resolver(token) == 7          # renueva la inactividad
    reloj[0] += 61
    assert almacen.resolver(token) is None    # caducó por inactividad
    t2 = almacen.abrir(7)
    for _ in range(6):
        reloj[0] += 55
        almacen.resolver(t2)
    assert almacen.resolver(t2) is None       # caducó por antigüedad aunque se use
    t3, t4 = almacen.abrir(8), almacen.abrir(8)
    assert otro.cerrar_de_usuario(8) == 2 and len(almacen) == 0
    assert isinstance(almacen, AlmacenSesiones)


def test_el_almacen_no_guarda_el_token(tmp_path):
    import sqlite3

    almacen = AlmacenSesionesSQLite(tmp_path / "s.db")
    token = almacen.abrir(1)
    with sqlite3.connect(tmp_path / "s.db") as conn:
        guardado = conn.execute("SELECT clave FROM sesiones").fetchone()[0]
    assert guardado != token and token not in guardado
