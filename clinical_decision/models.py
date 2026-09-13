"""Modelos de dominio de TX-04 (decisión final del oncólogo).

Ver docs/interacciones_farmacologicas.md y el plan de continuidad,
sección 6, para el diseño completo ya cerrado con el usuario:
  - "accept": regimen_final_id = el que la IA sugirió, automático.
  - "modify": regimen_final_id DEBE ser uno de los candidatos que
    builder.py ya evaluó (regimens.yaml del módulo) -- nunca un régimen
    arbitrario. Decisión cerrada explícitamente para que el chequeo de
    interacciones de TX-03 SIEMPRE pueda correr, sin casos "régimen
    desconocido".
  - "reject": no pasa por el gate de interacciones (AC2: no bloquea
    nada), solo exige motivo_rechazo no vacío.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DecisionTratamiento:
    paciente_id: int
    oncologo_id: int
    fecha: str
    tipo_decision: str  # "accept" | "modify" | "reject"

    #: Snapshot INMUTABLE de lo que el sistema mostró en el momento de la
    #: decisión (candidatos evaluados + evidencia citada de TX-01/TX-02).
    #: Es lo que sostiene la regla de negocio de auditoría: si
    #: guidelines/ cambia después, este registro histórico no cambia de
    #: significado retroactivamente.
    recomendacion_ia_snapshot: dict = field(default_factory=dict)

    #: El régimen que la IA sugirió como primera opción (puede ser None
    #: si sin_guia_aplicable/candidatos vacío -- el oncólogo igual puede
    #: rechazar o, en teoría, "modify" si hay otros candidatos no
    #: primarios).
    regimen_sugerido_id: Optional[str] = None

    #: Solo poblado si tipo_decision in ("accept", "modify").
    regimen_final_id: Optional[str] = None

    #: Solo poblado si tipo_decision == "reject".
    motivo_rechazo: Optional[str] = None

    #: ids de justificaciones_continuacion (AUD-02) generadas al
    #: confirmar, si el chequeo de interacciones exigió alguna.
    justificaciones_ids: list[int] = field(default_factory=list)

    id: Optional[int] = None


@dataclass
class ResultadoRegistroDecision:
    exito: bool
    decision: Optional[DecisionTratamiento] = None
    #: Motivo por el que NO se pudo registrar (tipo_decision inválido,
    #: falta motivo_rechazo, régimen fuera de los candidatos evaluados,
    #: interacción bloqueante, falta justificación...). None si exito=True.
    motivo_rechazo: Optional[str] = None