"""Pruebas de PAC-03 (dashboard 360) contra la API real, con la base MOCK
sembrada por el lifespan de la app -- sin mockear nada del camino."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import patients.api as api_module
from patients.api import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DB_PATH", tmp_path / "pacientes_test.db")
    monkeypatch.setattr(api_module, "DB_PATH_360", tmp_path / "resumen_360_test.db")
    with TestClient(app) as c:
        yield c


def test_ac1_dashboard_del_paciente_completo_muestra_todo_sin_navegar(client):
    r = client.get("/pacientes/1/resumen-360", params={"oncologo_id": 1})
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["nombre"] == "María Gómez"
    assert body["diagnostico_principal"] == "NSCLC metastásico no oncogénico"
    assert body["estadio"] == "IV"

    # Debe tomar el tratamiento MAS RECIENTE por fecha_inicio, no el primero.
    assert body["tratamiento_mas_reciente"]["regimen"] == "pembrolizumab + pemetrexed"

    # Alertas activas (interacciones + estudios pendientes), ordenadas por
    # severidad -- y la ya resuelta no debe aparecer.
    severidades = [a["severidad"] for a in body["alertas_activas"]]
    assert severidades == ["alta", "media"]
    assert len(body["alertas_activas"]) == 2

    # Accesos rápidos a labs/imágenes/notas.
    assert len(body["labs_recientes"]) == 2
    assert len(body["imagenes_recientes"]) == 1
    assert len(body["notas_recientes"]) == 2

    # Expediente completo: el indicador de informacion faltante NO debe encenderse.
    assert body["campos_faltantes"] == []
    assert body["informacion_incompleta"] is False


def test_ac2_dashboard_del_paciente_incompleto_muestra_indicador_claro(client):
    r = client.get("/pacientes/2/resumen-360", params={"oncologo_id": 1})
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["nombre"] == "Carlos Ruiz"
    assert body["diagnostico_principal"] is None
    assert body["estadio"] is None
    assert body["tratamiento_mas_reciente"] is None

    assert body["informacion_incompleta"] is True
    assert set(body["campos_faltantes"]) == {
        "diagnostico_principal", "estadio", "tratamiento_mas_reciente",
    }

    # Que falte lo clínico clave no debe ocultar lo que SÍ hay disponible.
    assert len(body["labs_recientes"]) == 1


def test_regla_de_negocio_oncologo_no_puede_ver_paciente_de_otro(client):
    r = client.get("/pacientes/1/resumen-360", params={"oncologo_id": 999})
    assert r.status_code == 404


def test_paciente_inexistente_da_404(client):
    r = client.get("/pacientes/999999/resumen-360", params={"oncologo_id": 1})
    assert r.status_code == 404


def test_reinicio_del_servidor_no_duplica_los_datos_sembrados(tmp_path, monkeypatch):
    """El lifespan solo siembra si la base está vacía -- dos 'arranques'
    seguidos sobre el mismo archivo no deben duplicar pacientes."""
    monkeypatch.setattr(api_module, "DB_PATH", tmp_path / "pacientes_test.db")
    monkeypatch.setattr(api_module, "DB_PATH_360", tmp_path / "resumen_360_test.db")

    with TestClient(app):
        pass  # primer "arranque": siembra

    with TestClient(app) as c:  # segundo "arranque": NO debe volver a sembrar
        r = c.get("/pacientes/1/resumen-360", params={"oncologo_id": 1})
        assert r.status_code == 200
        # Si hubiera sembrado dos veces, este paciente sería el id 3, no el 1.
        r2 = c.get("/pacientes/3/resumen-360", params={"oncologo_id": 1})
        assert r2.status_code == 404
