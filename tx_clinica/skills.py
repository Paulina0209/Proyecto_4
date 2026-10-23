"""Skills del agente de tratamiento (formato agentskills.io).

Una *skill* es una carpeta con un ``SKILL.md`` (frontmatter YAML + instrucciones en
Markdown) y, opcionalmente, ``references/``, ``scripts/`` y ``assets/``. Aquí se
descubren, se validan contra la especificación y se cargan por **divulgación
progresiva**, para no gastar contexto del modelo en lo que la tarea no necesita:

1. *Catálogo* (siempre en el prompt): solo ``name`` y ``description`` de cada skill.
2. *Activación* (cuando la tarea lo pide, con la tool ``activar_skill``): el cuerpo
   de ``SKILL.md`` sin el frontmatter, más la lista de recursos que trae.
3. *Recursos* (bajo demanda, ``activar_skill(nombre, recurso=...)``): un archivo de
   ``references/``, ``scripts/`` o ``assets/`` que el cuerpo mande a leer.

Especificación (https://agentskills.io/specification): ``name`` de 1 a 64 caracteres
en minúsculas, dígitos y guiones, sin guion al inicio ni al final ni ``--``, igual al
nombre de la carpeta; ``description`` de 1 a 1024 caracteres que diga qué hace y cuándo
usarla; opcionales ``license``, ``compatibility`` (máx. 500), ``metadata`` (texto a
texto) y ``allowed-tools``. Esta validación es **estricta** a propósito: aquí las skills
son parte del código del repositorio, así que una skill mal formada es un error de
desarrollo y se detecta al construir el agente, no se ignora en silencio.

La carpeta de skills es ``skills/`` en la raíz del repositorio; ``COPILOTO_SKILLS_DIR``
la reemplaza (útil para pruebas y despliegues).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

import yaml

#: Skills sin las que el agente de tratamiento no debe arrancar.
SKILLS_REQUERIDAS = ("ruta-recomendacion-guias",)

#: Campos de frontmatter que admite la especificación.
CAMPOS_PERMITIDOS = frozenset({"name", "description", "license", "compatibility", "metadata", "allowed-tools"})
SUBCARPETAS_DE_RECURSOS = ("references", "scripts", "assets")

MAX_NOMBRE = 64
MAX_DESCRIPCION = 1024
MAX_COMPATIBILIDAD = 500
#: Recomendación de la especificación para el cuerpo (<500 líneas, <5000 tokens aprox.).
MAX_LINEAS_CUERPO = 500
MAX_CARACTERES_CUERPO = 20_000
#: Tope de un recurso que se entrega al modelo (evita volcar archivos enormes al contexto).
MAX_BYTES_RECURSO = 64 * 1024

_PATRON_NOMBRE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_PATRON_FRONTMATTER = re.compile(r"---\n(.*?)\n---[ \t]*(?:\n|$)", re.DOTALL)
_RAIZ_REPO = Path(__file__).resolve().parent.parent


class SkillInvalida(ValueError):
    """Una carpeta de skill no cumple la especificación."""


class SkillNoEncontrada(KeyError):
    """No existe una skill con ese nombre."""


class RecursoNoDisponible(ValueError):
    """El recurso pedido no existe, está fuera de la skill o no se puede entregar."""


@dataclass(frozen=True)
class Skill:
    nombre: str
    descripcion: str
    carpeta: Path
    cuerpo: str
    licencia: Optional[str] = None
    compatibilidad: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    herramientas_permitidas: Optional[str] = None

    def recursos(self) -> list[str]:
        """Rutas relativas (con ``/``) de los archivos de references/, scripts/ y assets/."""
        encontrados: list[str] = []
        for subcarpeta in SUBCARPETAS_DE_RECURSOS:
            base = self.carpeta / subcarpeta
            if base.is_dir():
                encontrados.extend(
                    p.relative_to(self.carpeta).as_posix() for p in sorted(base.rglob("*")) if p.is_file()
                )
        return encontrados


def directorio_skills() -> Path:
    """Carpeta que contiene las skills (cada una en su propia subcarpeta)."""
    return Path(os.environ.get("COPILOTO_SKILLS_DIR") or (_RAIZ_REPO / "skills"))


# ---------------------------------------------------------------------------
# Lectura y validación
# ---------------------------------------------------------------------------
def separar_frontmatter(texto: str) -> tuple[dict, str]:
    """Divide ``SKILL.md`` en (frontmatter como dict, cuerpo). Falla si no hay frontmatter válido."""
    texto = texto.lstrip("﻿").replace("\r\n", "\n")
    if not texto.startswith("---\n"):
        raise SkillInvalida("SKILL.md debe empezar con frontmatter YAML (una línea '---').")
    cierre = _PATRON_FRONTMATTER.match(texto)
    if cierre is None:
        raise SkillInvalida("El frontmatter de SKILL.md no está cerrado con una línea '---'.")
    try:
        datos = yaml.safe_load(cierre.group(1))
    except yaml.YAMLError as exc:
        raise SkillInvalida(f"El frontmatter no es YAML válido: {exc}") from exc
    if not isinstance(datos, dict):
        raise SkillInvalida("El frontmatter de SKILL.md debe ser un mapa YAML (name, description, ...).")
    return datos, texto[cierre.end() :].lstrip("\n")


def _texto_obligatorio(datos: dict, campo: str, maximo: int) -> str:
    valor = datos.get(campo)
    if not isinstance(valor, str) or not valor.strip():
        raise SkillInvalida(f"'{campo}' es obligatorio y debe ser un texto no vacío.")
    valor = valor.strip()
    if len(valor) > maximo:
        raise SkillInvalida(f"'{campo}' tiene {len(valor)} caracteres; el máximo es {maximo}.")
    return valor


def cargar_skill(carpeta: Path) -> Skill:
    """Lee y valida la skill de ``carpeta``. Lanza ``SkillInvalida`` si algo no cumple."""
    carpeta = Path(carpeta)
    archivo = carpeta / "SKILL.md"
    if not archivo.is_file():
        raise SkillInvalida(f"{carpeta.name}: falta SKILL.md.")
    try:
        datos, cuerpo = separar_frontmatter(archivo.read_text(encoding="utf-8"))
        desconocidos = sorted(set(datos) - CAMPOS_PERMITIDOS)
        if desconocidos:
            raise SkillInvalida(f"campos no admitidos en el frontmatter: {', '.join(map(str, desconocidos))}.")

        nombre = _texto_obligatorio(datos, "name", MAX_NOMBRE)
        if not _PATRON_NOMBRE.match(nombre):
            raise SkillInvalida(
                f"'name' ({nombre!r}) solo admite minúsculas, dígitos y guiones, "
                "sin guion al inicio ni al final y sin guiones seguidos."
            )
        if nombre != carpeta.name:
            raise SkillInvalida(f"'name' ({nombre!r}) debe ser igual al nombre de la carpeta ({carpeta.name!r}).")
        descripcion = _texto_obligatorio(datos, "description", MAX_DESCRIPCION)

        compatibilidad = None
        if "compatibility" in datos:
            compatibilidad = _texto_obligatorio(datos, "compatibility", MAX_COMPATIBILIDAD)
        licencia = None
        if "license" in datos:
            licencia = _texto_obligatorio(datos, "license", 10_000)
        herramientas = None
        if "allowed-tools" in datos:
            herramientas = _texto_obligatorio(datos, "allowed-tools", 10_000)
        metadata = datos.get("metadata", {})
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in metadata.items()):
            raise SkillInvalida("'metadata' debe ser un mapa de texto a texto (entre comillas los números, p. ej. \"1.0\").")

        if not cuerpo.strip():
            raise SkillInvalida("SKILL.md no tiene instrucciones después del frontmatter.")
        lineas = cuerpo.count("\n") + 1
        if lineas > MAX_LINEAS_CUERPO or len(cuerpo) > MAX_CARACTERES_CUERPO:
            raise SkillInvalida(
                f"el cuerpo de SKILL.md es demasiado largo ({lineas} líneas, {len(cuerpo)} caracteres; "
                f"máximo {MAX_LINEAS_CUERPO} y {MAX_CARACTERES_CUERPO}). Mueve el detalle a references/."
            )
    except SkillInvalida as exc:
        raise SkillInvalida(f"{carpeta.name}: {exc}") from None
    return Skill(
        nombre=nombre,
        descripcion=descripcion,
        carpeta=carpeta,
        cuerpo=cuerpo,
        licencia=licencia,
        compatibilidad=compatibilidad,
        metadata=dict(metadata),
        herramientas_permitidas=herramientas,
    )


def descubrir_skills(raiz: Optional[Path] = None, *, requeridas: Iterable[str] = ()) -> dict[str, Skill]:
    """Carga todas las skills de ``raiz`` (una por subcarpeta con ``SKILL.md``).

    Lanza ``SkillInvalida`` si alguna no cumple la especificación o si falta alguna de
    ``requeridas``: arrancar el agente sin su procedimiento sería peor que no arrancar.
    """
    raiz = Path(raiz) if raiz is not None else directorio_skills()
    skills: dict[str, Skill] = {}
    if raiz.is_dir():
        for carpeta in sorted(p for p in raiz.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()):
            skill = cargar_skill(carpeta)
            skills[skill.nombre] = skill
    faltan = [n for n in requeridas if n not in skills]
    if faltan:
        raise SkillInvalida(f"faltan skills requeridas en {raiz}: {', '.join(faltan)}.")
    return skills


@lru_cache(maxsize=8)
def _skills_en(raiz: str) -> dict[str, Skill]:
    return descubrir_skills(Path(raiz))


def skills_disponibles() -> dict[str, Skill]:
    """Skills de la carpeta configurada (cacheadas por carpeta; ver ``limpiar_cache``)."""
    return _skills_en(str(directorio_skills().resolve()))


def limpiar_cache() -> None:
    _skills_en.cache_clear()


# ---------------------------------------------------------------------------
# Catálogo, activación y recursos
# ---------------------------------------------------------------------------
def _escapar(texto: str) -> str:
    return texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def catalogo_para_prompt(skills: dict[str, Skill]) -> str:
    """Bloque con nombre y descripción de cada skill, para añadir al system prompt."""
    if not skills:
        return "<skills_disponibles>\n(no hay skills cargadas)\n</skills_disponibles>"
    filas = "\n".join(f"- {s.nombre}: {s.descripcion}" for s in skills.values())
    return f"<skills_disponibles>\n{filas}\n</skills_disponibles>"


def activar(nombre: str, skills: Optional[dict[str, Skill]] = None) -> str:
    """Contenido que recibe el modelo al activar la skill: cuerpo + recursos disponibles."""
    skills = skills_disponibles() if skills is None else skills
    skill = skills.get(nombre)
    if skill is None:
        raise SkillNoEncontrada(nombre)
    partes = [f'<skill_content name="{skill.nombre}">', skill.cuerpo.strip()]
    recursos = skill.recursos()
    if recursos:
        partes += ["", "<skill_resources>", *(f"  <archivo>{_escapar(r)}</archivo>" for r in recursos), "</skill_resources>"]
    partes.append("</skill_content>")
    return "\n".join(partes)


def leer_recurso(nombre: str, ruta: str, skills: Optional[dict[str, Skill]] = None) -> str:
    """Texto de un archivo de ``references/``, ``scripts/`` o ``assets/`` de la skill.

    Solo entrega archivos de texto dentro de esas subcarpetas: una ruta con ``..``, absoluta,
    o un enlace que apunte fuera de la skill se rechaza.
    """
    skills = skills_disponibles() if skills is None else skills
    skill = skills.get(nombre)
    if skill is None:
        raise SkillNoEncontrada(nombre)
    ruta = (ruta or "").strip().replace("\\", "/")
    partes = [p for p in ruta.split("/") if p not in ("", ".")]
    if not partes or ruta.startswith("/") or ".." in partes or partes[0] not in SUBCARPETAS_DE_RECURSOS:
        raise RecursoNoDisponible(
            f"Ruta no permitida: {ruta!r}. Usa una ruta de la lista de recursos "
            f"({', '.join(s + '/' for s in SUBCARPETAS_DE_RECURSOS)})."
        )
    base = skill.carpeta.resolve()
    destino = (base / Path(*partes)).resolve()
    try:
        destino.relative_to(base)
    except ValueError:
        raise RecursoNoDisponible(f"Ruta no permitida: {ruta!r} sale de la carpeta de la skill.") from None
    if not destino.is_file():
        raise RecursoNoDisponible(f"No existe el recurso {ruta!r} en la skill {nombre!r}.")
    if destino.stat().st_size > MAX_BYTES_RECURSO:
        raise RecursoNoDisponible(f"El recurso {ruta!r} es demasiado grande para cargarlo ({MAX_BYTES_RECURSO} bytes máx.).")
    try:
        texto = destino.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise RecursoNoDisponible(f"El recurso {ruta!r} no es un archivo de texto.") from None
    return f'<skill_resource skill="{nombre}" ruta="{"/".join(partes)}">\n{texto.strip()}\n</skill_resource>'
