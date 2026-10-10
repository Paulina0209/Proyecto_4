"""API de HC-03 (imágenes diagnósticas del PACS): AC1 y AC2 de punta a punta.
El PACS es un doble inyectado en ``api_module.PACS_FUENTE``."""
from __future__ import annotations

import pytest

import patients.api as api_module
from historia_clinica.imagenes_pacs import EstudioDICOM
from historia_clinica.db import conectar_expediente

ONC = {"oncologo_id": 1}
MARIA = 1  # María Gómez, cédula 91000001, del oncólogo 1
DE_OTRO_ONCOLOGO = 10
UID = "1.2.840.113619.2.55.3.604688119.969.1268071829.6"
VISOR = "https://visor.hospital.example/viewer?StudyInstanceUIDs={study_uid}"


class _Pacs:
    nombre = "PACS-Prueba"

    def __init__(self, estudios=None, error=None):
        self.estudios, self.error = estudios or [], error

    def buscar_estudios(self, identificacion):
        if self.error:
            raise self.error
        return self.estudios


def _estudio(**cambios):
    datos = dict(study_uid=UID, patient_id="91000001", patient_name="Gómez^María", fecha="2026-03-10",
                 modalidad="CT", descripcion="TC de tórax", series=4, instancias=300)
    datos.update(cambios)
    return EstudioDICOM(**datos)


@pytest.fixture()
def api(client_con_datos, monkeypatch):
    monkeypatch.setattr(api_module, "VISOR_PLANTILLA", VISOR)
    monkeypatch.setattr(api_module, "PACS_FUENTE", None)
    return client_con_datos


def _pacs(monkeypatch, **kw):
    monkeypatch.setattr(api_module, "PACS_FUENTE", _Pacs(**kw))


def test_ac1_el_expediente_lista_el_estudio_con_su_enlace_al_visor(api, monkeypatch):
    _pacs(monkeypatch, estudios=[_estudio()])

    r = api.get(f"/pacientes/{MARIA}/imagenes", params=ONC)

    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["integracion_disponible"] is True and cuerpo["mensaje"] == ""
    (estudio,) = cuerpo["estudios"]
    assert estudio["study_uid"] == UID
    assert estudio["visor_url"] == VISOR.replace("{study_uid}", UID)


def test_ac1_el_informe_del_expediente_se_muestra_junto_al_estudio(api, monkeypatch):
    _pacs(monkeypatch, estudios=[_estudio()])
    api.get(f"/pacientes/{MARIA}/imagenes", params=ONC)  # crea al paciente en el expediente
    exp = conectar_expediente(api_module._ruta_expediente())
    pid = exp.execute("SELECT id FROM pacientes WHERE identificacion = '91000001'").fetchone()[0]
    exp.execute("INSERT INTO imagenologia (paciente_id, fecha, modalidad, region, hallazgos) VALUES (?,?,?,?,?)",
                (pid, "2026-03-10", "Tomografía", "tórax", "Nódulo de 8 mm en LID."))
    exp.commit()
    exp.close()

    (estudio,) = api.get(f"/pacientes/{MARIA}/imagenes", params=ONC).json()["estudios"]

    assert estudio["informe"]["texto"] == "Nódulo de 8 mm en LID."


def test_ac2_el_visor_responde_503_con_el_motivo_cuando_el_pacs_no_responde(api, monkeypatch):
    _pacs(monkeypatch, error=ConnectionError("conexión rechazada"))

    r = api.get(f"/pacientes/{MARIA}/imagenes/{UID}/visor", params=ONC)

    assert r.status_code == 503
    assert "integración con el PACS no está disponible" in r.json()["mensaje"]
    assert "conexión rechazada" in r.json()["mensaje"]


def test_ac2_el_listado_avisa_sin_fallar_y_el_fallo_queda_en_la_bitacora(api, monkeypatch):
    _pacs(monkeypatch, error=TimeoutError("tiempo agotado"))

    r = api.get(f"/pacientes/{MARIA}/imagenes", params=ONC)

    assert r.status_code == 200
    assert r.json()["integracion_disponible"] is False
    assert "no está disponible" in r.json()["mensaje"]
    (consulta,) = api.get(f"/pacientes/{MARIA}/imagenes/consultas", params=ONC).json()
    assert consulta["estado"] == "fallida" and "tiempo agotado" in consulta["mensaje"]


def test_ac2_sin_pacs_configurado_tambien_se_informa(api, monkeypatch):
    monkeypatch.delenv("COPILOTO_PACS_URL", raising=False)

    r = api.get(f"/pacientes/{MARIA}/imagenes", params=ONC)

    assert r.status_code == 200
    assert r.json()["integracion_disponible"] is False
    assert "no hay un PACS configurado" in r.json()["mensaje"]
    assert api.get(f"/pacientes/{MARIA}/imagenes/{UID}/visor", params=ONC).status_code == 503


def test_abrir_el_visor_con_pacs_disponible(api, monkeypatch):
    _pacs(monkeypatch, estudios=[_estudio()])

    r = api.get(f"/pacientes/{MARIA}/imagenes/{UID}/visor", params=ONC)

    assert r.status_code == 200, r.text
    assert r.json()["url"] == VISOR.replace("{study_uid}", UID)


def test_estudio_de_otro_paciente_nunca_se_muestra(api, monkeypatch):
    _pacs(monkeypatch, estudios=[_estudio(patient_id="99999999", patient_name="Pérez^Juan Carlos")])

    assert api.get(f"/pacientes/{MARIA}/imagenes", params=ONC).json()["estudios"] == []
    assert api.get(f"/pacientes/{MARIA}/imagenes/{UID}/visor", params=ONC).status_code == 503


def test_paciente_de_otro_oncologo_es_404(api, monkeypatch):
    _pacs(monkeypatch, estudios=[_estudio()])

    assert api.get(f"/pacientes/{DE_OTRO_ONCOLOGO}/imagenes", params=ONC).status_code == 404
    assert api.get(f"/pacientes/{DE_OTRO_ONCOLOGO}/imagenes/{UID}/visor", params=ONC).status_code == 404


def test_con_usuario_id_el_acceso_a_las_imagenes_queda_auditado(api, monkeypatch):
    _pacs(monkeypatch, estudios=[_estudio()])
    api.get(f"/pacientes/{MARIA}/imagenes", params={**ONC, "usuario_id": 7})

    conn = api_module.db.conectar(api_module.DB_PATH)
    filas = conn.execute("SELECT usuario_id, accion, detalle FROM eventos_acceso WHERE paciente_id = ?", (MARIA,)).fetchall()
    conn.close()
    assert [(f[0], f[1], f[2]) for f in filas] == [(7, "ver", "imagenes_pacs")]
