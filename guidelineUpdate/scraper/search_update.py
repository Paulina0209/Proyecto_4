from datetime import datetime, timezone

import requests

from ..state import state_manager


ESMO_API_URL = "https://kontent.cdn.aws.esmo.org/rest/items"

ELEMENTS = (
    "title,"
    "version,"
    "last_update,"
    "publish_date,"
    "guideline_product"
)

GUIDELINE_PRODUCT_TYPES = (
    "esmo_clinical_practice_guideline,"
    "living_guideline,"
)

REQUEST_TIMEOUT = 60


class ESMOScraper:
    """Consulta las guidelines disponibles en ESMO y detecta cambios."""

    def __init__(self):
        self.session = requests.Session()

        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/150.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
            "Origin": "https://www.esmo.org",
            "Referer": "https://www.esmo.org/",
        })

    def fetch_guidelines(self):
        """Obtiene las publicaciones de tipo guideline desde ESMO."""

        params = {
            "includeTotalCount": "",
            "system.workflow_step[nin]": "archived",
            "limit": "2000",
            "depth": "2",
            "elements.guideline_product[any]": GUIDELINE_PRODUCT_TYPES,
            "order": "elements.last_update[desc]",
            "elements": ELEMENTS,
        }

        response = self.session.get(
            ESMO_API_URL,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        data = response.json()

        if not data.get("items"):
            raise RuntimeError(
                "ESMO no devolvió ninguna guideline. "
                "La respuesta puede haber cambiado o la API puede "
                "estar bloqueando la petición."
            )

        return data

    @staticmethod
    def get_value(element):
        """
        Extrae el valor de un elemento de Kontent.ai.
        """

        if not isinstance(element, dict):
            return element

        value = element.get("value")

        if value is None:
            return None

        # Taxonomías como guideline_product
        if element.get("type") == "taxonomy":
            if not isinstance(value, list):
                return value

            codenames = [
                item.get("codename")
                for item in value
                if isinstance(item, dict)
                and item.get("codename")
            ]

            if not codenames:
                return None

            return (
                codenames[0]
                if len(codenames) == 1
                else codenames
            )

        return value

    def normalize_guidelines(self, response):
        """
        Convierte la respuesta de ESMO a una lista simple.
        """

        guidelines = []

        for item in response.get("items", []):
            system = item.get("system", {})
            elements = item.get("elements", {})

            codename = system.get("codename")

            if not codename:
                continue

            guidelines.append({
                "codename": codename,
                "id": system.get("id"),
                "title": self.get_value(
                    elements.get("title")
                ),
                "version": self.get_value(
                    elements.get("version")
                ),
                "last_update": self.get_value(
                    elements.get("last_update")
                ),
                "publish_date": self.get_value(
                    elements.get("publish_date")
                ),
                "guideline_product": self.get_value(
                    elements.get("guideline_product")
                ),
            })

        return guidelines

    @staticmethod
    def normalize_text(value):
        """Normaliza texto para hacer matching básico."""

        if not value:
            return ""

        return " ".join(
            str(value).lower().split()
        )

    def match_source(self, source, guidelines):
        """
        Busca la guideline de ESMO correspondiente a una fuente.

        Prioridad:
        1. codename explícito en sources.yaml
        2. coincidencia exacta por nombre
        3. coincidencia mediante aliases
        """

        configured_codename = source.get("codename")

        if configured_codename:
            for guideline in guidelines:
                if guideline["codename"] == configured_codename:
                    return guideline, "matched_codename"

            return None, "configured_codename_not_found"

        name = self.normalize_text(source.get("name"))

        if not name:
            return None, "missing_name"

        aliases = [
            self.normalize_text(alias)
            for alias in source.get("aliases", [])
            if alias
        ]

        candidates = [name, *aliases]

        # Coincidencia exacta
        exact_matches = [
            guideline
            for guideline in guidelines
            if self.normalize_text(guideline.get("title")) in candidates
        ]

        if len(exact_matches) == 1:
            return exact_matches[0], "matched_name"

        # Coincidencia parcial conservadora
        partial_matches = []

        for guideline in guidelines:
            title = self.normalize_text(
                guideline.get("title")
            )

            if any(
                candidate in title or title in candidate
                for candidate in candidates
            ):
                partial_matches.append(guideline)

        if len(partial_matches) == 1:
            return partial_matches[0], "matched_name_partial"

        if len(partial_matches) > 1:
            return None, "ambiguous_match"

        return None, "not_found"
    
    def check_updates(self):
        """
        Revisa todas las fuentes configuradas.

        Devuelve únicamente los módulos que tienen una actualización
        real. La primera ejecución de un módulo nuevo fija la referencia
        inicial y no la reporta como actualización.
        """

        sources = state_manager.load_sources()

        remote_guidelines = self.normalize_guidelines(
            self.fetch_guidelines()
        )

        updates = []

        for source in sources:
            module_id = source.get("module_id")

            if not module_id:
                continue

            remote, match_status = self.match_source(
                source,
                remote_guidelines,
            )

            if remote is None:
                continue

            existing_state = state_manager.load_state(module_id)
            is_first_run = existing_state is None

            state = (
                existing_state
                or state_manager.create_state(module_id)
            )

            now = datetime.now(timezone.utc).isoformat()

            try:
                changed = state_manager.has_changed(
                    remote.get("last_update"),
                    state,
                )
            except ValueError:
                state["sync"]["last_checked_at"] = now
                state["sync"]["last_match_status"] = match_status

                state_manager.save_state(
                    module_id,
                    state,
                )

                continue

            state["sync"]["last_checked_at"] = now
            state["sync"]["last_match_status"] = match_status

            state["source"]["codename"] = remote.get("codename")
            state["source"]["guideline_type"] = remote.get(
                "guideline_product"
            )
            state["source"]["version"] = remote.get("version")
            state["source"]["publish_date"] = remote.get(
                "publish_date"
            )

            if changed and is_first_run:
                state["sync"]["last_known_update"] = (
                    remote.get("last_update")
                )
                state["sync"]["last_processed_publication_id"] = (
                    remote.get("id")
                )

            elif changed:
                updates.append(
                    {
                        "module_id": module_id,
                        "codename": remote["codename"],
                        "id": remote.get("id"),
                        "title": remote.get("title"),
                        "version": remote.get("version"),
                        "last_update": remote.get("last_update"),
                    }
                )

            else:
                state["sync"]["last_known_update"] = (
                    remote.get("last_update")
                )
                state["sync"]["last_processed_publication_id"] = (
                    remote.get("id")
                )

            state_manager.save_state(
                module_id,
                state,
            )

        return updates

def main():
    scraper = ESMOScraper()
    updates = scraper.check_updates()

    for update in updates:
        print(update["module_id"])


if __name__ == "__main__":
    main()