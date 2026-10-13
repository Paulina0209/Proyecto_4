from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Union

from langchain_core.tools import tool

from expediente.repository import obtener_paciente
from privacidad.consentimiento_ia import estado_consentimiento_ia
from historia_clinica.biopsias_biomarcadores import PENDIENTE_CONFIRMACION, biomarcadores_clave
from tx_clinica.patient_facts import construir_facts_paciente
from tx_clinica.tools._db import conn_lock, obtener_conexion


@dataclass
class PacienteResuelto:
    paciente_id: int
    paciente: Any = None  # tipo real de expediente.repository.Paciente


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


@dataclass
class ErrorConsentimientoIA:
    """SEC-03: el paciente no tiene consentimiento vigente para usar IA."""

    paciente_id: int
    motivo: str

    def a_json(self) -> str:
        return json.dumps(
            {
                "error": "consentimiento_ia_requerido",
                "paciente_id": self.paciente_id,
                "mensaje": (
                    f"Las funciones de IA no están habilitadas para el paciente {self.paciente_id}: "
                    f"{self.motivo} No uses ni pidas sus datos con ninguna otra tool. Infórmale al "
                    "oncólogo que primero debe registrarse el consentimiento informado del paciente "
                    "(SEC-03). Su historia clínica sigue disponible fuera del asistente."
                ),
            },
            ensure_ascii=False,
        )


#: Lo que puede devolver ``obtener_paciente_o_error`` en vez del paciente.
ERRORES_PACIENTE = (ErrorPacienteNoEncontrado, ErrorConsentimientoIA)


def obtener_paciente_o_error(
    paciente_id: int,
) -> Union[PacienteResuelto, ErrorPacienteNoEncontrado, ErrorConsentimientoIA]:
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
        consentimiento = estado_consentimiento_ia(conn, paciente_id) if paciente is not None else None
    if paciente is None:
        return ErrorPacienteNoEncontrado(paciente_id)
    # SEC-03: el agente es una función de IA; sin consentimiento no recibe datos del paciente.
    if not consentimiento.ia_habilitada:
        return ErrorConsentimientoIA(paciente_id, consentimiento.motivo)
    return PacienteResuelto(paciente_id=paciente_id, paciente=paciente)


@tool
def obtener_datos_paciente(patient_id: int) -> str:
    """Devuelve, en JSON, los datos clínicos estructurados de un paciente
    YA REGISTRADO en la base de datos (id interno, diagnóstico principal,
    estadio, y todas las variables clínicas usadas por las guías: estadio
    TNM, biomarcadores, ECOG, etc.). Por minimización de datos (NFR-04) no
    trae el nombre ni el documento del paciente: refiérete a él por su id. Usa esta tool cuando
    el oncólogo pregunte qué datos tiene un paciente, o antes de generar
    una recomendación por id de paciente, para poder mencionar sus datos
    reales en la respuesta.

    Incluye `biomarcadores_clave` (HC-04): biomarcadores relevantes para una
    terapia dirigida. Los `confirmado: false` vienen de una fuente externa y
    el oncólogo todavía no los confirmó: menciónalos como pendientes de
    confirmación y NO los uses como si fueran un resultado confirmado (su
    variable no está en `facts_clinicos`)."""
    resuelto = obtener_paciente_o_error(patient_id)
    if isinstance(resuelto, ERRORES_PACIENTE):
        return resuelto.a_json()

    conn = obtener_conexion()
    with conn_lock:
        facts = construir_facts_paciente(conn, patient_id)
        clave = biomarcadores_clave(conn, patient_id)

    paciente = resuelto.paciente
    return json.dumps(
        {
            "paciente_id": patient_id,
            "diagnostico_principal": paciente.diagnostico_principal,
            "estadio_registrado": paciente.estadio,
            "facts_clinicos": facts,
            "biomarcadores_clave": [
                {
                    "biomarcador": b.biomarcador,
                    "resultado": b.resultado,
                    "terapia_dirigida": b.terapia_asociada,
                    "confirmado": b.relevancia != PENDIENTE_CONFIRMACION,
                    "variable_tratamiento": b.variable_tx,
                    "fecha": b.fecha,
                }
                for b in clave
            ],
        },
        ensure_ascii=False,
    )
