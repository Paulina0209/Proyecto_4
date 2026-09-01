"""Construcción de la propuesta de estadificación (punto de entrada de EST-01).

Depende de la información que ya existe en ``historia_clinica_mock``:

- la variable estructurada ``cancer_type`` para elegir el sistema aplicable, y
- las variables T/N/M (``clinical_t_category``, ``clinical_n_status``,
  ``clinical_m_status``) que define ese sistema.

Nunca infiere un valor de componente que no esté registrado: lo reporta como
dato faltante. Nunca lee variables que no pertenezcan al sistema seleccionado
(regla de negocio de EST-01).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Dict, Optional

from historia_clinica_mock.repository import (
    DatoClinicoEstructurado,
    datos_clinicos_estructurados_de_paciente,
    obtener_paciente,
)

from estadificacion.models import (
    ComponenteEstadio,
    PropuestaEstadificacion,
)
from estadificacion.staging_systems import (
    SistemaEstadificacion,
    agrupar_estadio,
    familia_de_valor,
    sistema_para_cancer,
)

_VARIABLE_TIPO_CANCER = "cancer_type"


def _ultimo_por_variable(
    datos: list[DatoClinicoEstructurado],
) -> Dict[str, DatoClinicoEstructurado]:
    ultimo: Dict[str, DatoClinicoEstructurado] = {}
    for dato in datos:
        actual = ultimo.get(dato.variable)
        if actual is None or dato.fecha >= actual.fecha:
            ultimo[dato.variable] = dato
    return ultimo


def _propuesta_vacia(
    paciente_id: int,
    ahora: datetime,
    sistema: Optional[SistemaEstadificacion],
    fundamento_global: str,
    datos_faltantes: tuple[str, ...],
) -> PropuestaEstadificacion:
    return PropuestaEstadificacion(
        paciente_id=paciente_id,
        generado_en=ahora,
        sistema_id=sistema.id if sistema else None,
        sistema_version=sistema.version if sistema else None,
        sistema_nombre=sistema.nombre if sistema else None,
        sistema_fuente=sistema.fuente if sistema else None,
        componentes=(),
        estadio_global=None,
        fundamento_global=fundamento_global,
        datos_faltantes=datos_faltantes,
        nota_alcance=sistema.nota_alcance if sistema else None,
    )


def proponer_estadificacion(
    conn: sqlite3.Connection,
    paciente_id: int,
    *,
    ahora: Optional[datetime] = None,
) -> PropuestaEstadificacion:
    """Genera la propuesta de estadificación para un paciente."""

    ahora = ahora or datetime.now()

    paciente = obtener_paciente(conn, paciente_id)
    if paciente is None:
        return _propuesta_vacia(
            paciente_id,
            ahora,
            None,
            f"No existe ningún paciente con id={paciente_id}.",
            (),
        )

    datos = datos_clinicos_estructurados_de_paciente(conn, paciente_id)
    ultimo = _ultimo_por_variable(datos)

    tipo_cancer = ultimo[_VARIABLE_TIPO_CANCER].valor if _VARIABLE_TIPO_CANCER in ultimo else None
    if tipo_cancer is None:
        return _propuesta_vacia(
            paciente_id,
            ahora,
            None,
            "No hay un tipo de cáncer registrado en el expediente estructurado, "
            "así que no se puede seleccionar un sistema de estadificación.",
            (_VARIABLE_TIPO_CANCER,),
        )

    sistema = sistema_para_cancer(tipo_cancer)
    if sistema is None:
        return _propuesta_vacia(
            paciente_id,
            ahora,
            None,
            f"No hay ningún sistema de estadificación registrado para el tipo de "
            f"cáncer '{tipo_cancer}'. No se propone un estadio para no aplicar "
            "criterios que no corresponden.",
            (),
        )

    componentes: list[ComponenteEstadio] = []
    datos_faltantes: list[str] = []
    familias: Dict[str, Optional[str]] = {}

    # SOLO se recorren las variables que define este sistema/versión.
    for comp_def in sistema.componentes:
        registro = ultimo.get(comp_def.variable_expediente)
        if registro is None:
            datos_faltantes.append(comp_def.variable_expediente)
            familias[comp_def.codigo] = None
            continue

        familia = familia_de_valor(registro.valor)
        familias[comp_def.codigo] = familia

        consulta_ref = (
            f"consulta-{registro.consulta_id}" if registro.consulta_id else "sin consulta vinculada"
        )
        familia_txt = f" (familia {familia})" if familia else " (no se pudo normalizar a una familia T/N/M)"
        componentes.append(
            ComponenteEstadio(
                codigo=comp_def.codigo,
                valor=registro.valor,
                criterio_aplicado=comp_def.descripcion_criterio,
                fundamento=(
                    f"Valor '{registro.valor}'{familia_txt} tomado del registro estructurado "
                    f"dato-{registro.id} ({consulta_ref}, {registro.fecha})."
                ),
                fuente_ids=(f"dato-{registro.id}",),
            )
        )

    estadio_global = agrupar_estadio(
        sistema, familias.get("T"), familias.get("N"), familias.get("M")
    )

    if datos_faltantes:
        fundamento_global = (
            "No se propone un estadio global porque faltan componentes requeridos "
            f"por {sistema.identificador_legible()}: {', '.join(datos_faltantes)}."
        )
    elif estadio_global is None:
        fundamento_global = (
            "Los componentes T/N/M están completos pero su combinación "
            f"({familias.get('T')}, {familias.get('N')}, {familias.get('M')}) no está "
            f"cubierta por la tabla de agrupación incluida para "
            f"{sistema.identificador_legible()}."
        )
    else:
        fundamento_global = (
            f"Estadio {estadio_global} según {sistema.identificador_legible()} a partir de "
            f"({familias.get('T')}, {familias.get('N')}, {familias.get('M')})."
        )

    return PropuestaEstadificacion(
        paciente_id=paciente_id,
        generado_en=ahora,
        sistema_id=sistema.id,
        sistema_version=sistema.version,
        sistema_nombre=sistema.nombre,
        sistema_fuente=sistema.fuente,
        componentes=tuple(componentes),
        estadio_global=estadio_global,
        fundamento_global=fundamento_global,
        datos_faltantes=tuple(datos_faltantes),
        nota_alcance=sistema.nota_alcance,
    )
