"""Middleware que exige activar la skill antes de las tools que ella gobierna.

La divulgación progresiva tiene un riesgo: si el modelo no activa la skill, se
salta el procedimiento. Igual que con la aprobación humana (ver
``human_in_the_loop.py``), esto no se deja solo al prompt: aunque el modelo
decida llamar ``obtener_recomendaciones_tratamiento_por_id`` sin haber cargado
``ruta-recomendacion-guias``, la tool no se ejecuta; el modelo recibe un error que
le dice qué activar y reintenta. Solo cubre tools de **lectura**; las que escriben
en el expediente siguen protegidas por la aprobación humana, no por esto.

«Activada» significa que en el historial de la conversación hay una respuesta
exitosa de ``activar_skill`` con el cuerpo de la skill (no basta con haber leído uno
de sus archivos de ``references/``). Como el historial vive en el checkpointer, la
activación vale para toda la conversación.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

NOMBRE_TOOL_ACTIVACION = "activar_skill"

#: Tools de lectura que forman parte de la ruta de recomendación.
TOOLS_QUE_EXIGEN_SKILL = frozenset(
    {
        "listar_variables_requeridas",
        "obtener_recomendaciones_tratamiento_por_id",
        "completar_datos_paciente_y_recomendar",
        "obtener_recomendaciones_tratamiento_con_datos",
        "chequear_interacciones_tratamiento",
    }
)


def _texto(mensaje: Any) -> str:
    texto = getattr(mensaje, "text", None)
    if isinstance(texto, str):
        return str(texto)
    contenido = getattr(mensaje, "content", "")
    return contenido if isinstance(contenido, str) else ""


def skill_activada(mensajes: Any, skill: str) -> bool:
    """¿Hay en ``mensajes`` una activación exitosa de ``skill``?"""
    marca = f'<skill_content name="{skill}">'
    for mensaje in mensajes or ():
        if (
            isinstance(mensaje, ToolMessage)
            and mensaje.name == NOMBRE_TOOL_ACTIVACION
            and getattr(mensaje, "status", "success") != "error"
            and _texto(mensaje).lstrip().startswith(marca)
        ):
            return True
    return False


class ExigirSkillMiddleware(AgentMiddleware):
    """Rechaza (sin ejecutar) las tools de ``tools`` mientras ``skill`` no esté activada."""

    def __init__(self, skill: str, tools: frozenset[str] = TOOLS_QUE_EXIGEN_SKILL) -> None:
        super().__init__()
        self.skill = skill
        # Ojo: AgentMiddleware ya tiene un atributo `tools` (las tools que el middleware aporta al
        # agente); por eso este se llama distinto.
        self.tools_exigidas = frozenset(tools)

    def _rechazo(self, request: Any) -> ToolMessage | None:
        llamada = request.tool_call
        if llamada.get("name") not in self.tools_exigidas:
            return None
        mensajes = (request.state or {}).get("messages")
        if skill_activada(mensajes, self.skill):
            return None
        return ToolMessage(
            content=(
                f"No se ejecutó {llamada.get('name')}: primero debes activar la skill "
                f"'{self.skill}' con {NOMBRE_TOOL_ACTIVACION}(nombre=\"{self.skill}\") y seguir "
                "su procedimiento. Actívala y luego vuelve a llamar esta tool."
            ),
            name=llamada.get("name"),
            tool_call_id=llamada.get("id"),
            status="error",
        )

    def wrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        return self._rechazo(request) or handler(request)

    async def awrap_tool_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        rechazo = self._rechazo(request)
        return rechazo if rechazo is not None else await handler(request)


def construir_middleware_exigir_skill(skill: str) -> ExigirSkillMiddleware:
    return ExigirSkillMiddleware(skill)
