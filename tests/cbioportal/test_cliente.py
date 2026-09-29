"""Cliente HTTP de cBioPortal con una sesión falsa (sin red)."""

import pytest

from cbioportal import ClienteCBioPortal
from historia_clinica.integracion_externa import ErrorIntegracion


class _Respuesta:
    def __init__(self, status_code, cuerpo):
        self.status_code = status_code
        self._cuerpo = cuerpo

    def json(self):
        return self._cuerpo


class _SesionFalsa:
    def __init__(self, respuestas):
        self.respuestas = respuestas
        self.peticiones = []

    def _responder(self, metodo, url, **kwargs):
        self.peticiones.append((metodo, url, kwargs))
        ruta = url.split("/api", 1)[1]
        return self.respuestas[(metodo, ruta)]

    def get(self, url, **kwargs):
        return self._responder("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._responder("POST", url, **kwargs)


def _cliente(respuestas, **kwargs):
    sesion = _SesionFalsa(respuestas)
    return ClienteCBioPortal("https://www.cbioportal.org/api", session=sesion, **kwargs), sesion


def test_eventos_clinicos_se_reducen_a_tipo_dias_y_atributos():
    cliente, _ = _cliente({
        ("GET", "/studies/e/patients/p/clinical-events"): _Respuesta(200, [{
            "eventType": "Lab_Test", "startNumberOfDaysSinceDiagnosis": 12, "endNumberOfDaysSinceDiagnosis": None,
            "attributes": [{"key": "TEST", "value": "CEA"}, {"key": "RESULT", "value": "3.1"}],
        }])
    })
    assert cliente.eventos_clinicos("e", "p") == [
        {"tipo": "Lab_Test", "inicio": 12, "fin": None, "atributos": {"TEST": "CEA", "RESULT": "3.1"}}
    ]


def test_error_http_se_convierte_en_error_de_integracion():
    cliente, _ = _cliente({("GET", "/studies/e/patients/p/clinical-data"): _Respuesta(502, {})})
    with pytest.raises(ErrorIntegracion, match="HTTP 502"):
        cliente.datos_clinicos_paciente("e", "p")


def test_paciente_inexistente():
    cliente, _ = _cliente({("GET", "/studies/e/patients/nadie/samples"): _Respuesta(404, {})})
    with pytest.raises(ErrorIntegracion, match="no encontró"):
        cliente.muestras_de_paciente("e", "nadie")


def test_token_de_instancia_privada_va_en_la_cabecera():
    cliente, sesion = _cliente({("GET", "/studies/e"): _Respuesta(200, {"studyId": "e"})}, token="secreto")
    cliente.estudio("e")
    assert sesion.peticiones[0][2]["headers"]["Authorization"] == "Bearer secreto"


def test_mutaciones_traducen_entrez_a_simbolo():
    cliente, sesion = _cliente({
        ("POST", "/molecular-profiles/perfil/mutations/fetch"): _Respuesta(200, [
            {"sampleId": "s1", "entrezGeneId": 1956, "proteinChange": "L858R", "mutationType": "Missense_Mutation"}
        ])
    })
    assert cliente.mutaciones("perfil", ["s1"], {"EGFR": 1956}) == [
        {"muestra": "s1", "gen": "EGFR", "cambio_proteico": "L858R", "tipo": "Missense_Mutation"}
    ]
    assert sesion.peticiones[0][2]["json"] == {"sampleIds": ["s1"], "entrezGeneIds": [1956]}


def test_sin_muestras_no_llama_a_la_api():
    cliente, sesion = _cliente({})
    assert cliente.mutaciones("perfil", [], {"EGFR": 1956}) == []
    assert cliente.fusiones("perfil", ["s1"], {}) == []
    assert sesion.peticiones == []


def test_paneles_y_entrez_se_cachean():
    cliente, sesion = _cliente({
        ("GET", "/gene-panels/IMPACT341"): _Respuesta(200, {"genes": [{"hugoGeneSymbol": "EGFR"}]}),
        ("POST", "/genes/fetch"): _Respuesta(200, [{"hugoGeneSymbol": "EGFR", "entrezGeneId": 1956}]),
    })
    for _ in range(2):
        assert cliente.genes_de_panel("IMPACT341") == {"EGFR"}
        assert cliente.entrez_ids(["EGFR"]) == {"EGFR": 1956}
    assert len(sesion.peticiones) == 2
