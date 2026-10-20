"""Rutas de apoyo clínico de la interfaz (``/api/clinica``): notas de IA (IA-02/IA-03) y tratamiento (TX-01)."""
import pytest

from tests.frontend.conftest import H, LUCIA

BASE = f"/api/clinica/pacientes/{LUCIA}"


@pytest.fixture(autouse=True)
def sin_modelo(monkeypatch):
    """Sin llamadas a OpenAI: las notas salen del redactor por reglas."""
    from core import llm_config

    monkeypatch.setattr(llm_config, "obtener_api_key", lambda: None)


@pytest.fixture()
def medica(entrar):
    return entrar("dra.rios")


def _consulta(c):
    r = c.post(f"{BASE}/consultas-expediente", json={"motivo": "Control", "notas": "Refiere fatiga leve. Sin fiebre. Plan: TAC de control."}, headers=H)
    assert r.status_code == 200, r.text
    return c.get(f"{BASE}/consultas-expediente").json()[0]["id"]


def test_nota_borrador_editar_aprobar(medica):
    cid = _consulta(medica)
    r = medica.post(f"{BASE}/notas", json={"consulta_id": cid, "formato": "SOAP"}, headers=H)
    assert r.status_code == 200, r.text
    nota = r.json()["nota"]
    assert nota["estado"] == "DRAFT" and not nota["oficial"] and set("SOAP") <= set(nota["contenido_actual"])
    r = medica.put(f"{BASE}/notas/{nota['nota_id']}/secciones/A", json={"contenido": "Corregido por la médica."}, headers=H)
    assert r.status_code == 200 and r.json()["contenido_actual"]["A"] == "Corregido por la médica."
    r = medica.post(f"{BASE}/notas/{nota['nota_id']}/aprobar", json={}, headers=H)
    assert r.status_code == 200 and r.json()["estado"] == "APPROVED" and r.json()["oficial"]


def test_pedir_otra_nota_para_la_misma_consulta_se_explica_sin_error_500(medica):
    cid = _consulta(medica)
    assert medica.post(f"{BASE}/notas", json={"consulta_id": cid}, headers=H).status_code == 200
    r = medica.post(f"{BASE}/notas", json={"consulta_id": cid}, headers=H)
    assert r.status_code == 409 and "ya tiene un borrador" in r.text
    nota_id = medica.get(f"{BASE}/notas").json()[0]["nota_id"]
    medica.post(f"{BASE}/notas/{nota_id}/aprobar", json={}, headers=H)
    r = medica.post(f"{BASE}/notas", json={"consulta_id": cid}, headers=H)
    assert r.status_code == 409 and "aprobada" in r.text


def test_tratamiento_anuncia_que_los_biomarcadores_van_por_hc04(medica):
    r = medica.get(f"{BASE}/tratamiento")
    assert r.status_code == 200
    assert {"pdl1_tps", "egfr_status"} <= set(r.json()["biomarcadores"])


def test_un_dato_de_tratamiento_invalido_dice_cual_y_por_que(medica):
    r = medica.post(f"{BASE}/tratamiento/datos", json={"valores": {"pdl1_tps": 60, "treatment_line": "uno"}}, headers=H)
    assert r.status_code == 400
    errores = r.json()["detail"]["errores"]
    campos = {e["campo"] for e in errores}
    assert {"pdl1_tps", "treatment_line"} <= campos
    assert any("Biomarcadores y biopsias" in e["mensaje"] for e in errores)
