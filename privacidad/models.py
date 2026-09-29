"""Modelos de dominio de NFR-06 (cumplimiento de datos personales)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class EstadoAutorizacion(str, Enum):
    OTORGADA = "otorgada"
    REVOCADA = "revocada"
    DENEGADA = "denegada"


class EstadoSolicitud(str, Enum):
    RECIBIDA = "recibida"
    EN_TRAMITE = "en_tramite"
    ATENDIDA = "atendida"
    RECHAZADA = "rechazada"


ESTADOS_FINALES = frozenset({EstadoSolicitud.ATENDIDA, EstadoSolicitud.RECHAZADA})


@dataclass(frozen=True)
class Finalidad:
    codigo: str
    descripcion: str
    #: Si la política exige una autorización registrada para esta finalidad
    #: (otras pueden ampararse en otra base legal definida por la institución).
    requiere_autorizacion: bool = True


@dataclass(frozen=True)
class PoliticaTratamiento:
    id: int
    codigo: str
    version: int
    jurisdiccion: str
    nombre: str
    marco_normativo: Optional[str]
    finalidades: Tuple[Finalidad, ...]
    bases_legales: Tuple[str, ...]
    derechos: Tuple[str, ...]
    plazo_respuesta_dias: int
    requiere_evidencia_autorizacion: bool
    configurado_por: int
    fecha: str

    def finalidad(self, codigo: str) -> Optional[Finalidad]:
        return next((f for f in self.finalidades if f.codigo == codigo), None)


@dataclass(frozen=True)
class Autorizacion:
    id: int
    paciente_id: int
    politica_id: int
    finalidad: str
    base_legal: str
    estado: EstadoAutorizacion
    medio: Optional[str]
    evidencia_ref: Optional[str]
    registrado_por: int
    fecha: str


@dataclass(frozen=True)
class EventoSolicitud:
    id: int
    solicitud_id: int
    estado: EstadoSolicitud
    detalle: Optional[str]
    usuario_id: int
    fecha: str


@dataclass(frozen=True)
class SolicitudDerechos:
    id: int
    paciente_id: int
    politica_id: int
    tipo_derecho: str
    descripcion: str
    solicitante: str
    fecha_recepcion: str
    fecha_limite: str
    registrado_por: int
    estado: EstadoSolicitud
    historial: Tuple[EventoSolicitud, ...]
    #: True si sigue abierta y ya pasó su fecha límite.
    vencida: bool


@dataclass(frozen=True)
class ResultadoOperacion:
    exito: bool
    registro: Any = None
    motivo_rechazo: Optional[str] = None


@dataclass(frozen=True)
class DecisionTratamientoDatos:
    """¿Se puede tratar el dato de este paciente para esta finalidad?"""

    permitido: bool
    motivo: str
    #: Registro que respalda la decisión (None si no hay ninguno).
    autorizacion: Optional[Autorizacion] = None


@dataclass(frozen=True)
class InformacionTitular:
    """Todo lo que el sistema tiene del titular, para atender una solicitud de derechos."""

    paciente_id: int
    generado_en: str
    #: {"origen.tabla": [filas como dict]}
    secciones: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)

    @property
    def total_registros(self) -> int:
        return sum(len(filas) for filas in self.secciones.values())

    def a_json(self) -> str:
        """Formato estructurado y portable para entregar al titular."""
        return json.dumps(
            {"paciente_id": self.paciente_id, "generado_en": self.generado_en, "secciones": self.secciones},
            ensure_ascii=False,
            indent=2,
            default=str,
        )
