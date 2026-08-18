from __future__ import annotations

from .models import QueryResponse
from .normalizer import detect_concept
from .repository import ClinicalRepository


class NaturalLanguageClinicalQueryService:
    """IA-01 application service: interpret -> retrieve -> verify -> answer."""

    def __init__(self, repository: ClinicalRepository):
        self.repository = repository

    def ask(self, patient_id: str, question: str) -> QueryResponse:
        concept = detect_concept(question)

        if concept is None:
            return QueryResponse(
                found=False,
                answer=(
                    "No pude identificar de forma segura el dato clínico solicitado. "
                    "Especifica el dato que deseas consultar."
                ),
            )

        # Retrieval always precedes response generation.
        matches = self.repository.find_by_concept(patient_id, concept)

        if not matches:
            return QueryResponse(
                found=False,
                concept=concept,
                answer=(
                    f"No hay información de {concept} disponible en el expediente "
                    "del paciente activo. No se infirió ni se inventó ningún valor."
                ),
            )

        # A clinical value is never returned without its provenance object.
        datum = max(matches, key=lambda item: item.observed_at)
        date_text = datum.observed_at.strftime("%Y-%m-%d")
        answer = (
            f"El valor más reciente de {concept} es {datum.display_value}, "
            f"registrado el {date_text}. "
            f"Fuente: {datum.source} (ID: {datum.source_id})."
        )

        return QueryResponse(found=True, concept=concept, datum=datum, answer=answer)
