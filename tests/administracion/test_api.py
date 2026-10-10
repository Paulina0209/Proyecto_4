"""API de ADM-01 de punta a punta (HTTP Basic sobre el login de SEC-01)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from administracion import api as api_module
from administracion import usuarios as adm
from seguridad.models import Rol

CLAVE_ADMIN = "Adm1n-Inicial"
CLAVE = "Cl1nic@2026"
ADMIN = ("admin.sistema", CLAVE_ADMIN)


@pytest.fixture(autouse=True)
def _hash_rapido(monkeypatch):
    monkeypatch.setattr("seguridad.autenticacion._ITERACIONES_PBKDF2", 1_000)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    ruta = tmp_path / "usuarios_test.db"
    monkeypatch.setattr(api_module, "USUARIOS_DB_PATH", ruta)
    conn = adm.crear_conexion(str(ruta))
    adm.crear_primer_administrador(conn, "admin.sistema", CLAVE_ADMIN, "Administrador del Sistema")
    conn.close()
    with TestClient(api_module.app) as c:
        yield c


def _alta(client, nombre="dra.gomez", rol="oncologo", **cambios):
    datos = {"nombre_usuario": nombre, "contrasena": CLAVE, "rol": rol,
             "nombre_completo": "Dra. Ana Gómez", "correo": f"{nombre}@hospital.org"}
    datos.update(cambios)
    return client.post("/usuarios", auth=ADMIN, json=datos)


def test_ciclo_completo_crear_editar_rol_desactivar(client):
    r = _alta(client)
    assert r.status_code == 201, r.text
    usuario = r.json()
    assert usuario["rol"] == "oncologo" and usuario["activo"] is True
    assert "hash_contrasena" not in usuario and "sal" not in usuario and "contrasena" not in usuario

    # El usuario nuevo puede autenticarse (SEC-01) pero no administrar.
    assert client.get("/usuarios", auth=("dra.gomez", CLAVE)).status_code == 403

    assert client.patch(f"/usuarios/{usuario['id']}", auth=ADMIN, json={"nombre_completo": "Ana María Gómez"}).json()["nombre_completo"] == "Ana María Gómez"
    r = client.put(f"/usuarios/{usuario['id']}/rol", auth=ADMIN, json={"rol": "auditor", "motivo": "Pasa a auditoría"})
    assert r.status_code == 200 and r.json()["rol"] == "auditor"
    r = client.post(f"/usuarios/{usuario['id']}/desactivar", auth=ADMIN, json={"motivo": "Renuncia"})
    assert r.json()["activo"] is False
    assert client.get("/usuarios", auth=("dra.gomez", CLAVE)).status_code == 401  # ya no entra
    assert client.post(f"/usuarios/{usuario['id']}/reactivar", auth=ADMIN).json()["activo"] is True


def test_sin_credenciales_o_con_credenciales_malas_es_401(client):
    assert client.get("/usuarios").status_code == 401
    assert client.get("/usuarios").headers["www-authenticate"] == "Basic"
    assert client.get("/usuarios", auth=("admin.sistema", "mala")).status_code == 401
    assert client.get("/usuarios", auth=("no.existe", "mala")).json() == \
        client.get("/usuarios", auth=("admin.sistema", "mala")).json()  # no revela si el usuario existe


def test_la_cuenta_se_bloquea_tambien_por_http(client):
    for _ in range(5):
        client.get("/usuarios", auth=("admin.sistema", "mala"))
    r = client.get("/usuarios", auth=ADMIN)  # la contraseña correcta ya no sirve
    assert r.status_code == 401 and "bloqueada" in r.json()["detail"]


def test_un_no_administrador_recibe_403_y_queda_auditado(client):
    _alta(client, "enf.paez", "enfermeria")
    r = client.put("/usuarios/1/rol", auth=("enf.paez", CLAVE), json={"rol": "auditor", "motivo": "x"})
    assert r.status_code == 403 and "gestionar_usuarios" in r.json()["detail"]
    eventos = client.get("/auditoria/usuarios", auth=ADMIN).json()
    assert eventos[0]["resultado"] == "denegado" and eventos[0]["operacion"] == "asignar_rol"


def test_errores_de_validacion_vienen_juntos_en_400(client):
    r = _alta(client, "Mal Nombre!", rol="medico", contrasena="corta", nombre_completo="A", correo=None)
    assert r.status_code == 400
    assert {e["campo"] for e in r.json()["errores"]} == {"nombre_usuario", "rol", "nombre_completo", "contrasena"}


def test_campos_desconocidos_y_faltantes_se_rechazan(client):
    assert client.post("/usuarios", auth=ADMIN, json={"nombre_usuario": "x.y.z", "es_admin": True}).status_code == 400
    r = client.patch("/usuarios/1", auth=ADMIN, json={"rol": "administrador"})  # el rol no se cambia por aquí
    assert r.status_code == 400


def test_duplicado_es_409_y_no_encontrado_404(client):
    _alta(client)
    assert _alta(client).status_code == 409
    assert client.get("/usuarios/999", auth=ADMIN).status_code == 404


def test_el_ultimo_administrador_no_se_puede_quitar(client):
    r = client.post("/usuarios/1/desactivar", auth=ADMIN, json={"motivo": "x"})
    assert r.status_code == 409 and "propia cuenta" in r.json()["detail"]
    r = client.put("/usuarios/1/rol", auth=ADMIN, json={"rol": "auditor", "motivo": "x"})
    assert r.status_code == 409


def test_listar_filtrar_roles_y_auditoria(client):
    _alta(client)
    _alta(client, "enf.paez", "enfermeria")
    assert [u["nombre_usuario"] for u in client.get("/usuarios", auth=ADMIN, params={"rol": "enfermeria"}).json()] == ["enf.paez"]
    assert client.get("/usuarios", auth=ADMIN, params={"rol": "inventado"}).status_code == 400
    roles = {r["rol"]: r["permisos"] for r in client.get("/roles", auth=ADMIN).json()}
    assert "confirmar_tratamiento" in roles["oncologo"] and "confirmar_tratamiento" not in roles["enfermeria"]
    assert roles["administrador"] == ["gestionar_usuarios"]
    operaciones = [e["operacion"] for e in client.get("/auditoria/usuarios", auth=ADMIN).json()]
    assert operaciones[:2] == ["crear_usuario", "crear_usuario"]


def test_restablecer_contrasena_por_http(client):
    uid = _alta(client).json()["id"]
    assert client.post(f"/usuarios/{uid}/contrasena", auth=ADMIN, json={"contrasena_nueva": "corta"}).status_code == 400
    assert client.post(f"/usuarios/{uid}/contrasena", auth=ADMIN, json={"contrasena_nueva": "Nueva-Clave-77"}).status_code == 200
    assert client.get("/usuarios", auth=("dra.gomez", "Nueva-Clave-77")).status_code == 403  # entra, pero no administra


def test_comando_crear_admin_solo_funciona_una_vez(tmp_path, monkeypatch, capsys):
    from administracion import __main__ as cli

    monkeypatch.setattr(api_module, "USUARIOS_DB_PATH", tmp_path / "nueva.db")
    respuestas = iter(["admin.uno", "Admin Uno", ""])
    monkeypatch.setattr("builtins.input", lambda _: next(respuestas))
    monkeypatch.setattr("getpass.getpass", lambda _: "Adm1n-Inicial")
    assert cli.main(["administracion", "crear-admin"]) == 0
    assert "creado" in capsys.readouterr().out

    respuestas = iter(["admin.dos", "Admin Dos", ""])
    assert cli.main(["administracion", "crear-admin"]) == 1
    assert "Ya existe un administrador activo" in capsys.readouterr().out
    assert cli.main(["administracion"]) == 2
