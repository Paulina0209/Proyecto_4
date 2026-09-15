"""Construcción de prompts y cliente de referencia para el resumen de caso (IA-04).

Reutiliza la misma interfaz :class:`~ia_clinica.notes.llm_client.LLMClient`
que ya usan IA-02/IA-03 (``complete(system_prompt, user_prompt) -> str``):
el mismo servidor local de Ollama (``OllamaLLMClient``) sirve aquí sin
ningún cambio, solo con un prompt distinto. No se define un nuevo cliente
de Ollama para esta historia a propósito — sería duplicar exactamente el
mismo adaptador HTTP que ya existe y ya está probado.

Solo se le pide al modelo (real o de referencia) que redacte dos de las
cuatro secciones del resumen: "tratamientos previos" y "estado actual".
``diagnostico`` y ``estadio`` NUNCA se le piden al modelo: ya están
registrados tal cual en el expediente estructurado del paciente
(``pacientes.diagnostico_principal`` / ``pacientes.estadio``), así que
``ia_clinica.summary.generator`` los copia directamente, sin pasar por
ningún LLM. Esto es intencional: elimina cualquier riesgo de que el dato
clínico más consecuente de la junta médica (qué tiene el paciente y en qué
estadio) dependa de una redacción del modelo.
"""

from __future__ import annotations

import json
from typing import Sequence

from ia_clinica.notes.llm_client import LLMClient
from ia_clinica.summary.models import CaseSummaryContext, ESTADO_ACTUAL, TRATAMIENTOS_PREVIOS

#: Claves de sección que sí se le piden al modelo (ver docstring del módulo).
CLAVES_SECCION_DERIVADA = (TRATAMIENTOS_PREVIOS, ESTADO_ACTUAL)


def build_system_prompt() -> str:
    """Prompt de sistema con las reglas anti-alucinación del resumen de caso."""

    return (
        "Eres un asistente clínico que redacta un resumen ejecutivo de caso "
        "oncológico para presentarse en junta médica o interconsulta.\n"
        "Reglas obligatorias, sin excepción:\n"
        "1. Usa EXCLUSIVAMENTE la información contenida en los fragmentos del "
        "expediente que se te entregan (notas de consulta, laboratorios, "
        "imagenología, biomarcadores, de TODO el historial del paciente). No "
        "agregues datos clínicos, supuestos, ni conocimiento médico general "
        "que no esté explícito en esos fragmentos.\n"
        "2. Debes producir EXACTAMENTE dos secciones: "
        f'"{TRATAMIENTOS_PREVIOS}" (tratamientos oncológicos que el paciente '
        "ya recibió: quimioterapia, radioterapia, cirugía, etc., según lo "
        "documentado) y "
        f'"{ESTADO_ACTUAL}" (evolución y situación clínica más reciente del '
        "paciente según lo documentado). NO redactes diagnóstico ni estadio: "
        "esos datos se toman directamente del expediente estructurado, no de "
        "ti.\n"
        "3. Si no hay información suficiente en los fragmentos para una de "
        'esas dos secciones, no la completes: márcala con "status": "missing" '
        'y deja "content" vacío.\n'
        "4. Toda sección que sí completes debe listar en "
        '"source_span_ids" los identificadores de los fragmentos exactos '
        "que respaldan ese contenido. No cites fragmentos que no existan.\n"
        "5. Responde ÚNICAMENTE con un objeto JSON válido, sin texto "
        "adicional antes o después, con esta forma exacta:\n"
        '{"sections": [{"key": <clave_seccion>, "status": "documented"|"missing", '
        '"content": <texto o "">, "source_span_ids": [<ids>]}]}\n'
        f"Las claves de sección esperadas son: "
        f'"{TRATAMIENTOS_PREVIOS}", "{ESTADO_ACTUAL}".\n'
        "Este resultado es siempre un resumen que un oncólogo revisará antes "
        "de presentarlo formalmente; nunca es un documento definitivo."
    )


def build_user_prompt(context: CaseSummaryContext) -> str:
    fragments = [{"id": s.id, "origin": s.origin, "text": s.text} for s in context.segments]
    return json.dumps(
        {
            "patient_ref": context.patient_ref,
            "diagnostico_principal": context.diagnostico_principal,
            "estadio": context.estadio,
            "fragments": fragments,
        },
        ensure_ascii=False,
    )


class RuleBasedSummaryLLMClient(LLMClient):
    """Implementación de referencia sin proveedor externo ni red.

    Igual que ``ia_clinica.notes.llm_client.RuleBasedLLMClient``: no es un
    LLM real, es un clasificador léxico que asigna cada fragmento del
    expediente a "tratamientos_previos" o "estado_actual" según palabras
    clave, y copia el fragmento literalmente — por lo que cualquier salida
    que produce está garantizada como "grounded". Sirve de respaldo seguro
    cuando no hay un servidor Ollama disponible (ver ``demo.py``).
    """

    _KEYWORDS = {
        TRATAMIENTOS_PREVIOS: (
            "quimioterapia",
            "radioterapia",
            "cirugía",
            "cirugia",
            "resección",
            "reseccion",
            "tratamiento",
            "ciclo",
            "neoadyuvante",
            "adyuvante",
            "inmunoterapia",
            "terapia dirigida",
            "recibió",
            "recibio",
            "se inició",
            "se inicio",
        ),
        ESTADO_ACTUAL: (
            "actualmente",
            "se siente",
            "sentirse",
            "sin dolor",
            "reporta que",
            "continuar",
            "seguimiento",
            "control en",
            "controles clínicos",
            "controles clinicos",
            "evolución",
            "evolucion",
            "respuesta clínica",
            "respuesta clinica",
            "progresión",
            "progresion",
            "remisión",
            "remision",
            "retomó",
            "retomo",
        ),
    }

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        payload = json.loads(user_prompt)
        fragments = payload["fragments"]
        sections = []
        for key in CLAVES_SECCION_DERIVADA:
            keywords = self._KEYWORDS[key]
            matched = [f for f in fragments if self._matches(f["text"], keywords)]
            if matched:
                sections.append(
                    {
                        "key": key,
                        "status": "documented",
                        "content": " ".join(f["text"].strip() for f in matched),
                        "source_span_ids": [f["id"] for f in matched],
                    }
                )
            else:
                sections.append({"key": key, "status": "missing", "content": "", "source_span_ids": []})
        return json.dumps({"sections": sections}, ensure_ascii=False)

    @staticmethod
    def _matches(text: str, keywords: Sequence[str]) -> bool:
        normalized = text.lower()
        return any(keyword in normalized for keyword in keywords)


__all__ = [
    "CLAVES_SECCION_DERIVADA",
    "build_system_prompt",
    "build_user_prompt",
    "RuleBasedSummaryLLMClient",
]
