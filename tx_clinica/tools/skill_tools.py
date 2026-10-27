"""Tool ``activar_skill``: carga bajo demanda el procedimiento de una skill.

El prompt solo trae el catálogo (nombre y descripción). Cuando la tarea lo pide, el
modelo llama esta tool y recibe el cuerpo de ``SKILL.md`` (o, con ``recurso``, un
archivo de ``references/``, ``scripts/`` o ``assets/`` que ese cuerpo le mande a
leer). Es de solo lectura: no toca el expediente ni necesita aprobación humana.
"""

from __future__ import annotations

from typing import Optional

from langchain_core.tools import tool

from tx_clinica import skills


@tool
def activar_skill(nombre: str, recurso: Optional[str] = None) -> str:
    """Carga una skill: el procedimiento detallado para una tarea (por ejemplo, cómo trazar una
    recomendación de tratamiento a partir de las guías clínicas).

    Llámala ANTES de recomendar un tratamiento o de usar las tools de recomendación e
    interacciones, con el nombre exacto de la skill que aparece en <skills_disponibles>.
    Devuelve las instrucciones que debes seguir paso a paso y la lista de archivos de apoyo.
    Para leer uno de esos archivos, vuelve a llamarla con el mismo nombre y su ruta en `recurso`
    (por ejemplo "references/registro-de-decision.md").

    Args:
        nombre: nombre exacto de la skill.
        recurso: ruta opcional de un archivo de apoyo de esa skill.
    """
    try:
        disponibles = skills.skills_disponibles()
        if recurso:
            return skills.leer_recurso(nombre, recurso, disponibles)
        return skills.activar(nombre, disponibles)
    except skills.SkillNoEncontrada:
        nombres = ", ".join(sorted(skills.skills_disponibles())) or "ninguna"
        return f"No existe la skill {nombre!r}. Skills disponibles: {nombres}."
    except skills.RecursoNoDisponible as exc:
        return str(exc)
