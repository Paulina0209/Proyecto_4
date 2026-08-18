"""Pruebas de ESMOScraper.

Cubren cuatro responsabilidades del scraper:

AC1: fetch_guidelines obtiene y valida la respuesta cruda de la API de ESMO.
AC2: get_value / normalize_guidelines / normalize_text transforman la
     respuesta de Kontent.ai a estructuras planas y comparables.
AC3: match_source resuelve, con prioridad explícita, qué guideline remota
     corresponde a una fuente configurada en sources.yaml.
AC4: check_updates orquesta todo lo anterior contra el estado persistido y
     decide qué módulos reportar como "con actualización real".

Se usa un `state_manager` de doble (via monkeypatch) para que las pruebas
sean deterministas y no dependan de disco ni de red. La sesión HTTP también
se sustituye por un mock, así que no se realiza ninguna petición real.

Rutas reales del paquete (guidelineUpdate/):
    guidelineUpdate/scraper/search_update.py
    guidelineUpdate/state/state_manager.py
"""

import pytest
import requests

import guidelineUpdate.scraper.search_update as esmo_module
from guidelineUpdate.scraper.search_update import ESMOScraper


# ---------------------------------------------------------------------------
# Dobles y fixtures
# ---------------------------------------------------------------------------
class FakeStateManager:
    """Doble en memoria de state_manager, con la misma interfaz usada por esmo.py."""

    def __init__(self):
        self.sources = []
        self.states = {}
        self.saved_states = {}
        self.has_changed_result = True
        self.has_changed_raises = False

    # -- API esperada por ESMOScraper --------------------------------------
    def load_sources(self):
        return self.sources

    def load_state(self, module_id):
        return self.states.get(module_id)

    def create_state(self, module_id):
        return {"sync": {}, "source": {}}

    def has_changed(self, remote_last_update, state):
        if self.has_changed_raises:
            raise ValueError("formato de fecha inválido")
        return self.has_changed_result

    def save_state(self, module_id, state):
        self.saved_states[module_id] = state


class FakeResponse:
    """Doble mínimo de requests.Response."""

    def __init__(self, json_data, status_error=None):
        self._json_data = json_data
        self._status_error = status_error

    def raise_for_status(self):
        if self._status_error is not None:
            raise self._status_error

    def json(self):
        return self._json_data


@pytest.fixture
def fake_state_manager(monkeypatch):
    fake = FakeStateManager()
    monkeypatch.setattr(esmo_module, "state_manager", fake)
    return fake


@pytest.fixture
def scraper():
    return ESMOScraper()


def guideline_item(codename, title, last_update="2024-01-01T00:00:00Z",
                    version="1.0", publish_date="2023-12-01T00:00:00Z",
                    guideline_product_codenames=("esmo_clinical_practice_guideline",),
                    item_id="id-1"):
    """Construye un item crudo con la forma que devuelve la API de Kontent.ai."""

    taxonomy_value = [{"codename": c} for c in guideline_product_codenames]

    return {
        "system": {"codename": codename, "id": item_id},
        "elements": {
            "title": {"value": title},
            "version": {"value": version},
            "last_update": {"value": last_update},
            "publish_date": {"value": publish_date},
            "guideline_product": {"type": "taxonomy", "value": taxonomy_value},
        },
    }


