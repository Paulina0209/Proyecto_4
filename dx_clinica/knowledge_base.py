"""Perfiles diagnósticos sintéticos usados por el motor de diagnóstico diferencial.

Cada ``PerfilDiagnostico`` define, de forma explícita y legible por un
humano, qué criterios clínicos lo sustentan. No hay ningún modelo
estadístico ni LLM decidiendo qué diagnósticos existen: es una tabla de
conocimiento curada, en el mismo espíritu que las reglas ya existentes en
``guidelines/`` (explícitas, versionables, revisables por un clínico),
aunque mucho más pequeña y sin ninguna pretensión de cobertura clínica
real todavía — es deliberadamente un punto de partida pequeño para poder
probar DX-02 de punta a punta, no un catálogo diagnóstico validado.

Los perfiles aquí están pensados para poder evaluarse contra los
pacientes sintéticos de ``historia_clinica_mock`` (breast_early_tnbc y
NSCLC oncogene-addicted), no para cobertura clínica general.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class Criterio:
    id: str
    descripcion: str
    palabras_clave: Tuple[str, ...]


@dataclass(frozen=True)
class PerfilDiagnostico:
    id: str
    nombre: str
    criterios: Tuple[Criterio, ...]
    #: Si es True, la evidencia se resuelve según el diagnóstico principal
    #: del paciente (``evidence.evidencia_por_diagnostico_principal``) en
    #: vez de una guía fija — porque este perfil no es específico de una
    #: patología (aplica igual a cualquier tipo de cáncer de base).
    evidencia_dinamica: bool = False
    #: Carpeta de módulo en `guidelines/` a citar como evidencia fija,
    #: cuando aplica un perfil específico de una patología concreta. None
    #: si no existe ninguna guía en el repositorio relevante para este
    #: perfil (en ese caso no se cita evidencia — nunca se inventa una).
    evidencia_module_folder: Optional[str] = None


PERFIL_TOXICIDAD_MUSCULOESQUELETICA = PerfilDiagnostico(
    id="toxicidad_musculoesqueletica",
    nombre="Toxicidad musculoesquelética asociada a tratamiento oncológico sistémico",
    criterios=(
        Criterio(
            id="dolor_articular",
            descripcion="Dolor articular u óseo de aparición reciente",
            palabras_clave=("dolor articular", "artralgia", "dolor óseo"),
        ),
        Criterio(
            id="ciclo_reciente_tratamiento",
            descripcion="Síntoma referido en relación temporal con un ciclo de tratamiento sistémico reciente",
            palabras_clave=("ciclo de quimioterapia", "último ciclo", "post-quimioterapia"),
        ),
    ),
    evidencia_dinamica=True,
)

PERFIL_PROGRESION_ENFERMEDAD_BASE = PerfilDiagnostico(
    id="progresion_enfermedad_base",
    nombre="Progresión de la enfermedad oncológica de base",
    criterios=(
        Criterio(
            id="hallazgo_imagen_progresion",
            descripcion="Hallazgo imagenológico compatible con progresión (nuevo hallazgo o aumento de tamaño)",
            palabras_clave=("nuevo nódulo", "aumento de tamaño", "progresión"),
        ),
        Criterio(
            id="sintomas_generales_progresivos",
            descripcion="Síntomas generales o respiratorios de curso progresivo",
            palabras_clave=("disnea progresiva", "tos persistente", "pérdida de peso"),
        ),
        Criterio(
            id="impresion_clinica_progresion",
            descripcion="Impresión clínica de progresión registrada explícitamente en la consulta",
            palabras_clave=("sospecha de progresión", "progresión de enfermedad"),
        ),
    ),
    evidencia_dinamica=True,
)

PERFIL_PROCESO_INFECCIOSO_RESPIRATORIO = PerfilDiagnostico(
    id="proceso_infeccioso_respiratorio",
    nombre="Proceso infeccioso respiratorio concomitante",
    criterios=(
        Criterio(
            id="fiebre",
            descripcion="Fiebre o temperatura elevada",
            palabras_clave=("fiebre", "temperatura elevada"),
        ),
        Criterio(
            id="sintomas_respiratorios_agudos",
            descripcion="Síntomas respiratorios agudos (tos, disnea)",
            palabras_clave=("tos", "disnea"),
        ),
    ),
    # Ninguna guía en `guidelines/` cubre manejo de procesos infecciosos
    # (todas son de elegibilidad de tratamiento oncológico), así que este
    # perfil deliberadamente no cita evidencia — no se inventa una.
    evidencia_dinamica=False,
    evidencia_module_folder=None,
)

PERFIL_TOXICIDAD_HEPATICA = PerfilDiagnostico(
    id="toxicidad_hepatica_tratamiento",
    nombre="Toxicidad hepática relacionada con tratamiento sistémico",
    criterios=(
        Criterio(
            id="enzimas_hepaticas_alteradas",
            descripcion="Elevación de enzimas hepáticas fuera de rango de referencia",
            palabras_clave=("función hepática", "fuera de rango de referencia", "alt"),
        ),
    ),
    evidencia_dinamica=True,
)

CATALOGO_DIAGNOSTICO_DIFERENCIAL: Tuple[PerfilDiagnostico, ...] = (
    PERFIL_TOXICIDAD_MUSCULOESQUELETICA,
    PERFIL_PROGRESION_ENFERMEDAD_BASE,
    PERFIL_PROCESO_INFECCIOSO_RESPIRATORIO,
    PERFIL_TOXICIDAD_HEPATICA,
)
