from __future__ import annotations

import sqlite3
import uuid

from .models import Paciente, ResultadoRegistroPaciente, TipoIdentificacion
from .validacion import validar_campos_obligatorios
from .repository import buscar_por_identificacion, guardar_paciente


def generar_identificador_temporal() -> str:
    return f"TEMP-{uuid.uuid4().hex[:10].upper()}"


def registrar_paciente(
    conn: sqlite3.Connection,
    paciente: Paciente,
) -> ResultadoRegistroPaciente:
    errores = validar_campos_obligatorios(paciente)
    if errores:
        return ResultadoRegistroPaciente(exito=False, errores=errores)

    # El identificador temporal se genera único en el momento, por lo
    # que no tiene sentido buscar duplicados de TEMPORAL en sí mismo.
    if paciente.tipo_identificacion != TipoIdentificacion.TEMPORAL:
        existente = buscar_por_identificacion(
            conn, paciente.tipo_identificacion, paciente.numero_identificacion
        )
        if existente:
            return ResultadoRegistroPaciente(exito=False, posible_duplicado=existente)

    paciente.registro_completo = bool(
        paciente.antecedentes
        and (paciente.antecedentes.personales or paciente.antecedentes.familiares)
        and paciente.motivo_consulta_inicial
    )
    paciente_guardado = guardar_paciente(conn, paciente)
    return ResultadoRegistroPaciente(exito=True, paciente=paciente_guardado)
