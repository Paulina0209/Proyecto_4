from datetime import datetime
from pathlib import Path

import yaml


STATE_DIR = Path(__file__).resolve().parent
STATE_DATA_DIR = STATE_DIR / "data"
SOURCES_FILE = STATE_DIR.parent / "sources.yaml"


def load_sources():
    """Carga las fuentes configuradas en sources.yaml."""

    if not SOURCES_FILE.exists():
        raise FileNotFoundError(
            f"No se encontró sources.yaml: {SOURCES_FILE}"
        )

    with SOURCES_FILE.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    sources = data.get("sources", [])

    if not isinstance(sources, list):
        raise ValueError(
            "sources.yaml debe contener una lista bajo 'sources'."
        )

    return sources


def load_state(module_id):
    """
    Carga el estado de un módulo.

    Devuelve None si todavía no existe su archivo.
    """

    state_file = STATE_DATA_DIR / f"{module_id}.yaml"

    if not state_file.exists():
        return None

    with state_file.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def create_state(module_id):
    """Crea el estado inicial de un módulo."""

    return {
        "module_id": module_id,
        "source": {
            "codename": None,
            "guideline_type": None,
            "version": None,
            "publish_date": None,
            "doi": None,
            "epub_date": None,
        },
        "sync": {
            "last_checked_at": None,
            "last_known_update": None,
            "last_processed_publication_id": None,
            "last_match_status": None,
        },
    }


def save_state(module_id, state):
    """Guarda el estado de un módulo."""

    STATE_DATA_DIR.mkdir(parents=True, exist_ok=True)

    state_file = STATE_DATA_DIR / f"{module_id}.yaml"

    with state_file.open("w", encoding="utf-8") as file:
        yaml.safe_dump(
            state,
            file,
            sort_keys=False,
            allow_unicode=True,
        )


def parse_date(value):
    """
    Convierte una fecha ISO 8601 a datetime.

    Ejemplos aceptados:
        2026-08-07T06:30:00Z
        2026-08-07T06:30:00+00:00
    """

    if not value:
        return None

    if isinstance(value, datetime):
        return value

    try:
        return datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    except ValueError:
        return None


def has_changed(remote_last_update, state):
    """
    Determina si la fuente tiene una actualización posterior
    a la última actualización procesada localmente.

    Importante:
    - last_checked_at NO se usa para comparar versiones.
    - last_known_update representa la última actualización
      que el sistema ya procesó.
    """

    remote_date = parse_date(remote_last_update)

    if remote_date is None:
        raise ValueError(
            "No se pudo interpretar la fecha remota: "
            f"{remote_last_update!r}"
        )

    if not state:
        return True

    last_known_update = state.get("sync", {}).get(
        "last_known_update"
    )

    if not last_known_update:
        return True

    local_date = parse_date(last_known_update)

    if local_date is None:
        raise ValueError(
            "No se pudo interpretar sync.last_known_update: "
            f"{last_known_update!r}"
        )

    return remote_date > local_date

def mark_processed(module_id, last_update, publication_id):
    """
    Marca una version como procesada (descargada + con intento de
    analisis por el agente) actualizando last_known_update.

    IMPORTANTE: esto NO es aprobacion clinica. Solo evita que la
    proxima corrida vuelva a tratar esta misma version como una
    actualizacion nueva. La aprobacion clinica sigue siendo un paso
    humano separado, sobre la propuesta guardada en updates/.
    """

    state = load_state(module_id)

    if state is None:
        return

    state["sync"]["last_known_update"] = last_update
    state["sync"]["last_processed_publication_id"] = publication_id

    save_state(module_id, state)