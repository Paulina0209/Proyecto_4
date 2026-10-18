"""ADM-02 por HTTP: GET /metricas y GET /metricas/panel (HTTP Basic sobre SEC-01, solo HTTPS)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from administracion import api as api_module
from auditoria.models import TipoAccion
from seguridad.models import Rol
from tests.administracion.conftest import CLAVE, CLAVE_ADMIN

ADMIN = ("admin.sistema", CLAVE_ADMIN)
DIRECTOR = ("direccion.medica", CLAVE)


def _dia(atras: int) -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=atras)).isoformat()


@pytest.fixture()
def mundo_api(mundo, monkeypatch):
    mundo.equipo(5, 5)
    # Datos relativos a hoy: la API usa el reloj real.
    for u in mundo.oncologos[:3]:
        mundo.acceso(u, _dia(3))
    mundo.alerta(_dia(2))
    mundo.alerta(_dia(5), estado="revisada")
    mundo.nota_aprobada(_dia(1), 2)
    monkeypatch.setattr(api_module, "USUARIOS_DB_PATH", mundo.ruta_usuarios)
    monkeypatch.setattr(api_module, "METRICAS_DB_PATHS", [mundo.ruta_accesos, mundo.ruta_expediente])
    return mundo


@pytest.fixture()
def client(mundo_api):
    with TestClient(api_module.app, base_url="https://testserver") as c:
        yield c


def _eventos(mundo):
    filas = mundo.usuarios.execute(
        "SELECT usuario_id, detalle FROM eventos_acceso WHERE accion = ? ORDER BY id", (TipoAccion.CONSULTAR_METRICAS.value,)).fetchall()
    return [(f[0], json.loads(f[1])) for f in filas]


def test_el_director_obtiene_las_metricas_en_json(client, mundo_api):
    r = client.get("/metricas", auth=DIRECTOR)
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    d = r.json()
    assert (d["adopcion"]["usuarios_activos"], d["adopcion"]["usuarios_elegibles"]) == (3, 10)
    assert d["adopcion"]["tasa_adopcion"] == pytest.approx(0.3)
    assert d["alertas"]["generadas"] == 2 and d["alertas"]["revisadas"] == 1
    assert d["tiempo_ahorrado"]["es_estimacion"] is True and d["tiempo_ahorrado"]["horas_max"] > d["tiempo_ahorrado"]["horas_min"]
    assert {x["dominio"] for x in d["aceptacion_ia"]["dominios"]} == {"TX", "EST"}
    assert d["periodo"]["dias"] == 30


def test_la_respuesta_no_trae_nada_por_persona(client, mundo_api):
    texto = client.get("/metricas", auth=DIRECTOR).text
    for nombre in mundo_api.nombres.values():
        assert nombre not in texto
    assert "oncologo_id" not in texto and "usuario_id" not in texto


def test_periodo_por_parametros(client):
    r = client.get("/metricas", auth=DIRECTOR, params={"desde": _dia(9), "hasta": _dia(0)})
    assert r.status_code == 200 and r.json()["periodo"]["dias"] == 10 and r.json()["periodo"]["desde"] == _dia(9)


@pytest.mark.parametrize("params", [
    {"desde": _dia(0), "hasta": _dia(5)},          # al revés
    {"desde": "ayer"},                             # no es una fecha
    {"hasta": (datetime.now(timezone.utc).date() + timedelta(days=3)).isoformat()},  # futuro
    {"desde": "2020-01-01"},                       # más de 400 días
])
def test_periodos_invalidos_son_400(client, params):
    r = client.get("/metricas", auth=DIRECTOR, params=params)
    assert r.status_code == 400 and r.json()["errores"]


def test_sin_credenciales_o_con_credenciales_malas_es_401(client):
    assert client.get("/metricas").status_code == 401
    assert client.get("/metricas/panel").status_code == 401
    r = client.get("/metricas", auth=("direccion.medica", "mala-clave-123"))
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Basic"


@pytest.mark.parametrize("ruta", ["/metricas", "/metricas/panel"])
def test_quien_no_es_director_recibe_403_y_queda_auditado(client, mundo_api, ruta):
    assert client.get(ruta, auth=("onco.01", CLAVE)).status_code == 403
    assert client.get(ruta, auth=ADMIN).status_code == 403  # ni siquiera el administrador del sistema
    eventos = _eventos(mundo_api)
    assert [d["resultado"] for _, d in eventos] == ["denegado", "denegado"]
    assert eventos[0][0] == mundo_api.oncologos[0].id


def test_cada_consulta_exitosa_queda_en_la_auditoria_con_su_via(client, mundo_api):
    client.get("/metricas", auth=DIRECTOR)
    client.get("/metricas/panel", auth=DIRECTOR)
    assert [(d["resultado"], d["via"]) for _, d in _eventos(mundo_api)] == [("ok", "api"), ("ok", "panel")]


def test_el_panel_es_html_con_politica_de_contenido_estricta(client):
    r = client.get("/metricas/panel", auth=DIRECTOR)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert r.headers["cache-control"] == "no-store"
    csp = r.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "frame-ancestors 'none'" in csp and "connect-src" not in csp
    assert "Uso del copiloto oncológico" in r.text and "Cómo leer esto" in r.text


def test_el_panel_respeta_el_periodo(client):
    r = client.get("/metricas/panel", auth=DIRECTOR, params={"desde": _dia(6), "hasta": _dia(0)})
    assert r.status_code == 200 and "7 días" in r.text and f'value="{_dia(6)}"' in r.text


def test_solo_por_https(mundo_api):
    with TestClient(api_module.app, base_url="http://testserver") as http:
        assert http.get("/metricas", auth=DIRECTOR).status_code == 403
        assert http.get("/metricas/panel", auth=DIRECTOR).status_code == 403


def test_sin_bases_conectadas_lo_que_falta_es_null_no_cero(client, monkeypatch, tmp_path):
    monkeypatch.setattr(api_module, "METRICAS_DB_PATHS", [tmp_path / "no_existe.db"])  # una base ilegible no tumba el tablero
    d = client.get("/metricas", auth=DIRECTOR).json()
    assert d["alertas"]["disponible"] is False and d["alertas"]["generadas"] is None
    assert "alertas_laboratorio" in d["fuentes_no_disponibles"]


def test_consultar_no_modifica_las_bases_clinicas(client, mundo_api):
    antes = (mundo_api.ruta_accesos.read_bytes(), mundo_api.ruta_expediente.read_bytes())
    client.get("/metricas", auth=DIRECTOR)
    client.get("/metricas/panel", auth=DIRECTOR)
    assert (mundo_api.ruta_accesos.read_bytes(), mundo_api.ruta_expediente.read_bytes()) == antes


# --- ADM-01 + ADM-02: el administrador da de alta al director médico --------------------


def test_el_administrador_crea_un_director_medico_y_este_ya_puede_consultar(client):
    r = client.post("/usuarios", auth=ADMIN, json={
        "nombre_usuario": "dra.direccion", "contrasena": CLAVE, "rol": "director_medico",
        "nombre_completo": "Dra. Dirección", "correo": "dra.direccion@hospital.org"})
    assert r.status_code == 201 and r.json()["rol"] == "director_medico"
    assert client.get("/metricas", auth=("dra.direccion", CLAVE)).status_code == 200


def test_la_matriz_de_roles_muestra_el_permiso_nuevo_solo_para_el_director(client):
    roles = {x["rol"]: x["permisos"] for x in client.get("/roles", auth=ADMIN).json()}
    assert "ver_metricas_uso" in roles["director_medico"]
    assert all("ver_metricas_uso" not in p for rol, p in roles.items() if rol != "director_medico")
    assert not any(a in roles["director_medico"] for a in ("ver_expediente", "editar_expediente", "gestionar_usuarios"))
