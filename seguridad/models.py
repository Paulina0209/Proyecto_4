"""Modelos de dominio de SEC-01 (autenticación y control de acceso por rol)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Rol(str, Enum):
    ONCOLOGO = "oncologo"
    ENFERMERIA = "enfermeria"
    ADMINISTRATIVO = "administrativo"
    AUDITOR = "auditor"


@dataclass(frozen=True)
class Usuario:
    """Snapshot de solo lectura de un usuario institucional ya autenticado."""

    id: int
    nombre_usuario: str
    rol: Rol
    activo: bool


@dataclass(frozen=True)
class ResultadoAutenticacion:
    exito: bool
    usuario: Optional[Usuario] = None
    motivo_rechazo: Optional[str] = None
    #: True si el rechazo se debe a que la cuenta está bloqueada temporalmente
    #: (AC2), no a una credencial incorrecta.
    cuenta_bloqueada: bool = False
    bloqueado_hasta: Optional[str] = None


@dataclass(frozen=True)
class ResultadoAutorizacion:
    permitido: bool
    motivo_rechazo: Optional[str] = None