# ---------------------------------------------------------------------------
# AC1 — fetch_guidelines obtiene y valida la respuesta de la API.
# ---------------------------------------------------------------------------
class TestFetchGuidelines:
    def test_fetch_guidelines_retorna_la_data_cuando_hay_items(self, scraper, monkeypatch):
        payload = {"items": [guideline_item("breast-cancer", "Breast Cancer Guideline")]}
        monkeypatch.setattr(scraper.session, "get", lambda *a, **k: FakeResponse(payload))

        data = scraper.fetch_guidelines()

        assert data == payload

    def test_fetch_guidelines_llama_a_la_url_y_parametros_esperados(self, scraper, monkeypatch):
        captured = {}

        def fake_get(url, params=None, timeout=None):
            captured["url"] = url
            captured["params"] = params
            captured["timeout"] = timeout
            return FakeResponse({"items": [guideline_item("x", "X")]})

        monkeypatch.setattr(scraper.session, "get", fake_get)

        scraper.fetch_guidelines()

        assert captured["url"] == esmo_module.ESMO_API_URL
        assert captured["timeout"] == esmo_module.REQUEST_TIMEOUT
        assert captured["params"]["system.workflow_step[nin]"] == "archived"
        assert captured["params"]["order"] == "elements.last_update[desc]"
        assert "guideline_product" in captured["params"]["elements.guideline_product[any]"] \
            or captured["params"]["elements.guideline_product[any]"] == esmo_module.GUIDELINE_PRODUCT_TYPES

    def test_fetch_guidelines_lanza_error_explicito_si_no_hay_items(self, scraper, monkeypatch):
        monkeypatch.setattr(scraper.session, "get", lambda *a, **k: FakeResponse({"items": []}))

        with pytest.raises(RuntimeError):
            scraper.fetch_guidelines()

    def test_fetch_guidelines_lanza_error_explicito_si_falta_la_clave_items(self, scraper, monkeypatch):
        monkeypatch.setattr(scraper.session, "get", lambda *a, **k: FakeResponse({}))

        with pytest.raises(RuntimeError):
            scraper.fetch_guidelines()

    def test_fetch_guidelines_propaga_errores_http(self, scraper, monkeypatch):
        error_response = FakeResponse({}, status_error=requests.HTTPError("500"))
        monkeypatch.setattr(scraper.session, "get", lambda *a, **k: error_response)

        with pytest.raises(requests.HTTPError):
            scraper.fetch_guidelines()


# ---------------------------------------------------------------------------
# AC2 — get_value / normalize_guidelines / normalize_text.
# ---------------------------------------------------------------------------
class TestGetValue:
    def test_get_value_retorna_el_elemento_tal_cual_si_no_es_dict(self, scraper):
        assert scraper.get_value("texto_plano") == "texto_plano"
        assert scraper.get_value(None) is None

    def test_get_value_retorna_none_si_no_hay_value(self, scraper):
        assert scraper.get_value({"type": "text"}) is None

    def test_get_value_retorna_el_valor_directo_para_elementos_no_taxonomy(self, scraper):
        assert scraper.get_value({"type": "text", "value": "1.4"}) == "1.4"

    def test_get_value_taxonomy_con_un_solo_codename_retorna_string(self, scraper):
        element = {"type": "taxonomy", "value": [{"codename": "eupdate"}]}
        assert scraper.get_value(element) == "eupdate"

    def test_get_value_taxonomy_con_varios_codenames_retorna_lista(self, scraper):
        element = {
            "type": "taxonomy",
            "value": [{"codename": "eupdate"}, {"codename": "living_guideline"}],
        }
        assert scraper.get_value(element) == ["eupdate", "living_guideline"]

    def test_get_value_taxonomy_sin_codenames_validos_retorna_none(self, scraper):
        element = {"type": "taxonomy", "value": [{"otra_clave": "x"}, {}]}
        assert scraper.get_value(element) is None

    def test_get_value_taxonomy_con_value_no_lista_retorna_value_tal_cual(self, scraper):
        element = {"type": "taxonomy", "value": "no-es-lista"}
        assert scraper.get_value(element) == "no-es-lista"


class TestNormalizeGuidelines:
    def test_normalize_guidelines_extrae_los_campos_esperados(self, scraper):
        response = {
            "items": [
                guideline_item(
                    "breast-cancer",
                    "Breast Cancer Guideline",
                    last_update="2024-05-01T00:00:00Z",
                    version="2.1",
                    publish_date="2023-01-01T00:00:00Z",
                    guideline_product_codenames=("living_guideline",),
                    item_id="item-1",
                )
            ]
        }

        guidelines = scraper.normalize_guidelines(response)

        assert len(guidelines) == 1
        guideline = guidelines[0]
        assert guideline["codename"] == "breast-cancer"
        assert guideline["id"] == "item-1"
        assert guideline["title"] == "Breast Cancer Guideline"
        assert guideline["version"] == "2.1"
        assert guideline["last_update"] == "2024-05-01T00:00:00Z"
        assert guideline["publish_date"] == "2023-01-01T00:00:00Z"
        assert guideline["guideline_product"] == "living_guideline"

    def test_normalize_guidelines_ignora_items_sin_codename(self, scraper):
        item_sin_codename = guideline_item("x", "X")
        item_sin_codename["system"] = {"id": "sin-codename"}

        response = {"items": [item_sin_codename]}

        assert scraper.normalize_guidelines(response) == []

    def test_normalize_guidelines_retorna_lista_vacia_si_no_hay_items(self, scraper):
        assert scraper.normalize_guidelines({}) == []


