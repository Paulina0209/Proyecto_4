"""NFR-02 — Disponibilidad (SLA ≥ 99,5 %).

AC1: sondas de vida y de preparación para el balanceador.
AC2: una dependencia externa caída degrada pero no saca la réplica de servicio;
     una base que falta sí (503).
AC3: la disponibilidad se mide contra el SLA, con presupuesto de error e incidentes.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, time as hora, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from operacion import monitor, salud
from operacion.monitor import Sondeo, calcular
from operacion.salud import EstadoVerificacion, Verificacion, estado_general


# --- AC1 / AC2: sondas ----------------------------------------------------------


@pytest.fixture()
def api(tmp_path, monkeypatch):
    import patients.api as api

    monkeypatch.setattr(api, "DB_PATH", tmp_path / "pacientes.db")
    monkeypatch.setattr(api, "EXPEDIENTE_PATH", tmp_path / "expediente.db")
    return api


def test_vivo_responde_tambien_en_claro(api):
    with TestClient(api.app, base_url="http://testserver") as c:
        r = c.get("/salud/vivo")
        assert r.status_code == 200 and r.json()["estado"] == "vivo"
        assert c.get("/pacientes", params={"oncologo_id": 1}).status_code == 403  # los datos, solo HTTPS


def test_listo_con_las_bases_disponibles(api, monkeypatch):
    monkeypatch.delenv("COPILOTO_PACS_URL", raising=False)
    with TestClient(api.app, base_url="https://testserver") as c:
        c.get("/pacientes/1/consentimiento-ia", params={"oncologo_id": 1})  # crea el expediente
        r = c.get("/salud/listo")
    estados = {v["nombre"]: v["estado"] for v in r.json()["verificaciones"]}
    assert r.status_code == 200
    assert estados["base de pacientes"] == "ok" and estados["espacio en disco"] == "ok"
    assert estados["PACS"] == "degradado"  # sin PACS: degradado, pero la réplica sigue atendiendo
    assert r.json()["estado"] == "degradado"


def test_listo_falla_si_la_base_de_pacientes_no_esta(api, tmp_path):
    with TestClient(api.app, base_url="https://testserver") as c:
        (tmp_path / "pacientes.db").unlink()
        r = c.get("/salud/listo")
    assert r.status_code == 503 and r.json()["estado"] == "falla"


def test_expediente_aun_no_creado_no_es_falla(api):
    with TestClient(api.app, base_url="https://testserver") as c:
        r = c.get("/salud/listo")
    exp = next(v for v in r.json()["verificaciones"] if v["nombre"] == "expediente clínico")
    assert r.status_code == 200 and exp["estado"] == "falla" and not exp["critica"]


def test_verificar_base_no_crea_ni_escribe(tmp_path):
    ruta = tmp_path / "x.db"
    assert salud.verificar_base("x", ruta).estado is EstadoVerificacion.FALLA and not ruta.exists()
    sqlite3.connect(ruta).execute("CREATE TABLE t (a)").connection.close()
    assert salud.verificar_base("x", ruta).estado is EstadoVerificacion.OK


def test_estado_general():
    ok = Verificacion("a", EstadoVerificacion.OK, "")
    degradada = Verificacion("b", EstadoVerificacion.DEGRADADO, "", critica=False)
    no_critica = Verificacion("c", EstadoVerificacion.FALLA, "", critica=False)
    critica = Verificacion("d", EstadoVerificacion.FALLA, "")
    assert estado_general([ok]) is EstadoVerificacion.OK
    assert estado_general([ok, degradada, no_critica]) is EstadoVerificacion.DEGRADADO
    assert estado_general([ok, critica]) is EstadoVerificacion.FALLA


def test_metricas_de_la_replica(api):
    with TestClient(api.app, base_url="https://testserver") as c:
        c.get("/pacientes", params={"oncologo_id": 1})
        rutas = {r["ruta"]: r for r in c.get("/salud/metricas").json()["rutas"]}
    assert rutas["GET /pacientes"]["peticiones"] >= 1 and "p95_ms" in rutas["GET /pacientes"]


# --- AC3: SLA ---------------------------------------------------------------------

T0 = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)


def _serie(caidos: set, total: int, intervalo: int = 60):
    return [Sondeo(T0 + timedelta(seconds=i * intervalo), i not in caidos, 20.0, None if i not in caidos else "HTTP 503")
            for i in range(total)]


def test_todo_disponible():
    informe = calcular(_serie(set(), 1000), 60)
    assert informe.disponibilidad == 100.0 and informe.cumple and not informe.incidentes
    assert informe.minutos_observados == 1000
    assert informe.presupuesto_minutos == pytest.approx(5.0)  # 0,5 % de 1000 min


def test_caida_dentro_del_presupuesto():
    informe = calcular(_serie({10, 11, 12}, 1000), 60)  # 3 min de 1000
    assert informe.disponibilidad == pytest.approx(99.7) and informe.cumple
    assert informe.presupuesto_restante_minutos == pytest.approx(2.0)
    assert len(informe.incidentes) == 1 and informe.incidentes[0].minutos == 3.0


def test_caida_que_rompe_el_sla():
    informe = calcular(_serie(set(range(100, 110)) | {500}, 1000), 60)  # 11 min
    assert informe.disponibilidad == pytest.approx(98.9) and not informe.cumple
    assert [i.minutos for i in informe.incidentes] == [10.0, 1.0]
    assert informe.presupuesto_restante_minutos < 0


def test_monitor_apagado_no_cuenta_como_caida():
    sondeos = _serie(set(), 10) + [Sondeo(T0 + timedelta(hours=5), True, 10.0)]
    informe = calcular(sondeos, 60)
    assert informe.disponibilidad == 100.0 and informe.minutos_observados == 11


def test_solo_horario_clinico():
    # Hora local del equipo (naive -> astimezone la toma como local).
    noche = [Sondeo(datetime(2026, 10, 1, 3, m).astimezone(), False) for m in range(10)]
    dia = [Sondeo(datetime(2026, 10, 1, 12, m).astimezone(), True) for m in range(10)]
    horario = (hora(7, 0), hora(19, 0))
    assert calcular(noche + dia, 60, horario=horario).disponibilidad == 100.0
    assert calcular(noche + dia, 60).disponibilidad == 50.0


def test_guardar_y_leer(tmp_path):
    conn = monitor.conectar(tmp_path / "d.db")
    for s in _serie({1}, 3):
        monitor.guardar(conn, s)
    leidos = monitor.leer(conn, T0 - timedelta(minutes=1), T0 + timedelta(hours=1))
    assert [s.disponible for s in leidos] == [True, False, True]


def test_sondear_contra_la_api_real(api):
    with TestClient(api.app, base_url="https://testserver") as c:
        ok = monitor.sondear("https://testserver/salud/listo", cliente=c)
        assert ok.disponible and ok.ms is not None
        (api.DB_PATH).unlink()
        caido = monitor.sondear("https://testserver/salud/listo", cliente=c)
    assert not caido.disponible and "503" in caido.detalle and "base de pacientes" in caido.detalle


def test_sondear_sin_servidor():
    sondeo = monitor.sondear("https://127.0.0.1:9/salud/listo", tiempo_maximo_s=1)
    assert not sondeo.disponible and sondeo.detalle


def test_cli_vigilar_e_informe(api, tmp_path, monkeypatch, capsys):
    llamadas = []
    monkeypatch.setattr(monitor, "sondear", lambda url, ca=None, t=5.0: llamadas.append(url) or Sondeo(datetime.now(timezone.utc), True, 5.0))
    monkeypatch.setattr(monitor.time, "sleep", lambda s: None)
    assert monitor.main(["--base", str(tmp_path / "d.db"), "vigilar", "https://x/salud/listo", "--veces", "3", "--intervalo", "1"]) == 0
    assert len(llamadas) == 3
    assert monitor.main(["--base", str(tmp_path / "d.db"), "informe", "--intervalo", "1"]) == 0
    assert "CUMPLE" in capsys.readouterr().out
