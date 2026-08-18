from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class EvidenceDocument:
    module_id: str
    organization: str
    title: str
    publication_date: Optional[str]
    publication_year: Optional[int]
    doi: Optional[str]
    source_path: str
    clinical_scope: dict
    development_status: Optional[str]
    licensing_status: Optional[str]
    validation_status: Optional[str]


@dataclass(frozen=True)
class EvidenceSearchResult:
    document: EvidenceDocument
    score: int
    matched_terms: tuple[str, ...]
