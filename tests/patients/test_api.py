"""AUD-01 sobre la API de pacientes: GET /pacientes/{id} con `usuario_id`
deja el acceso registrado en el log de auditoría; sin él, no registra nada."""
from __future__ import annotations

import patients.api as api_module
from auditoria.registro_acceso import obtener_eventos_de_paciente
from patients import db


def _payload(**overrides) -> dict:
    base = {
        "nombre_completo": "María Restrepo",
        "fecha_nacimiento": "1975-03-02",
        "sexo": "femenino",
        "tipo_identificacion": "cedula",
        "numero_identificacion": "99887766",
        "contacto": {"telefono": "3001112233"},
        "oncologo_id": 1,
    }
    base.update(overrides)
    return base


def _eventos(paciente_id: int):
    conn = db.conectar(api_module.DB_PATH)
    try:
        return obtener_eventos_de_paciente(conn, paciente_id)
    finally:
        conn.close()


def test_leer_paciente_con_usuario_id_registra_el_acceso_en_auditoria(client):
    creado = client.post("/pacientes", json=_payload()).json()

    respuesta = client.get(
        f"/pacientes/{creado['id']}", params={"oncologo_id": 1, "usuario_id": 10}
    )
    assert respuesta.status_code == 200

    eventos = _eventos(creado["id"])
    assert len(eventos) == 1
    assert eventos[0].usuario_id == 10
    assert eventos[0].accion.value == "ver"


def test_leer_paciente_sin_usuario_id_no_registra_ningun_acceso(client):
    creado = client.post("/pacientes", json=_payload()).json()

    client.get(f"/pacientes/{creado['id']}", params={"oncologo_id": 1})

    assert _eventos(creado["id"]) == ()


def test_leer_paciente_de_otro_oncologo_no_registra_acceso(client):
    creado = client.post("/pacientes", json=_payload()).json()

    respuesta = client.get(
        f"/pacientes/{creado['id']}", params={"oncologo_id": 2, "usuario_id": 10}
    )
    assert respuesta.status_code == 404
    assert _eventos(creado["id"]) == ()