class TestNormalizeText:
    def test_normalize_text_pasa_a_minusculas_y_colapsa_espacios(self, scraper):
        assert scraper.normalize_text("  Breast   CANCER  Guideline ") == "breast cancer guideline"

    def test_normalize_text_valores_vacios_retornan_cadena_vacia(self, scraper):
        assert scraper.normalize_text(None) == ""
        assert scraper.normalize_text("") == ""


# ---------------------------------------------------------------------------
# AC3 — match_source: prioridad codename > nombre exacto > alias/parcial.
# ---------------------------------------------------------------------------
@pytest.fixture
def remote_guidelines():
    return [
        {"codename": "breast-cancer", "title": "Breast Cancer"},
        {"codename": "lung-cancer", "title": "Lung Cancer"},
        {"codename": "lung-cancer-early", "title": "Early Lung Cancer"},
    ]


class TestMatchSource:
    def test_prioriza_codename_configurado_sobre_el_nombre(self, scraper, remote_guidelines):
        source = {"codename": "lung-cancer", "name": "Breast Cancer"}

        guideline, status = scraper.match_source(source, remote_guidelines)

        assert guideline["codename"] == "lung-cancer"
        assert status == "matched_codename"

    def test_codename_configurado_no_encontrado_no_hace_fallback_al_nombre(self, scraper, remote_guidelines):
        source = {"codename": "no-existe", "name": "Breast Cancer"}

        guideline, status = scraper.match_source(source, remote_guidelines)

        assert guideline is None
        assert status == "configured_codename_not_found"

    def test_coincidencia_exacta_por_nombre(self, scraper, remote_guidelines):
        source = {"name": "Breast Cancer"}

        guideline, status = scraper.match_source(source, remote_guidelines)

        assert guideline["codename"] == "breast-cancer"
        assert status == "matched_name"

    def test_coincidencia_por_alias_cuando_el_nombre_principal_no_matchea(self, scraper, remote_guidelines):
        source = {"name": "Cáncer de Mama", "aliases": ["Breast Cancer"]}

        guideline, status = scraper.match_source(source, remote_guidelines)

        assert guideline["codename"] == "breast-cancer"
        assert status == "matched_name"

    def test_coincidencia_parcial_unica(self, scraper, remote_guidelines):
        source = {"name": "Breast"}

        guideline, status = scraper.match_source(source, remote_guidelines)

        assert guideline["codename"] == "breast-cancer"
        assert status == "matched_name_partial"

    def test_match_ambiguo_cuando_hay_mas_de_una_coincidencia_parcial(self, scraper, remote_guidelines):
        # "Cancer" es substring de los tres títulos de la fixture, pero no
        # es exactamente igual a ninguno, así que nunca entra por la rama
        # de coincidencia exacta: cae directo en la parcial, con 3 matches.
        source = {"name": "Cancer"}

        guideline, status = scraper.match_source(source, remote_guidelines)

        assert guideline is None
        assert status == "ambiguous_match"

    def test_no_encontrado_cuando_no_hay_ninguna_coincidencia(self, scraper, remote_guidelines):
        source = {"name": "Prostate Cancer"}

        guideline, status = scraper.match_source(source, remote_guidelines)

        assert guideline is None
        assert status == "not_found"

    def test_falta_nombre_y_no_hay_codename(self, scraper, remote_guidelines):
        guideline, status = scraper.match_source({}, remote_guidelines)

        assert guideline is None
        assert status == "missing_name"


