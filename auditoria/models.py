"""Modelos de dominio de AUD-01 (registro de auditoría de accesos y acciones)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class TipoAccion(str, Enum):
    VER = "ver"
    EDITAR = "editar"
    EXPORTAR = "exportar"
    # NFR-06: acciones sobre políticas, autorizaciones y derechos del titular.
    CONFIGURAR_POLITICA_DATOS = "configurar_politica_datos"
    REGISTRAR_AUTORIZACION = "registrar_autorizacion"
    GESTIONAR_DERECHOS_TITULAR = "gestionar_derechos_titular"
    # CFG-01: cambio de las guías clínicas institucionales por defecto.
    CONFIGURAR_GUIAS = "configurar_guias"


@dataclass(frozen=True)
class EventoAcceso:
    """Snapshot de solo lectura de un evento de acceso ya registrado."""

    id: int
    usuario_id: int
    paciente_id: Optional[int]
    accion: TipoAccion
    fecha: str
    detalle: Optional[str]
