"""La única base de datos del módulo (patients/db) y su carga de datos de prueba."""
from __future__ import annotations

from fastapi.testclient import TestClient

import patients.api as api_module
from patients import db, medicacion_actual


def _contar_pacientes(ruta) -> int:
    conn = db.conectar(ruta)
    try:
        return conn.execute("SELECT COUNT(*) FROM pacientes").fetchone()[0]
    finally:
        conn.close()


def test_datos_prueba_se_cargan_una_sola_vez(conn):
    assert db.sembrar_datos_prueba(conn) is True
    assert db.sembrar_datos_prueba(conn) is False
    assert conn.execute("SELECT COUNT(*) FROM pacientes").fetchone()[0] == 10


def test_reiniciar_la_api_no_duplica_los_datos(tmp_path, monkeypatch):
    ruta = tmp_path / "pacientes_test.db"
    monkeypatch.setattr(api_module, "DB_PATH", ruta)

    with TestClient(api_module.app):
        pass
    sembrados = _contar_pacientes(ruta)
    with TestClient(api_module.app):
        pass
    assert _contar_pacientes(ruta) == sembrados == 10


def test_no_se_mezclan_con_pacientes_reales(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DB_PATH", tmp_path / "pacientes_test.db")

    monkeypatch.setattr(api_module, "SEMBRAR_DATOS_PRUEBA", False)
    with TestClient(api_module.app) as c:
        r = c.post("/pacientes", json={
            "nombre_completo": "Paciente Real", "sexo": "otro", "tipo_identificacion": "cedula",
            "numero_identificacion": "1234567", "contacto": {"telefono": "3000000000"}, "oncologo_id": 1,
        })
        assert r.status_code == 201, r.text

    monkeypatch.setattr(api_module, "SEMBRAR_DATOS_PRUEBA", True)
    with TestClient(api_module.app) as c:
        nombres = [p["nombre_completo"] for p in c.get("/pacientes", params={"oncologo_id": 1}).json()]
        assert nombres == ["Paciente Real"]


def test_medicacion_actual_crea_solo_sus_tablas():
    """tx_clinica lo inicializa sobre su propia base (historia_clinica_mock):
    no debe crear ahí las tablas de este módulo."""
    conn = db.conectar(":memory:")
    medicacion_actual.inicializar_schema(conn)

    tablas = {f[0] for f in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"medicacion_actual", "conciliacion_medicamentos"} <= tablas
    assert "pacientes" not in tablas

    conn.execute(
        "INSERT INTO medicacion_actual (paciente_id, medicamento, registrado_por, fecha_registro) "
        "VALUES (1, 'rifampicina', 9, '2026-09-13')"
    )
    assert medicacion_actual.listar_medicacion_activa(conn, 1) == ["rifampicina"]
    assert medicacion_actual.obtener_estado_conciliacion(conn, 1) == medicacion_actual.ESTADO_NO_REALIZADA
