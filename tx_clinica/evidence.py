"""TX-02 — Nivel de evidencia y fuente exacta por recomendación de tratamiento.

dx_clinica/evidence.py ya resuelve esto a nivel de módulo (metadata.yaml:
organización, título, año, DOI, estado de validación). TX-02 necesita ser
más específico: el evidence_level / recommendation_grade / MCBS de la
REGLA concreta que se disparó, no solo la guía general del módulo. Esos
campos viven dentro de cada regla (`evidence.native.*`), no en
metadata.yaml, así que no se puede resolver reusando dx_clinica/evidence.py
tal cual — se lee el archivo de regla directamente, igual que ese módulo
ya lee YAML crudo con yaml.safe_load para lo suyo.

No se modifica dx_clinica/evidence.py. Este archivo es nuevo, en
tx_clinica, y sigue exactamente el mismo principio: nada se inventa en
tiempo de ejecución, todo sale de YAML ya versionado en guidelines/.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

from tx_clinica.models import TreatmentEvidenceReference


def _leer_yaml(path: Path) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8-sig") as f:
        return yaml.safe_load(f)


def _estado_validacion_clinica(metadata: dict[str, Any]) -> Optional[str]:
    validation = metadata.get("validation") or {}
    # Igual que dx_clinica/evidence.py: soporta ambas llaves observadas
    # en distintos metadata.yaml del repo, sin asumir una sola forma.
    return validation.get("clinical_validation_status") or validation.get("clinical")


def _buscar_regla_por_id(rule_file: Path, rule_id: str) -> Optional[dict[str, Any]]:
    payload = _leer_yaml(rule_file)
    if not payload or not isinstance(payload.get("rules"), list):
        return None
    for regla in payload["rules"]:
        if regla.get("id") == rule_id:
            return regla
    return None


def obtener_evidencia_regla(
    module_folder: Path,
    archivo_regla: str,
    rule_id: str,
) -> Optional[TreatmentEvidenceReference]:
    """Construye la referencia de evidencia de una regla concreta ya disparada.

    Devuelve None si el módulo o la regla no existen — nunca se inventa
    una referencia parcial ni se rellena con valores por defecto que
    aparenten venir de la guía.
    """
    metadata = _leer_yaml(module_folder / "metadata.yaml")
    if metadata is None:
        return None

    regla = _buscar_regla_por_id(module_folder / archivo_regla, rule_id)
    if regla is None:
        return None

    evidence = regla.get("evidence") or {}
    native = evidence.get("native") or {}
    mcbs = native.get("mcbs") or {}
    source = regla.get("source") or {}
    metadata_source = metadata.get("source") or {}

    return TreatmentEvidenceReference(
        module_id=metadata.get("module_id", module_folder.name),
        organization=source.get("organization") or evidence.get("organization") or metadata.get("organization", "organización no especificada"),
        title=source.get("title") or metadata_source.get("title"),
        publication_year=source.get("publication_year") or metadata_source.get("publication_year"),
        doi=source.get("doi") or metadata_source.get("doi"),
        section=source.get("section"),
        module_version=metadata.get("module_version"),
        clinical_validation_status=_estado_validacion_clinica(metadata),
        evidence_level=native.get("evidence_level"),
        recommendation_grade=native.get("recommendation_grade"),
        mcbs_score=mcbs.get("score"),
        explicit_grade_reported=bool(evidence.get("explicit_grade_reported", False)),
        ruta_metadata=str(module_folder / "metadata.yaml"),
        ruta_regla=str(module_folder / archivo_regla),
    )
