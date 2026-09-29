"""Natural-language clinical data query capability (IA-01) with ambiguity handling (IA-06)."""

from .ambiguity import AmbiguityFinding, AmbiguityKind, PacienteRef
from .models import ClinicalDatum, ClinicalRecord, QueryResponse
from .repository import ClinicalRepository, JsonClinicalRepository, SQLiteClinicalRepository
from .service import Clarification, NaturalLanguageClinicalQueryService

__all__ = [
    "ClinicalDatum",
    "ClinicalRecord",
    "QueryResponse",
    "ClinicalRepository",
    "JsonClinicalRepository",
    "SQLiteClinicalRepository",
    "NaturalLanguageClinicalQueryService",
    "Clarification",
    "AmbiguityFinding",
    "AmbiguityKind",
    "PacienteRef",
]
