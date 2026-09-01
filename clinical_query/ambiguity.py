"""IA-06 — Detección de consultas clínicas ambiguas.

IA-01 (``clinical_query.service``) resuelve la ambigüedad *en silencio*:
``detect_concept`` se queda con el alias más largo y el servicio devuelve el
dato más reciente sin avisar. IA-06 exige lo contrario: identificar cuándo una
pregunta admite más de una interpretación clínica válida y **pedir aclaración
antes de responder**, sin elegir nunca una interpretación de forma arbitraria y
sin mezclar información entre pacientes o episodios distintos.

Este módulo contiene únicamente funciones puras de detección (sin estado, sin
acceso a base de datos). El servicio las orquesta y decide, con su resultado, si
responde o si devuelve una solicitud de aclaración.

Se distinguen tres tipos de ambigüedad, uno por criterio de aceptación de la
historia:

1. ``PATIENT``: la pregunta menciona a un paciente que no es el activo (o a uno
   que no puede determinarse sin ambigüedad). Nunca se usa información de otro
   paciente: se pide aclaración.
2. ``DATA_POINT``: la pregunta podría referirse a más de un dato clínico y no
   hay forma de saber cuál se pide.
3. ``EPISODE``: el dato solicitado existe en más de un episodio (consulta) y la
   pregunta no acota a cuál, de modo que la elección del episodio cambiaría la
   respuesta.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from .normalizer import normalize_text


class AmbiguityKind(str, enum.Enum):
    PATIENT = "PATIENT"
    DATA_POINT = "DATA_POINT"
    EPISODE = "EPISODE"


@dataclass(frozen=True)
class AmbiguityFinding:
    """Una ambigüedad detectada, con las opciones concretas entre las que elegir."""

    kind: AmbiguityKind
    message: str
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class PacienteRef:
    """Identidad mínima de un paciente, para desambiguar a quién se refiere la pregunta."""

    id: str
    nombre: str
    identificacion: Optional[str] = None


# Palabras que fijan "el más reciente" como episodio de interés. Si la pregunta
# trae una de estas (o una fecha explícita), la elección de episodio deja de ser
# ambigua: el usuario ya indicó cuál quiere.
_CALIFICADORES_TEMPORALES: tuple[str, ...] = (
    "ultimo",
    "ultima",
    "reciente",
    "mas reciente",
    "actual",
    "vigente",
    "hoy",
)

_FECHA_ISO = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def tiene_calificador_temporal(question: str) -> bool:
    """True si la pregunta ya indica qué episodio quiere (p. ej. "el último")."""

    normalized = f" {normalize_text(question)} "
    if _FECHA_ISO.search(question):
        return True
    return any(f" {c} " in normalized for c in _CALIFICADORES_TEMPORALES)


def _tokens_significativos(nombre: str) -> list[str]:
    # Se ignoran tokens muy cortos y la marca "(sintético)" de los datos de
    # prueba para no generar falsos positivos.
    descartar = {"sintetico", "de", "la", "el", "del"}
    return [t for t in normalize_text(nombre).split() if len(t) >= 3 and t not in descartar]


def nombra_otro_paciente(
    question: str,
    directorio: Sequence[PacienteRef],
    paciente_activo_id: str,
) -> Optional[AmbiguityFinding]:
    """Detecta si la pregunta se refiere a un paciente distinto al activo.

    Devuelve un ``AmbiguityFinding`` de tipo ``PATIENT`` si:
    - la pregunta menciona el nombre o la identificación de otro paciente, o
    - menciona un nombre que coincide con más de un paciente del directorio.

    Devuelve ``None`` si la pregunta no nombra a nadie o solo nombra al paciente
    activo (en cuyo caso no hay ambigüedad).
    """

    normalized = f" {normalize_text(question)} "
    activos = {str(paciente_activo_id)}

    coincidencias: list[PacienteRef] = []
    for paciente in directorio:
        if paciente.identificacion and normalize_text(paciente.identificacion) in normalized:
            coincidencias.append(paciente)
            continue
        tokens = _tokens_significativos(paciente.nombre)
        if tokens and any(f" {t} " in normalized for t in tokens):
            coincidencias.append(paciente)

    if not coincidencias:
        return None

    ids_mencionados = {str(p.id) for p in coincidencias}

    # Solo se menciona al paciente activo: sin ambigüedad.
    if ids_mencionados <= activos:
        return None

    otros = [p for p in coincidencias if str(p.id) not in activos]
    nombres = ", ".join(sorted({p.nombre for p in otros}))
    return AmbiguityFinding(
        kind=AmbiguityKind.PATIENT,
        message=(
            "La consulta parece referirse a un paciente distinto al paciente "
            f"activo ({nombres}). No se usará información de otro paciente: "
            "confirma si la pregunta es sobre el paciente activo o cambia de "
            "paciente antes de continuar."
        ),
        options=tuple(sorted({p.nombre for p in otros})),
    )


def ambiguedad_de_dato(conceptos: Sequence[str]) -> Optional[AmbiguityFinding]:
    """Ambigüedad cuando la pregunta menciona más de un dato clínico posible."""

    if len(conceptos) <= 1:
        return None
    return AmbiguityFinding(
        kind=AmbiguityKind.DATA_POINT,
        message=(
            "La consulta podría referirse a más de un dato clínico "
            f"({', '.join(conceptos)}). Especifica cuál necesitas."
        ),
        options=tuple(conceptos),
    )


def ambiguedad_de_episodio(
    resumenes_por_episodio: Iterable[str],
) -> Optional[AmbiguityFinding]:
    """Ambigüedad cuando el dato existe en más de un episodio y no se acotó cuál.

    ``resumenes_por_episodio`` es una lista ya formateada por el servicio
    (``"consulta-3 — 11.5 g/dL (2026-04-20)"``); este módulo no toca la base de
    datos.
    """

    resumenes = list(resumenes_por_episodio)
    if len(resumenes) <= 1:
        return None
    return AmbiguityFinding(
        kind=AmbiguityKind.EPISODE,
        message=(
            "El dato solicitado está registrado en más de un episodio clínico y "
            "la elección del episodio cambia la respuesta. Indica a qué episodio "
            "te refieres."
        ),
        options=tuple(resumenes),
    )
