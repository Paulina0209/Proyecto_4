from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Union

from langchain_core.tools import tool

from historia_clinica_mock.repository import obtener_paciente
from tx_clinica.patient_facts import construir_facts_paciente
from tx_clinica.tools._db import conn_lock, obtener_conexion


@dataclass
class PacienteResuelto:
    paciente_id: int
    paciente: Any = None  # tipo real de historia_clinica_mock.repository.Paciente


@dataclass
class ErrorPacienteNoEncontrado:
    paciente_id: int

    def a_json(self) -> str:
        return json.dumps(
            {
                "error": "paciente_no_registrado",
                "paciente_id": self.paciente_id,
                "mensaje": (
                    f"No existe ningún paciente con id={self.paciente_id} en el sistema. "
                    "No asumas que existe ni sigas adelante con otra tool usando este id -- "
                    "infórmaselo al oncólogo y, si quiere, ofrécele iniciar el registro (HC-01)."
                ),
            },
            ensure_ascii=False,
        )


def obtener_paciente_o_error(
    paciente_id: int,
) -> Union[PacienteResuelto, ErrorPacienteNoEncontrado]:
    """Helper COMPARTIDO por todas las tools que reciben paciente_id (no
    solo las de este archivo) -- ver plan de continuidad, caso borde 5.2:
    ninguna tool debe seguir adelante como si el paciente existiera con
    datos vacíos cuando en realidad no existe, porque una lista vacía por
    "no hay paciente" se ve idéntica a una lista vacía por "paciente real
    sin datos" -- exactamente la ambigüedad que el proyecto evita en
    todos los demás lugares (dato ausente != negativo)."""
    conn = obtener_conexion()
    with conn_lock:
        paciente = obtener_paciente(conn, paciente_id)
    if paciente is None:
        return ErrorPacienteNoEncontrado(paciente_id)
    return PacienteResuelto(paciente_id=paciente_id, paciente=paciente)


@tool
def obtener_datos_paciente(patient_id: int) -> str:
    """Devuelve, en JSON, los datos clínicos estructurados de un paciente
    YA REGISTRADO en la base de datos (identificación, diagnóstico
    principal, estadio, y todas las variables clínicas usadas por las
    guías: estadio TNM, biomarcadores, ECOG, etc.). Usa esta tool cuando
    el oncólogo pregunte qué datos tiene un paciente, o antes de generar
    una recomendación por id de paciente, para poder mencionar sus datos
    reales en la respuesta."""
    resuelto = obtener_paciente_o_error(patient_id)
    if isinstance(resuelto, ErrorPacienteNoEncontrado):
        return resuelto.a_json()

    conn = obtener_conexion()
    with conn_lock:
        facts = construir_facts_paciente(conn, patient_id)

    paciente = resuelto.paciente
    return json.dumps(
        {
            "paciente_id": patient_id,
            "nombre": paciente.nombre,
            "diagnostico_principal": paciente.diagnostico_principal,
            "estadio_registrado": paciente.estadio,
            "facts_clinicos": facts,
        },
        ensure_ascii=False,
    )
