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


class OllamaConnectionError(RuntimeError):
    """No se pudo contactar (o no respondió a tiempo) al servidor local de Ollama."""


class OllamaLLMClient(LLMClient):
    """Adaptador para un modelo local servido por Ollama.

    Este es el proveedor real que sí se usa por defecto a partir de IA-03:
    el proyecto ya tiene un modelo local corriendo con Ollama (usado
    también por ``tx_clinica`` para redactar el rationale de TX-01), así
    que en vez de introducir un segundo mecanismo, este cliente reutiliza
    el mismo servidor y sigue el mismo contrato conceptual que
    ``tx_clinica.llm_client.LocalOllamaLLMClient``: el modelo solo redacta
    texto, nunca decide qué es correcto citar. Aquí lo que redacta es el
    borrador SOAP completo, con el mismo formato JSON que ya produce
    ``RuleBasedLLMClient``, para que ``ClinicalNoteGenerator`` no necesite
    ningún cambio: sigue validando cada sección contra los fragmentos
    reales de la consulta (``_build_section``) exactamente igual que con
    el cliente de referencia. Esa validación es la que importa aún más
    aquí que con ``RuleBasedLLMClient``: un LLM real sí puede redactar
    texto que no provenga literalmente de un fragmento, así que es
    ``ClinicalNoteGenerator`` (no este cliente) quien sigue garantizando
    que ninguna sección sin cita válida llegue al borrador final.

    Requiere Ollama corriendo localmente (``ollama serve``, por defecto en
    ``http://127.0.0.1:11434``) y el modelo ya descargado, por ejemplo:

        ollama pull qwen2.5:14b-instruct-q4_K_M

    Se usa ``127.0.0.1`` en vez de ``localhost`` como valor por defecto de
    ``base_url`` a propósito: en algunas máquinas Windows, ``localhost``
    resuelve primero a ``::1`` (loopback IPv6), y si Ollama solo escucha
    en la interfaz IPv4 (``OLLAMA_HOST=http://127.0.0.1:11434``, el valor
    por defecto de Ollama), una conexión a ``http://localhost:11434``
    puede fallar o demorar de más incluso con el servidor corriendo y
    escuchando correctamente. Usar la IP explícita evita depender de esa
    resolución.

    ``timeout`` (segundos de espera de la respuesta HTTP) es
    deliberadamente generoso por defecto: generar el JSON completo de una
    nota SOAP es una tarea más larga que el rationale corto de 2-4
    oraciones de ``tx_clinica.LocalOllamaLLMClient``, y en una máquina sin
    GPU la primera llamada además paga el costo de cargar el modelo
    (varios GB) en memoria. Si aun así se agota el tiempo, súbelo más
    (por ejemplo ``OllamaLLMClient(timeout=600)``) o "calienta" el modelo
    antes corriendo una vez ``ollama run <modelo>`` desde la terminal.

    Se usa ``"format": "json"`` de la API de Ollama por defecto
    (``usar_formato_json=True``): esto restringe la decodificación del
    modelo a una gramática JSON válida token por token, lo que evita el
    error más común al generar JSON en texto libre — una comilla sin
    escapar dentro de un campo de texto que rompe el parseo a la mitad
    (visto en la práctica: ``json.JSONDecodeError`` a media respuesta).
    En algunos backends esta restricción puede hacer la generación más
    lenta; si eso resulta ser un problema en una máquina concreta, se
    puede desactivar con ``OllamaLLMClient(usar_formato_json=False)`` —
    pero entonces una respuesta con un error de sintaxis simplemente se
    descarta (``GenerationError`` en ``ClinicalNoteGenerator``) en vez de
    inventarse una interpretación parcial.
    """

    def __init__(
        self,
        model: str = "qwen2.5:14b-instruct-q4_K_M",
        base_url: str = "http://127.0.0.1:11434",
        timeout: int = 300,
        temperature: float = 0.1,
        usar_formato_json: bool = True,
    ) -> None:
        try:
            import requests  # type: ignore  # noqa: F401
        except ImportError as exc:  # pragma: no cover - depende de instalación externa
            raise ImportError(
                "El paquete 'requests' no está instalado. Instálalo con "
                "'pip install requests --break-system-packages' para usar OllamaLLMClient."
            ) from exc
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._temperature = temperature
        self._usar_formato_json = usar_formato_json

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        import requests

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {"temperature": self._temperature},
        }
        if self._usar_formato_json:
            payload["format"] = "json"

        try:
            response = requests.post(
                f"{self._base_url}/api/chat",
                json=payload,
                timeout=self._timeout,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as exc:
            raise OllamaConnectionError(
                f"No se pudo contactar al servidor Ollama en '{self._base_url}'. "
                "Verifica que 'ollama serve' esté corriendo y que el modelo "
                f"'{self._model}' ya esté descargado (ollama pull {self._model})."
            ) from exc

        payload = response.json()
        try:
            return payload["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise OllamaConnectionError(
                f"Respuesta inesperada del servidor Ollama: {payload!r}"
            ) from exc

    def esta_disponible(self) -> bool:
        """Chequeo de salud liviano: ¿responde el servidor de Ollama?

        A propósito no genera texto (no llama ``/api/chat``): solo
        consulta ``/api/tags``, para poder decidir si conviene usar este
        cliente sin pagar el costo de una inferencia completa del modelo.
        """
        import requests

        try:
            response = requests.get(f"{self._base_url}/api/tags", timeout=5)
            response.raise_for_status()
        except requests.exceptions.RequestException:
            return False
        return True
