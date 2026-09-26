"""Caso de uso de PAC-03: armar el resumen 360 de un paciente.

Orquesta repository.py (SQL puro) y aplica la única regla de negocio de
esta historia que no es una simple consulta: qué campos clínicos clave
cuentan como "información faltante" (AC2, ligado a HC-05).
"""
from __future__ import annotations

import sqlite3

from . import repository
from .models import AccesoRapido, AlertaActiva, ResumenPaciente360, TratamientoReciente

#: Orden de severidad para las alertas activas -- más urgente primero.
#: Vive aquí (no en repository.py) porque es una decisión de negocio,
#: no algo que SQL exprese de forma natural sin codificar el orden a mano.
_ORDEN_SEVERIDAD = {"alta": 0, "media": 1, "baja": 2}

#: Campos clínicos clave del dashboard 360 (AC1). Si cualquiera de estos
#: falta, se reporta en `campos_faltantes` (AC2/HC-05) -- nunca se
#: infiere ni se rellena con un valor por defecto que aparente estar
#: completo.
_CAMPOS_CLAVE_DASHBOARD = ("diagnostico_principal", "estadio", "tratamiento_mas_reciente")


class PacienteNoEncontrado360(Exception):
    """El id no existe en resumen_360, o no pertenece al oncólogo que
    consulta -- ver repository.obtener_paciente_360, mismo criterio de
    no distinguir los dos casos que D2 del plan."""

    def __init__(self, paciente_id: int):
        self.paciente_id = paciente_id
        super().__init__(f"No existe un paciente con id={paciente_id} en resumen_360 para este oncólogo.")


def obtener_resumen_360(
    conn: sqlite3.Connection, paciente_id: int, oncologo_id: int
) -> ResumenPaciente360:
    fila = repository.obtener_paciente_360(conn, paciente_id, oncologo_id)
    if fila is None:
        raise PacienteNoEncontrado360(paciente_id)

    fila_tratamiento = repository.tratamiento_mas_reciente(conn, paciente_id)
    tratamiento = (
        TratamientoReciente(
            regimen=fila_tratamiento["regimen"],
            estado=fila_tratamiento["estado"],
            fecha_inicio=fila_tratamiento["fecha_inicio"],
        )
        if fila_tratamiento is not None
        else None
    )

    alertas = tuple(
        AlertaActiva(
            tipo=f["tipo"], severidad=f["severidad"], descripcion=f["descripcion"], fecha=f["fecha"]
        )
        for f in sorted(
            repository.alertas_activas(conn, paciente_id),
            key=lambda f: (_ORDEN_SEVERIDAD.get(f["severidad"], 99), f["fecha"]),
        )
    )

    labs = tuple(
        AccesoRapido(fecha=f["fecha"], resumen=f["resumen"])
        for f in repository.labs_recientes(conn, paciente_id)
    )
    imagenes = tuple(
        AccesoRapido(fecha=f["fecha"], resumen=f["resumen"])
        for f in repository.imagenes_recientes(conn, paciente_id)
    )
    notas = tuple(
        AccesoRapido(fecha=f["fecha"], resumen=f["resumen"])
        for f in repository.notas_recientes(conn, paciente_id)
    )

    valores_por_campo = {
        "diagnostico_principal": fila["diagnostico_principal"],
        "estadio": fila["estadio"],
        "tratamiento_mas_reciente": tratamiento,
    }
    campos_faltantes = tuple(
        campo for campo in _CAMPOS_CLAVE_DASHBOARD if not valores_por_campo[campo]
    )

    return ResumenPaciente360(
        paciente_id=paciente_id,
        nombre=fila["nombre"],
        diagnostico_principal=fila["diagnostico_principal"],
        estadio=fila["estadio"],
        tratamiento_mas_reciente=tratamiento,
        alertas_activas=alertas,
        labs_recientes=labs,
        imagenes_recientes=imagenes,
        notas_recientes=notas,
        campos_faltantes=campos_faltantes,
    )
