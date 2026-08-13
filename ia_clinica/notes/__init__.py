"""Generación automática de borradores de notas clínicas (IA-02).

Como oncólogo, quiero que el sistema genere automáticamente un borrador
estructurado de nota clínica a partir de la información registrada durante
la consulta, para reducir el tiempo dedicado a la documentación clínica.

Reglas de negocio no negociables (ver backlog, historia IA-02):
    1. El resultado es *siempre* un borrador, nunca una nota clínica
       definitiva. No existe ninguna función en este módulo que lo marque
       como "oficial" — esa decisión pertenece a una historia posterior
       (firma/aprobación del oncólogo) fuera de este alcance.
    2. El contenido generado debe corresponder únicamente a información
       presente en el contexto clínico de la consulta. Nada se infiere ni
       se completa con conocimiento general del modelo.
    3. Si falta información para una sección, esa sección se marca
       explícitamente como no disponible; nunca se inventa un valor.

Componentes públicos:
    - :class:`ia_clinica.notes.models.ClinicalContext`
    - :class:`ia_clinica.notes.models.ClinicalNoteDraft`
    - :class:`ia_clinica.notes.formats.NoteFormatSpec` / ``SOAP_FORMAT``
    - :class:`ia_clinica.notes.llm_client.LLMClient` (interfaz) y
      :class:`ia_clinica.notes.llm_client.RuleBasedLLMClient` (implementación
      de referencia sin dependencias externas)
    - :class:`ia_clinica.notes.generator.ClinicalNoteGenerator`
"""

from ia_clinica.notes.generator import ClinicalNoteGenerator, GenerationError
from ia_clinica.notes.models import (
    MISSING_INFO_MARKER,
    ClinicalContext,
    ClinicalNoteDraft,
    NoteSectionDraft,
    SourceSpan,
    split_sentences,
)
from ia_clinica.notes.formats import NoteFormatSpec, NoteSectionSpec, SOAP_FORMAT, get_format

__all__ = [
    "ClinicalNoteGenerator",
    "GenerationError",
    "MISSING_INFO_MARKER",
    "ClinicalContext",
    "ClinicalNoteDraft",
    "NoteSectionDraft",
    "SourceSpan",
    "split_sentences",
    "NoteFormatSpec",
    "NoteSectionSpec",
    "SOAP_FORMAT",
    "get_format",
]
