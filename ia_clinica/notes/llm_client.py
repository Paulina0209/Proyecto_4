"""Interfaz de cliente LLM y proveedores.

El generador de notas (``ClinicalNoteGenerator``) depende únicamente de la
interfaz :class:`LLMClient`, nunca de un proveedor concreto. Esto permite:

    - desarrollar y probar todo el módulo sin llaves de API ni acceso a
      red, usando :class:`RuleBasedLLMClient`;
    - conectar más adelante un proveedor real (Anthropic, OpenAI, un
      modelo propio de la institución, etc.) implementando la misma
      interfaz, sin tocar el generador ni las pruebas existentes.

Se eligió explícitamente **no** integrar todavía un proveedor real por
defecto: en este repositorio aún no hay una llave de API configurada, y
elegir el proveedor definitivo es una decisión de producto/infraestructura
que corresponde tomar por separado.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Iterable, List, Sequence

from ia_clinica.notes.formats import NoteFormatSpec
from ia_clinica.notes.models import ClinicalContext


class LLMClient(ABC):
    """Interfaz mínima que debe cumplir cualquier proveedor de LLM."""

    @abstractmethod
    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Devuelve la respuesta cruda (texto) del modelo para el prompt dado."""
        raise NotImplementedError


def build_system_prompt(format_spec: NoteFormatSpec) -> str:
    """Construye el prompt de sistema con las reglas anti-alucinación de IA-02."""

    section_lines = "\n".join(
        f'  - "{s.key}" ({s.label}): {s.guidance}' for s in format_spec.sections
    )
    section_keys = ", ".join(f'"{s.key}"' for s in format_spec.sections)
    return (
        "Eres un asistente clínico que redacta borradores de notas médicas "
        f"en formato {format_spec.name} para un oncólogo.\n"
        "Reglas obligatorias, sin excepción:\n"
        "1. Usa EXCLUSIVAMENTE la información contenida en los fragmentos de "
        "la consulta que se te entregan. No agregues datos clínicos, "
        "supuestos, ni conocimiento médico general que no esté explícito en "
        "esos fragmentos.\n"
        "2. Si no hay información suficiente en los fragmentos para "
        "completar una sección, no la completes: márcala con "
        '"status": "missing" y deja "content" vacío.\n'
        "3. Toda sección que sí completes debe listar en "
        '"source_span_ids" los identificadores de los fragmentos exactos '
        "que respaldan ese contenido. No cites fragmentos que no existan.\n"
        "4. Responde ÚNICAMENTE con un objeto JSON válido, sin texto "
        "adicional antes o después, con esta forma exacta:\n"
        '{"sections": [{"key": <clave_seccion>, "status": "documented"|"missing", '
        '"content": <texto o "">, "source_span_ids": [<ids>]}]}\n'
        f"Las claves de sección esperadas son: {section_keys}.\n"
        "Definición de cada sección:\n"
        f"{section_lines}\n"
        "Este resultado es siempre un borrador que un oncólogo revisará; "
        "nunca es una nota clínica definitiva."
    )


def build_user_prompt(context: ClinicalContext) -> str:
    fragments = [{"id": s.id, "origin": s.origin, "text": s.text} for s in context.segments]
    return json.dumps({"consult_id": context.consult_id, "fragments": fragments}, ensure_ascii=False)


class RuleBasedLLMClient(LLMClient):
    """Implementación de referencia sin proveedor externo ni red.

    No es un LLM real: es un cliente basado en reglas léxicas que asigna
    cada fragmento de la consulta a la sección del formato con la que
    comparte más palabras clave, y copia el fragmento literalmente. Sirve
    como valor por defecto seguro para desarrollo/pruebas: como nunca
    genera texto que no provenga literalmente de un fragmento existente,
    cualquier salida que produce está garantizada como "grounded" (con
    trazabilidad exacta a la consulta).

    Se implementa contra la misma interfaz ``LLMClient`` que usaría un
    proveedor real, de modo que sustituirlo en el futuro no requiere
    cambios en ``ClinicalNoteGenerator``.
    """

    #: Palabras clave (en minúsculas, sin acentos) asociadas a cada sección
    #: SOAP estándar. Un formato institucional distinto puede no tener
    #: buena cobertura con estas palabras; en ese caso las secciones
    #: quedarán, correctamente, marcadas como "missing".
    _KEYWORDS = {
        "S": ("refiere", "motivo de consulta", "síntoma", "sintoma", "antecedente", "dice que", "reporta"),
        "O": ("examen físico", "examen fisico", "signos vitales", "laboratorio", "resultado", "hallazgo", "tac", "resonancia", "biopsia", "biomarcador"),
        "A": ("impresión", "impresion", "diagnóstico", "diagnostico", "evaluación", "evaluacion", "sospecha"),
        "P": ("plan", "indicación", "indicacion", "seguimiento", "se solicita", "se inicia", "control en"),
    }

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        payload = json.loads(user_prompt)
        fragments = payload["fragments"]
        sections = []
        for key, keywords in self._KEYWORDS.items():
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


class AnthropicLLMClient(LLMClient):
    """Adaptador opcional para la API de Anthropic (Claude).

    No se instancia por defecto en ninguna parte de este módulo. Requiere
    tener instalado el paquete ``anthropic`` y una variable de entorno
    ``ANTHROPIC_API_KEY`` configurada. Se deja implementado para que
    conectar un proveedor real, cuando el equipo lo decida, sea un cambio
    de una línea (``ClinicalNoteGenerator(llm_client=AnthropicLLMClient(), ...)``)
    en vez de un rediseño.
    """

    def __init__(self, model: str = "claude-sonnet-4-5", api_key: str | None = None, max_tokens: int = 2000) -> None:
        try:
            import anthropic  # type: ignore
        except ImportError as exc:  # pragma: no cover - depende de instalación externa
            raise ImportError(
                "El paquete 'anthropic' no está instalado. Instálalo con "
                "'pip install anthropic --break-system-packages' para usar AnthropicLLMClient."
            ) from exc
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    def complete(self, system_prompt: str, user_prompt: str) -> str:  # pragma: no cover - requiere red/credenciales
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
