"""PAC-02 · Búsqueda y filtros, y los datos clínicos sobre los que filtra."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

ONCOLOGO = {"oncologo_id": 1}


def _buscar(client, **params):
    r = client.get("/pacientes/buscar", params={**ONCOLOGO, **params})
    assert r.status_code == 200, r.text
    return r.json()


def _nombres(body):
    return {p["nombre_completo"] for p in body["items"]}


def _registrar(client, oncologo_id=1, numero="2000001", nombre="Elena Vargas"):
    r = client.post("/pacientes", json={
        "nombre_completo": nombre, "sexo": "femenino", "tipo_identificacion": "cedula",
        "numero_identificacion": numero, "contacto": {"telefono": "3000000000"},
        "oncologo_id": oncologo_id,
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---------------------------------------------------------------------------
# AC1: nombre parcial (sobre los datos de prueba)
# ---------------------------------------------------------------------------

def test_ac1_nombre_parcial_sin_tildes_ni_mayusculas(client_con_datos):
    assert _nombres(_buscar(client_con_datos, nombre="JOSE")) == {"José Luis Martínez", "María José Herrera"}
    # Palabras en cualquier orden y parciales.
    assert _nombres(_buscar(client_con_datos, nombre="perez juan")) == {"Juan Carlos Pérez"}


# ---------------------------------------------------------------------------
# AC2: filtros combinados sin resultados → mensaje claro
# ---------------------------------------------------------------------------

def test_ac2_filtros_combinados_sin_resultados_dan_mensaje(client_con_datos):
    body = _buscar(client_con_datos, diagnostico="mama", estado_tratamiento="finalizado")
    assert body["total"] == 0
    assert body["items"] == []
    assert "diagnostico: mama" in body["mensaje"]
    assert "estado_tratamiento: finalizado" in body["mensaje"]


def test_sin_pacientes_el_mensaje_lo_dice(client):
    assert _buscar(client)["mensaje"] == "Aún no tienes pacientes registrados."


def test_filtros_combinados_con_resultados(client_con_datos):
    body = _buscar(client_con_datos, diagnostico="mama", estado_tratamiento="en_tratamiento")
    assert _nombres(body) == {"Ana Sofía Rodríguez"}
    assert body["mensaje"] is None


def test_estado_es_el_del_tratamiento_mas_reciente(client_con_datos):
    # María Gómez tiene uno finalizado (antiguo) y uno en tratamiento (actual).
    assert "María Gómez" in _nombres(_buscar(client_con_datos, estado_tratamiento="en_tratamiento"))
    assert "María Gómez" not in _nombres(_buscar(client_con_datos, estado_tratamiento="finalizado"))


def test_filtro_por_fecha_de_ultima_consulta(client_con_datos):
    body = _buscar(client_con_datos, ultima_consulta_desde="2026-09-01", ultima_consulta_hasta="2026-09-20")
    assert _nombres(body) == {"María Gómez", "Carlos Ruiz", "Juan Carlos Pérez", "Lucía Fernández"}


def test_rango_de_fechas_invertido_da_400(client):
    r = client.get("/pacientes/buscar", params={
        **ONCOLOGO, "ultima_consulta_desde": "2026-09-20", "ultima_consulta_hasta": "2026-09-01",
    })
    assert r.status_code == 400
    assert r.json()["detail"]["errores"][0]["campo"] == "ultima_consulta_desde"


# ---------------------------------------------------------------------------
# Regla de negocio y riesgo UX
# ---------------------------------------------------------------------------

def test_regla_de_negocio_solo_pacientes_del_oncologo(client_con_datos):
    assert _buscar(client_con_datos, nombre="laura")["total"] == 0

    r = client_con_datos.get("/pacientes/buscar", params={"oncologo_id": 2})
    assert _nombres(r.json()) == {"Laura Jiménez"}


def test_paginacion(client_con_datos):
    pagina_1 = _buscar(client_con_datos, tamano_pagina=5, pagina=1)
    pagina_2 = _buscar(client_con_datos, tamano_pagina=5, pagina=2)

    assert pagina_1["total"] == 9
    assert pagina_1["total_paginas"] == 2
    assert len(pagina_1["items"]) == 5
    assert len(pagina_2["items"]) == 4
    assert not _nombres(pagina_1) & _nombres(pagina_2)


# ---------------------------------------------------------------------------
# Datos clínicos: lo que se registra alimenta los filtros
# ---------------------------------------------------------------------------

def test_diagnostico_registrado_alimenta_el_filtro(client):
    pid = _registrar(client)
    assert _buscar(client, diagnostico="gastrico")["total"] == 0

    r = client.post(f"/pacientes/{pid}/diagnosticos", params=ONCOLOGO,
                    json={"descripcion": "  Adenocarcinoma gástrico  ", "estadio": "II", "fecha": "2026-09-01"})
    assert r.status_code == 201, r.text
    assert r.json()["descripcion"] == "Adenocarcinoma gástrico"
    assert r.json()["estadio"] == "II"

    body = _buscar(client, diagnostico="gastrico")
    assert body["items"][0]["diagnosticos"] == ["Adenocarcinoma gástrico"]


def test_tratamiento_registrado_alimenta_el_filtro_por_estado(client):
    pid = _registrar(client)
    client.post(f"/pacientes/{pid}/tratamientos", params=ONCOLOGO,
                json={"estado": "finalizado", "regimen": "FOLFOX", "fecha_inicio": "2026-01-10"})
    r = client.post(f"/pacientes/{pid}/tratamientos", params=ONCOLOGO,
                    json={"estado": "en_tratamiento", "regimen": "FOLFIRI", "fecha_inicio": "2026-08-01"})
    assert r.status_code == 201, r.text
    assert r.json()["regimen"] == "FOLFIRI"

    assert _buscar(client, estado_tratamiento="en_tratamiento")["total"] == 1
    assert _buscar(client, estado_tratamiento="finalizado")["total"] == 0


def test_consulta_registrada_alimenta_el_filtro_por_fecha(client):
    pid = _registrar(client)
    assert _buscar(client, ultima_consulta_desde="2026-09-01")["total"] == 0

    r = client.post(f"/pacientes/{pid}/consultas", params=ONCOLOGO,
                    json={"fecha": "2026-09-15", "nota": "Control"})
    assert r.status_code == 201, r.text
    assert r.json()["nota"] == "Control"

    body = _buscar(client, ultima_consulta_desde="2026-09-01")
    assert body["items"][0]["fecha_ultima_consulta"] == "2026-09-15"


def test_historial_mas_reciente_primero(client):
    pid = _registrar(client)
    for fecha in ("2026-03-01", "2026-09-01", "2026-06-01"):
        client.post(f"/pacientes/{pid}/consultas", params=ONCOLOGO, json={"fecha": fecha})
    client.post(f"/pacientes/{pid}/diagnosticos", params=ONCOLOGO, json={"descripcion": "Dx"})
    client.post(f"/pacientes/{pid}/tratamientos", params=ONCOLOGO, json={"estado": "suspendido"})

    consultas = client.get(f"/pacientes/{pid}/consultas", params=ONCOLOGO).json()
    assert [c["fecha"] for c in consultas] == ["2026-09-01", "2026-06-01", "2026-03-01"]
    assert len(client.get(f"/pacientes/{pid}/diagnosticos", params=ONCOLOGO).json()) == 1
    tratamientos = client.get(f"/pacientes/{pid}/tratamientos", params=ONCOLOGO).json()
    assert tratamientos[0]["estado"] == "suspendido"
    assert tratamientos[0]["regimen"] is None


@pytest.mark.parametrize("ruta,metodo,payload", [
    ("diagnosticos", "post", {"descripcion": "Dx"}),
    ("tratamientos", "post", {"estado": "en_tratamiento"}),
    ("consultas", "post", {"fecha": "2026-09-01"}),
    ("diagnosticos", "get", None),
    ("tratamientos", "get", None),
    ("consultas", "get", None),
])
def test_datos_clinicos_de_paciente_ajeno_dan_404(client, ruta, metodo, payload):
    pid = _registrar(client, oncologo_id=2)
    kwargs = {"params": ONCOLOGO}
    if payload is not None:
        kwargs["json"] = payload
    assert getattr(client, metodo)(f"/pacientes/{pid}/{ruta}", **kwargs).status_code == 404


def test_datos_clinicos_de_paciente_inexistente_dan_404(client):
    r = client.post("/pacientes/999/consultas", params=ONCOLOGO, json={"fecha": "2026-09-01"})
    assert r.status_code == 404


def test_descripcion_vacia_da_400(client):
    pid = _registrar(client)
    r = client.post(f"/pacientes/{pid}/diagnosticos", params=ONCOLOGO, json={"descripcion": "   "})
    assert r.status_code == 400
    assert r.json()["detail"]["errores"][0]["campo"] == "descripcion"


@pytest.mark.parametrize("ruta,payload,campo", [
    ("consultas", {}, "fecha"),
    ("diagnosticos", {"descripcion": "Dx"}, "fecha"),
    ("tratamientos", {"estado": "en_tratamiento"}, "fecha_inicio"),
])
def test_fecha_futura_da_400(client, ruta, payload, campo):
    pid = _registrar(client)
    payload = {**payload, campo: (date.today() + timedelta(days=1)).isoformat()}
    r = client.post(f"/pacientes/{pid}/{ruta}", params=ONCOLOGO, json=payload)
    assert r.status_code == 400
    assert r.json()["detail"]["errores"][0]["campo"] == campo


def test_estado_invalido_da_400(client):
    pid = _registrar(client)
    r = client.post(f"/pacientes/{pid}/tratamientos", params=ONCOLOGO, json={"estado": "inventado"})
    assert r.status_code == 400
    assert r.json()["detail"]["errores"][0]["campo"] == "estado"
