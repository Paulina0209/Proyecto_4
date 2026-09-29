"""Modelos de dominio de AUD-01 (registro de auditoría de accesos y acciones)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class TipoAccion(str, Enum):
    VER = "ver"
    EDITAR = "editar"
    EXPORTAR = "exportar"


@dataclass(frozen=True)
class EventoAcceso:
    """Snapshot de solo lectura de un evento de acceso ya registrado."""

    id: int
    usuario_id: int
    paciente_id: Optional[int]
    accion: TipoAccion
    fecha: str
    detalle: Optional[str]
