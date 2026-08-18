from __future__ import annotations

import re
import unicodedata


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9+\- ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# Deterministic interpreter for the MVP. It can later be replaced by an LLM/NLU
# component without changing the repository or the patient-safety behavior.
CONCEPT_ALIASES: dict[str, tuple[str, ...]] = {
    "ca-125": ("ca-125", "ca125", "ca 125", "marcador ca 125", "marcador ca-125"),
    "hemoglobina": ("hemoglobina", "hb"),
    "creatinina": ("creatinina", "creatinine"),
    "leucocitos": ("leucocitos", "wbc", "leukocytes"),
    "plaquetas": ("plaquetas", "platelets"),
    "psa": ("psa", "antigeno prostatico", "antigeno prostatico especifico"),
    # Concepts present in historia_clinica_mock
    "her2": ("her2", "her 2"),
    "egfr": ("egfr", "receptor del factor de crecimiento epidermico"),
    "neutrofilos": ("neutrofilos", "neutrofilo", "neutrophils"),
    "alt": ("alt", "alanina aminotransferasa", "funcion hepatica"),
}


def detect_concept(question: str) -> str | None:
    normalized = normalize_text(question)
    padded = f" {normalized} "
    matches: list[tuple[int, str]] = []

    for concept, aliases in CONCEPT_ALIASES.items():
        for alias in aliases:
            normalized_alias = normalize_text(alias)
            if f" {normalized_alias} " in padded:
                matches.append((len(normalized_alias), concept))

    if not matches:
        return None

    matches.sort(reverse=True)
    return matches[0][1]
