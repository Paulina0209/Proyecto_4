"""EST-03 — Manejo de la estadificación incompleta.

Como oncólogo, quiero que el sistema identifique cuándo no hay datos suficientes
para determinar una estadificación completa, para entender qué componentes sí se
pueden establecer y qué información falta para determinar el estadio con mayor
precisión.

Este módulo es una **capa de lectura** sobre la ``PropuestaEstadificacion`` que
ya produce EST-01 (``estadificacion.builder``): no la modifica ni asume valores.
Mismo patrón que ``dx_clinica/incertidumbre.py`` respecto a DX-02.

Reglas de negocio no negociables (backlog, historia EST-03):

- El sistema **nunca** asume valores de T, N, M ni de otros componentes cuando
  la información necesaria no está disponible.
- Los componentes indeterminados quedan **explícitamente** identificados como
  tales.
- Si la información disponible admite más de un estadio posible, se comunica el
  rango o las alternativas **sin elegir una de forma arbitraria**.
- Si no hay información suficiente para el estadio global, no se presenta un
  estadio definitivo como si estuviera confirmado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple

from estadificacion.models import PropuestaEstadificacion
from estadificacion.staging_systems import (
    estadios_candidatos,
    orden_estadio,
    sistema_para_cancer,
)

_DISCLAIMER = (
    "Estadificación incompleta: los componentes indeterminados se listan como "
    "tales y no se les asume ningún valor. El estadio no está confirmado y debe "
    "completarse con la información clínica pendiente y validarse por el "
    "profesional tratante."
)


@dataclass(frozen=True)
class ComponenteIndeterminado:
    """Un componente del sistema que no se pudo determinar con el expediente actual."""

    codigo: str  # "T" | "N" | "M"
    variable_expediente: str
    criterio_pendiente: str
    informacion_requerida: str
    motivo: str  # "sin dato registrado" | "el valor registrado no es interpretable"


@dataclass(frozen=True)
class AnalisisEstadificacionIncompleta:
    """Resultado del análisis de completitud sobre una ``PropuestaEstadificacion``.

    No contiene ninguna estadificación propia: nunca reemplaza ni completa la
    propuesta de EST-01. Es, a propósito, exclusivamente informativo.
    """

    estadificacion_completa: bool
    estadio_confirmado: bool
    componentes_determinados: Tuple[str, ...]
    componentes_indeterminados: Tuple[ComponenteIndeterminado, ...]
    estadios_posibles: Tuple[str, ...]
    rango_legible: Optional[str]
    informacion_faltante: Tuple[str, ...]
    mensaje: str
    disclaimer: str = field(default=_DISCLAIMER)


def analizar_estadificacion_incompleta(
    propuesta: PropuestaEstadificacion,
) -> AnalisisEstadificacionIncompleta:
    """Analiza qué se pudo determinar de ``propuesta`` y qué queda pendiente."""

    sistema = sistema_para_cancer(propuesta.cancer_type)

    if sistema is None:
        # Sin sistema aplicable no hay componentes que evaluar: EST-01 ya
        # explicó el motivo en su fundamento_global.
        return AnalisisEstadificacionIncompleta(
            estadificacion_completa=False,
            estadio_confirmado=False,
            componentes_determinados=(),
            componentes_indeterminados=(),
            estadios_posibles=(),
            rango_legible=None,
            informacion_faltante=propuesta.datos_faltantes,
            mensaje=propuesta.fundamento_global,
        )

    familia_por_codigo = {
        comp.codigo: comp.familia for comp in propuesta.componentes if comp.familia
    }
    determinados = tuple(
        comp.codigo for comp in sistema.componentes if comp.codigo in familia_por_codigo
    )

    indeterminados: list[ComponenteIndeterminado] = []
    valores_registrados = {comp.codigo: comp for comp in propuesta.componentes}
    for comp_def in sistema.componentes:
        if comp_def.codigo in familia_por_codigo:
            continue
        registrado = valores_registrados.get(comp_def.codigo)
        motivo = (
            "el valor registrado no se pudo interpretar como una categoría del sistema"
            if registrado is not None
            else "sin dato registrado en el expediente"
        )
        indeterminados.append(
            ComponenteIndeterminado(
                codigo=comp_def.codigo,
                variable_expediente=comp_def.variable_expediente,
                criterio_pendiente=comp_def.descripcion_criterio,
                informacion_requerida=comp_def.informacion_requerida,
                motivo=motivo,
            )
        )

    completa = not indeterminados
    posibles = estadios_candidatos(sistema, familia_por_codigo)
    estadio_confirmado = len(posibles) == 1 and completa

    rango_legible = _rango_legible(posibles)
    mensaje = _mensaje(
        sistema, determinados, tuple(indeterminados), posibles, completa
    )

    return AnalisisEstadificacionIncompleta(
        estadificacion_completa=completa,
        estadio_confirmado=estadio_confirmado,
        componentes_determinados=determinados,
        componentes_indeterminados=tuple(indeterminados),
        estadios_posibles=posibles,
        rango_legible=rango_legible,
        informacion_faltante=tuple(c.informacion_requerida for c in indeterminados),
        mensaje=mensaje,
    )


def _rango_legible(posibles: Tuple[str, ...]) -> Optional[str]:
    if len(posibles) <= 1:
        return None
    ordenados = sorted(posibles, key=orden_estadio)
    return (
        f"entre {ordenados[0]} y {ordenados[-1]} "
        f"(alternativas posibles: {', '.join(ordenados)})"
    )


def _mensaje(
    sistema,
    determinados: Tuple[str, ...],
    indeterminados: Tuple[ComponenteIndeterminado, ...],
    posibles: Tuple[str, ...],
    completa: bool,
) -> str:
    if completa and len(posibles) == 1:
        return (
            f"Estadificación completa según {sistema.identificador_legible()}: "
            f"estadio {posibles[0]}."
        )
    if completa and not posibles:
        return (
            "Los componentes están determinados pero su combinación no está "
            f"cubierta por la tabla incluida para {sistema.identificador_legible()}; "
            "no se presenta un estadio."
        )

    partes = []
    if determinados:
        partes.append(f"componentes determinados: {', '.join(determinados)}")
    if indeterminados:
        partes.append(
            "componentes que no se pueden determinar con la información actual: "
            + ", ".join(c.codigo for c in indeterminados)
        )

    if not posibles:
        cierre = (
            "con la información disponible no se puede acotar el estadio; "
            "no se presenta ningún estadio como confirmado"
        )
    elif len(posibles) == 1:
        cierre = (
            f"la información disponible ya acota el estadio a {posibles[0]}, "
            "aunque algún componente siga pendiente de registro"
        )
    else:
        cierre = (
            "según los valores que podrían tomar los componentes pendientes, el "
            f"estadio estaría {_rango_legible(posibles)}; no se selecciona uno"
        )

    return "Estadificación incompleta: " + "; ".join(partes) + f". {cierre}."
