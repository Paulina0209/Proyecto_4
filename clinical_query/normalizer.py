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
    # Concepts present in expediente
    "her2": ("her2", "her 2"),
    "egfr": ("egfr", "receptor del factor de crecimiento epidermico"),
    "neutrofilos": ("neutrofilos", "neutrofilo", "neutrophils"),
    "alt": ("alt", "alanina aminotransferasa", "funcion hepatica"),
    # Marcadores tumorales y biomarcadores que trae cBioPortal (docs/cbioportal.md)
    "cea": ("cea", "antigeno carcinoembrionario"),
    "ca 15-3": ("ca 15-3", "ca15-3", "ca 15 3", "ca 153"),
    "ca 19-9": ("ca 19-9", "ca19-9", "ca 19 9", "ca 199"),
    "kras": ("kras",),
    "alk": ("alk",),
    "ros1": ("ros1",),
    "braf": ("braf",),
    "met": ("met",),
    "ret": ("ret",),
    "pik3ca": ("pik3ca",),
    "tmb": ("tmb", "carga mutacional", "carga mutacional tumoral"),
    "msi": ("msi", "inestabilidad de microsatelites"),
    "receptores hormonales": ("receptores hormonales", "receptor hormonal", "hr"),
}


def detect_concepts(question: str) -> list[str]:
    """Todos los conceptos clínicos distintos que la pregunta podría estar pidiendo.

    A diferencia de :func:`detect_concept`, no colapsa el resultado a uno solo:
    devuelve cada concepto que aparece mencionado, ordenado por la longitud de
    su mejor alias coincidente (el más específico primero). IA-06 necesita ver
    *todas* las interpretaciones posibles para poder pedir aclaración en vez de
    elegir una en silencio.
    """

    normalized = normalize_text(question)
    padded = f" {normalized} "
    mejor_por_concepto: dict[str, int] = {}

    for concept, aliases in CONCEPT_ALIASES.items():
        for alias in aliases:
            normalized_alias = normalize_text(alias)
            if f" {normalized_alias} " in padded:
                largo = len(normalized_alias)
                if largo > mejor_por_concepto.get(concept, 0):
                    mejor_por_concepto[concept] = largo

    return [
        concept
        for concept, _ in sorted(
            mejor_por_concepto.items(), key=lambda item: item[1], reverse=True
        )
    ]


def detect_concept(question: str) -> str | None:
    conceptos = detect_concepts(question)
    return conceptos[0] if conceptos else None
