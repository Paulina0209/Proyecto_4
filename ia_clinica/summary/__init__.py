"""Resumen clínico de caso para junta médica / interconsulta (IA-04).

Como oncólogo, quiero generar un resumen médico del caso completo, para
poder compartirlo durante juntas médicas o interconsultas con otros
especialistas.

Depende de IA-02 (``ia_clinica.notes``): reutiliza la misma interfaz
``LLMClient`` (y, por tanto, el mismo ``OllamaLLMClient`` ya configurado) y
el mismo patrón de no-alucinación (marcador fijo de información faltante,
descarte de contenido sin cita válida). A diferencia de IA-02, que razona
sobre una sola consulta, IA-04 combina *todo* el expediente disponible del
paciente (como ya hace DX-02 para el diagnóstico diferencial), porque un
resumen para junta médica necesita el caso completo, no un encuentro
aislado.

Reglas de negocio no negociables (ver backlog, historia IA-04):
    1. El resultado es siempre un documento generado por IA que requiere
       revisión del oncólogo antes de presentarse formalmente; no existe
       ninguna función en este módulo que lo marque como "oficial".
    2. "Diagnóstico" y "estadio" se toman directamente del expediente
       estructurado del paciente — nunca los redacta el modelo.
    3. "Tratamientos previos" y "estado actual" solo se completan si hay
       un fragmento real del expediente que los respalde; si no lo hay,
       la sección se marca explícitamente como faltante, nunca se infiere.
    4. Si el resumen queda con secciones faltantes, el documento lo indica
       de forma explícita y visible (criterio de aceptación AC2).

Componentes públicos:
    - :class:`ia_clinica.summary.models.CaseSummaryContext`
    - :class:`ia_clinica.summary.models.CaseSummary`
    - :class:`ia_clinica.summary.llm_client.RuleBasedSummaryLLMClient`
      (implementación de referencia sin dependencias externas)
    - :class:`ia_clinica.summary.generator.CaseSummaryGenerator`
"""

from ia_clinica.summary.generator import CaseSummaryGenerationError, CaseSummaryGenerator
from ia_clinica.summary.llm_client import RuleBasedSummaryLLMClient
from ia_clinica.summary.models import (
    AI_SUMMARY_DISCLAIMER,
    DIAGNOSTICO,
    ESTADIO,
    ESTADO_ACTUAL,
    MISSING_INFO_MARKER,
    ORDEN_SECCIONES,
    TRATAMIENTOS_PREVIOS,
    CaseSummary,
    CaseSummaryContext,
    CaseSummarySection,
)

__all__ = [
    "CaseSummaryGenerator",
    "CaseSummaryGenerationError",
    "RuleBasedSummaryLLMClient",
    "CaseSummaryContext",
    "CaseSummary",
    "CaseSummarySection",
    "AI_SUMMARY_DISCLAIMER",
    "MISSING_INFO_MARKER",
    "DIAGNOSTICO",
    "ESTADIO",
    "TRATAMIENTOS_PREVIOS",
    "ESTADO_ACTUAL",
    "ORDEN_SECCIONES",
]
