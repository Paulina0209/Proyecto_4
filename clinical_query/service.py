from __future__ import annotations

from dataclasses import dataclass

from .ambiguity import (
    AmbiguityFinding,
    ambiguedad_de_dato,
    ambiguedad_de_episodio,
    nombra_otro_paciente,
    tiene_calificador_temporal,
)
from .models import ClinicalDatum, QueryResponse
from .normalizer import detect_concepts
from .repository import ClinicalRepository


@dataclass(frozen=True)
class Clarification:
    """Aclaración que el oncólogo entrega tras una solicitud de IA-06.

    El servicio es sin estado: la conversación se reanuda pasando esta
    estructura junto con la misma pregunta original. Solo el contexto aclarado
    aquí (más el ``patient_id`` activo) se usa para recuperar información.
    """

    concept: str | None = None
    episode_id: str | None = None
    confirm_active_patient: bool = False


class NaturalLanguageClinicalQueryService:
    """IA-01 + IA-06: interpret -> detectar ambigüedad -> retrieve -> verify -> answer."""

    def __init__(self, repository: ClinicalRepository):
        self.repository = repository

    def ask(
        self,
        patient_id: str,
        question: str,
        *,
        clarification: Clarification | None = None,
    ) -> QueryResponse:
        clarification = clarification or Clarification()

        # 1. Ambigüedad de paciente. La recuperación SIEMPRE se acota a
        #    patient_id; aquí solo se decide si además hay que pedir aclaración
        #    porque la pregunta parece hablar de otra persona.
        if not clarification.confirm_active_patient:
            patient_finding = nombra_otro_paciente(
                question, self.repository.directorio_pacientes(), patient_id
            )
            if patient_finding is not None:
                return self._clarification_response(patient_finding)

        # 2. Ambigüedad de dato clínico.
        if clarification.concept is not None:
            concept = clarification.concept
        else:
            concepts = detect_concepts(question)
            data_finding = ambiguedad_de_dato(concepts)
            if data_finding is not None:
                return self._clarification_response(data_finding)
            if not concepts:
                return QueryResponse(
                    found=False,
                    answer=(
                        "No pude identificar de forma segura el dato clínico solicitado. "
                        "Especifica el dato que deseas consultar."
                    ),
                )
            concept = concepts[0]

        # 3. Recuperación (siempre precede a la generación de respuesta y
        #    siempre acotada al paciente activo).
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

        # 4. Ambigüedad de episodio: el dato existe en más de una consulta y la
        #    pregunta no acota a cuál.
        if clarification.episode_id is not None:
            matches = [m for m in matches if m.episode_id == clarification.episode_id]
            if not matches:
                return QueryResponse(
                    found=False,
                    concept=concept,
                    answer=(
                        f"No hay información de {concept} registrada en el episodio "
                        f"{clarification.episode_id} para el paciente activo."
                    ),
                )
        elif not tiene_calificador_temporal(question):
            episodios = sorted(
                {m.episode_id for m in matches if m.episode_id is not None}
            )
            if len(episodios) > 1:
                episode_finding = ambiguedad_de_episodio(
                    self._resumen_por_episodio(matches, episodios)
                )
                if episode_finding is not None:
                    return self._clarification_response(episode_finding)

        # 5. Respuesta: un único dato resuelto, con su provenencia.
        datum = max(matches, key=lambda item: item.observed_at)
        date_text = datum.observed_at.strftime("%Y-%m-%d")
        contexto = f" (episodio {datum.episode_id})" if datum.episode_id else ""
        answer = (
            f"El valor más reciente de {concept} es {datum.display_value}, "
            f"registrado el {date_text}{contexto}. "
            f"Fuente: {datum.source} (ID: {datum.source_id})."
        )

        return QueryResponse(found=True, concept=concept, datum=datum, answer=answer)

    @staticmethod
    def _resumen_por_episodio(
        matches: list[ClinicalDatum], episodios: list[str]
    ) -> list[str]:
        resumenes: list[str] = []
        for episode_id in episodios:
            del_episodio = [m for m in matches if m.episode_id == episode_id]
            datum = max(del_episodio, key=lambda item: item.observed_at)
            resumenes.append(
                f"{episode_id} — {datum.display_value} "
                f"({datum.observed_at.strftime('%Y-%m-%d')})"
            )
        return resumenes

    @staticmethod
    def _clarification_response(finding: AmbiguityFinding) -> QueryResponse:
        cuerpo = finding.message
        if finding.options:
            cuerpo += " Opciones: " + "; ".join(finding.options) + "."
        return QueryResponse(
            found=False,
            answer=cuerpo,
            needs_clarification=True,
            ambiguities=(finding,),
        )
