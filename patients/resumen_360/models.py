"""Modelos de dominio del dashboard 360 del paciente (PAC-03).

Dataclasses simples, sin SQL ni FastAPI -- mismo principio que el resto
del proyecto (p. ej. tx_clinica/models.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass(frozen=True)
class TratamientoReciente:
    regimen: str
    estado: str
    fecha_inicio: str


@dataclass(frozen=True)
class AlertaActiva:
    tipo: str  # "interaccion" | "estudio_pendiente"
    severidad: str  # "alta" | "media" | "baja"
    descripcion: str
    fecha: str


@dataclass(frozen=True)
class AccesoRapido:
    """Una entrada de lab/imagen/nota, solo con lo necesario para la
    lista de acceso rápido del dashboard -- el detalle completo vive en
    la pantalla específica de cada uno, fuera del alcance de PAC-03."""

    fecha: str
    resumen: str


@dataclass(frozen=True)
class ResumenPaciente360:
    """El resultado completo que arma el dashboard 360 (AC1 de PAC-03)."""

    paciente_id: int
    nombre: str
    diagnostico_principal: Optional[str]
    estadio: Optional[str]
    tratamiento_mas_reciente: Optional[TratamientoReciente]
    alertas_activas: Tuple[AlertaActiva, ...] = field(default_factory=tuple)
    labs_recientes: Tuple[AccesoRapido, ...] = field(default_factory=tuple)
    imagenes_recientes: Tuple[AccesoRapido, ...] = field(default_factory=tuple)
    notas_recientes: Tuple[AccesoRapido, ...] = field(default_factory=tuple)

    #: AC2 de PAC-03 (ligado a HC-05): nombres de los campos clínicos
    #: clave que faltan -- nunca se infieren ni se ocultan, el front debe
    #: mostrar un indicador explícito por cada uno listado aquí.
    campos_faltantes: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def informacion_incompleta(self) -> bool:
        return bool(self.campos_faltantes)
