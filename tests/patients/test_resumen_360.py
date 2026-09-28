"""PAC-03 · Resumen 360 del paciente."""
from __future__ import annotations

import pytest

ONCOLOGO = {"oncologo_id": 1}


def _resumen(client, paciente_id, oncologo_id=1):
    return client.get(f"/pacientes/{paciente_id}/resumen-360", params={"oncologo_id": oncologo_id})


def test_ac1_expediente_completo_muestra_todo_sin_navegar(client_con_datos):
    r = _resumen(client_con_datos, 1)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["nombre"] == "María Gómez"
    assert body["diagnostico_principal"] == "NSCLC metastásico no oncogénico"
    assert body["estadio"] == "IV"
    # El tratamiento MÁS RECIENTE por fecha de inicio, no el primero registrado.
    assert body["tratamiento_mas_reciente"]["regimen"] == "pembrolizumab + pemetrexed"

    # Alertas activas por severidad; la ya resuelta no aparece.
    assert [a["severidad"] for a in body["alertas_activas"]] == ["alta", "media"]

    # Acceso rápido: cada entrada dice qué es (prueba / modalidad).
    assert [e["titulo"] for e in body["labs_recientes"]] == ["Hemograma", "Función hepática"]
    assert [e["titulo"] for e in body["imagenes_recientes"]] == ["TAC tórax"]
    assert len(body["notas_recientes"]) == 2
    assert body["notas_recientes"][0]["titulo"] is None

    assert body["campos_faltantes"] == []
    assert body["informacion_incompleta"] is False


def test_ac2_informacion_incompleta_muestra_indicador(client_con_datos):
    body = _resumen(client_con_datos, 2).json()

    assert body["nombre"] == "Carlos Ruiz"
    assert body["diagnostico_principal"] is None
    assert body["estadio"] is None
    assert body["tratamiento_mas_reciente"] is None
    assert body["informacion_incompleta"] is True
    assert set(body["campos_faltantes"]) == {"diagnostico_principal", "estadio", "tratamiento_mas_reciente"}

    # Que falte lo clínico clave no oculta lo que sí hay.
    assert len(body["labs_recientes"]) == 1


def test_ac2_un_solo_campo_faltante(client_con_datos):
    body = _resumen(client_con_datos, 7).json()
    assert body["campos_faltantes"] == ["estadio"]
    assert body["diagnostico_principal"]
    assert body["tratamiento_mas_reciente"]


def test_acceso_rapido_limitado_para_no_sobrecargar(client_con_datos):
    # Juan Carlos Pérez tiene 5 laboratorios; la lista nunca pasa del límite.
    from patients.resumen_360 import LIMITE_ACCESO_RAPIDO

    assert len(_resumen(client_con_datos, 3).json()["labs_recientes"]) <= LIMITE_ACCESO_RAPIDO


def test_cada_paciente_de_la_busqueda_abre_su_resumen(client_con_datos):
    body = client_con_datos.get("/pacientes/buscar", params={**ONCOLOGO, "tamano_pagina": 100}).json()
    for paciente in body["items"]:
        r = _resumen(client_con_datos, paciente["id"])
        assert r.status_code == 200, paciente
        assert r.json()["nombre"] == paciente["nombre_completo"]


def test_refleja_lo_registrado_en_registro_y_busqueda(client):
    """Una sola base: el 360 de un paciente recién registrado se completa
    con los diagnósticos, tratamientos y consultas que se le agregan."""
    pid = client.post("/pacientes", json={
        "nombre_completo": "Elena Vargas", "sexo": "femenino", "tipo_identificacion": "cedula",
        "numero_identificacion": "2000001", "contacto": {"telefono": "3000000000"}, "oncologo_id": 1,
    }).json()["id"]

    vacio = _resumen(client, pid).json()
    assert vacio["nombre"] == "Elena Vargas"
    assert vacio["informacion_incompleta"] is True

    client.post(f"/pacientes/{pid}/diagnosticos", params=ONCOLOGO,
                json={"descripcion": "Adenocarcinoma gástrico", "estadio": "II", "fecha": "2026-09-01"})
    client.post(f"/pacientes/{pid}/tratamientos", params=ONCOLOGO,
                json={"estado": "en_tratamiento", "regimen": "FLOT", "fecha_inicio": "2026-09-05"})
    client.post(f"/pacientes/{pid}/consultas", params=ONCOLOGO,
                json={"fecha": "2026-09-05", "nota": "Inicio de FLOT"})

    completo = _resumen(client, pid).json()
    assert completo["diagnostico_principal"] == "Adenocarcinoma gástrico"
    assert completo["estadio"] == "II"
    assert completo["tratamiento_mas_reciente"]["regimen"] == "FLOT"
    assert completo["notas_recientes"][0]["resumen"] == "Inicio de FLOT"
    assert completo["informacion_incompleta"] is False


@pytest.mark.parametrize("paciente_id,oncologo_id", [
    (1, 999),      # de otro oncólogo
    (10, 1),       # Laura Jiménez es del oncólogo 2
    (999999, 1),   # no existe
])
def test_paciente_ajeno_o_inexistente_da_404(client_con_datos, paciente_id, oncologo_id):
    assert _resumen(client_con_datos, paciente_id, oncologo_id).status_code == 404