# ---------------------------------------------------------------------------
# AC4 — check_updates: orquestación completa contra el estado persistido.
# ---------------------------------------------------------------------------
class TestCheckUpdates:
    def _mock_fetch(self, scraper, monkeypatch, items):
        monkeypatch.setattr(scraper.session, "get", lambda *a, **k: FakeResponse({"items": items}))

    def test_primera_ejecucion_de_un_modulo_nuevo_no_se_reporta_como_actualizacion(
        self, scraper, monkeypatch, fake_state_manager
    ):
        fake_state_manager.sources = [{"module_id": "mod-1", "codename": "breast-cancer"}]
        fake_state_manager.states = {}  # no hay estado previo -> primera ejecución
        fake_state_manager.has_changed_result = True

        self._mock_fetch(scraper, monkeypatch, [guideline_item("breast-cancer", "Breast Cancer")])

        updates = scraper.check_updates()

        assert updates == []
        saved = fake_state_manager.saved_states["mod-1"]
        assert saved["sync"]["last_known_update"] is not None

    def test_reporta_actualizacion_cuando_cambia_y_no_es_la_primera_ejecucion(
        self, scraper, monkeypatch, fake_state_manager
    ):
        fake_state_manager.sources = [{"module_id": "mod-1", "codename": "breast-cancer"}]
        fake_state_manager.states = {"mod-1": {"sync": {}, "source": {}}}  # ya existía
        fake_state_manager.has_changed_result = True

        self._mock_fetch(scraper, monkeypatch, [guideline_item("breast-cancer", "Breast Cancer")])

        updates = scraper.check_updates()

        assert len(updates) == 1
        assert updates[0]["module_id"] == "mod-1"
        assert updates[0]["codename"] == "breast-cancer"

    def test_no_reporta_nada_si_no_hay_cambio(self, scraper, monkeypatch, fake_state_manager):
        fake_state_manager.sources = [{"module_id": "mod-1", "codename": "breast-cancer"}]
        fake_state_manager.states = {"mod-1": {"sync": {}, "source": {}}}
        fake_state_manager.has_changed_result = False

        self._mock_fetch(scraper, monkeypatch, [guideline_item("breast-cancer", "Breast Cancer")])

        updates = scraper.check_updates()

        assert updates == []
        saved = fake_state_manager.saved_states["mod-1"]
        assert saved["sync"]["last_known_update"] is not None

    def test_ignora_sources_sin_module_id(self, scraper, monkeypatch, fake_state_manager):
        fake_state_manager.sources = [{"codename": "breast-cancer"}]  # sin module_id

        self._mock_fetch(scraper, monkeypatch, [guideline_item("breast-cancer", "Breast Cancer")])

        updates = scraper.check_updates()

        assert updates == []
        assert fake_state_manager.saved_states == {}

    def test_ignora_sources_sin_match_remoto(self, scraper, monkeypatch, fake_state_manager):
        fake_state_manager.sources = [{"module_id": "mod-1", "codename": "no-existe"}]

        self._mock_fetch(scraper, monkeypatch, [guideline_item("breast-cancer", "Breast Cancer")])

        updates = scraper.check_updates()

        assert updates == []
        assert "mod-1" not in fake_state_manager.saved_states

    def test_valueerror_de_has_changed_se_registra_pero_no_interrumpe_el_resto(
        self, scraper, monkeypatch, fake_state_manager
    ):
        fake_state_manager.sources = [
            {"module_id": "mod-fecha-invalida", "codename": "breast-cancer"},
            {"module_id": "mod-ok", "codename": "lung-cancer"},
        ]
        fake_state_manager.states = {
            "mod-fecha-invalida": {"sync": {}, "source": {}},
            "mod-ok": {"sync": {}, "source": {}},
        }
        fake_state_manager.has_changed_raises = True

        self._mock_fetch(
            scraper,
            monkeypatch,
            [
                guideline_item("breast-cancer", "Breast Cancer"),
                guideline_item("lung-cancer", "Lung Cancer"),
            ],
        )

        updates = scraper.check_updates()

        assert updates == []
        saved = fake_state_manager.saved_states["mod-fecha-invalida"]
        assert saved["sync"]["last_match_status"] == "matched_codename"
        # No debe tener last_known_update, porque se salió por el except antes de fijarlo
        assert "last_known_update" not in saved["sync"]

    def test_guarda_estado_actualizado_por_cada_source_procesada(self, scraper, monkeypatch, fake_state_manager):
        fake_state_manager.sources = [{"module_id": "mod-1", "codename": "breast-cancer"}]
        fake_state_manager.states = {"mod-1": {"sync": {}, "source": {}}}
        fake_state_manager.has_changed_result = True

        self._mock_fetch(
            scraper,
            monkeypatch,
            [guideline_item("breast-cancer", "Breast Cancer", version="3.0", publish_date="2024-02-02T00:00:00Z")],
        )

        scraper.check_updates()

        saved = fake_state_manager.saved_states["mod-1"]
        assert saved["source"]["codename"] == "breast-cancer"
        assert saved["source"]["version"] == "3.0"
        assert saved["source"]["publish_date"] == "2024-02-02T00:00:00Z"
        assert saved["sync"]["last_checked_at"] is not None