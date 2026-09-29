"""La única base de datos del módulo (patients/db): sin datos de ejemplo."""
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


def test_la_api_no_carga_datos_de_ejemplo_al_arrancar(tmp_path, monkeypatch):
    ruta = tmp_path / "pacientes_test.db"
    monkeypatch.setattr(api_module, "DB_PATH", ruta)

    with TestClient(api_module.app):
        pass
    assert _contar_pacientes(ruta) == 0


def test_un_paciente_registrado_persiste_al_reiniciar_la_api(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "DB_PATH", tmp_path / "pacientes_test.db")

    with TestClient(api_module.app) as c:
        r = c.post("/pacientes", json={
            "nombre_completo": "Paciente Real", "sexo": "otro", "tipo_identificacion": "cedula",
            "numero_identificacion": "1234567", "contacto": {"telefono": "3000000000"}, "oncologo_id": 1,
        })
        assert r.status_code == 201, r.text

    with TestClient(api_module.app) as c:
        nombres = [p["nombre_completo"] for p in c.get("/pacientes", params={"oncologo_id": 1}).json()]
        assert nombres == ["Paciente Real"]


def test_medicacion_actual_crea_solo_sus_tablas():
    """tx_clinica lo inicializa sobre su propia base (expediente):
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


def test_conciliacion_de_medicamentos():
    conn = db.conectar(":memory:")
    medicacion_actual.inicializar_schema(conn)

    assert medicacion_actual.registrar_conciliacion(conn, 1, ["rifampicina", "amiodarona"], 9, "2026-09-01") == \
        medicacion_actual.ESTADO_CON_MEDICACION_REGISTRADA
    assert sorted(medicacion_actual.listar_medicacion_activa(conn, 1)) == ["amiodarona", "rifampicina"]

    # Una nueva conciliación sin medicamentos cierra los anteriores (no los borra).
    assert medicacion_actual.registrar_conciliacion(conn, 1, [], 9, "2026-09-29") == \
        medicacion_actual.ESTADO_SIN_MEDICACION_CONCOMITANTE
    assert medicacion_actual.listar_medicacion_activa(conn, 1) == []
    assert conn.execute("SELECT COUNT(*) FROM medicacion_actual").fetchone()[0] == 2
    assert medicacion_actual.obtener_estado_conciliacion(conn, 1) == medicacion_actual.ESTADO_SIN_MEDICACION_CONCOMITANTE
