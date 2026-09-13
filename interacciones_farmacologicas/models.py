"""Modelos de dominio para el chequeo de interacciones/contraindicaciones
farmacológicas (historia 'Interacciones/contraindicaciones farmacológicas').

Sigue el mismo patrón que tx_clinica/models.py: dataclasses simples, sin
dependencias externas, sin lógica.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


AuditEffectInteraccion = str  # "blocks_confirmation" | "requires_justification" | "informational"


@dataclass
class InteraccionDetectada:
    interaccion_id: str
    regla_id: str
    severidad: str  # nativa de la fuente citada, nunca normalizada
    audit_effect: AuditEffectInteraccion
    descripcion: str
    recomendacion: str
    fuente: dict  # {"titulo": ..., "anio": ..., "seccion": ...}
    medicamento_concomitante: str


@dataclass
class ResultadoChequeoInteracciones:
    paciente_id: int
    modulo_guia: Optional[str]
    regimen_evaluado: Optional[str]
    interacciones: list[InteraccionDetectada] = field(default_factory=list)
    medicamentos_no_mapeados: list[str] = field(default_factory=list)
    advertencia_cobertura_incompleta: bool = False
    #: True si nadie ha revisado/registrado la medicación concomitante de
    #: este paciente todavía (tabla conciliacion_medicamentos en estado
    #: 'no_realizada' o sin fila). Distinto de "sin interacciones
    #: conocidas": una lista vacía de medicacion_actual es AMBIGUA entre
    #: "se revisó y no toma nada más" y "nadie preguntó" -- este campo
    #: elimina esa ambigüedad en vez de inferirla de la lista vacía.
    requiere_conciliacion_medicamentos: bool = False
    sin_interacciones_conocidas: bool = False
    disclaimer: Optional[str] = None  # p.ej. "SIN_REGLAS_INTERACCION_APLICABLES"

    def requiere_justificacion(self) -> list[InteraccionDetectada]:
        return [i for i in self.interacciones if i.audit_effect == "requires_justification"]

    def bloquea_confirmacion(self) -> list[InteraccionDetectada]:
        return [i for i in self.interacciones if i.audit_effect == "blocks_confirmation"]


@dataclass
class JustificacionContinuacion:
    paciente_id: int
    interaccion_id: str
    regimen_id: Optional[str]
    oncologo_id: int
    texto_justificacion: str
    fecha: str
    id: Optional[int] = None
