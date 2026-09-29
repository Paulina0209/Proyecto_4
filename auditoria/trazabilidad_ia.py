"""AUD-02 — Trazabilidad de recomendaciones de IA.

Como responsable regulatorio, quiero que cada recomendación de IA quede
trazada (versión del motor, fuentes/datos usados, decisión del médico),
para fines de auditoría clínica y legal.

Este componente NO persiste nada nuevo: cada dominio clínico ya registra,
por su lado, un snapshot de lo que sugería el sistema junto con la
decisión del médico --

  - DX-03: ``dx_clinica.juicio_clinico`` (``obtener_historial_juicios``)
  - EST-02: ``estadificacion.confirmacion`` (``obtener_historial_confirmaciones``)
  - TX-04: ``clinical_decision.registro`` (``obtener_historial_decisiones``)

-- siguiendo el mismo patrón de tabla de solo-inserción en los tres casos.
Lo que faltaba (y que las tres implementaciones señalan explícitamente en
sus comentarios como pendiente) era un punto único donde consultar los
tres a la vez para reconstruir, por paciente, "qué sugirió la IA y qué
decidió el médico" sin tener que saber en qué módulo vive cada pieza.
``obtener_trazabilidad_ia_paciente`` es ese punto único de consulta.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RegistroTrazabilidadIA:
    """Una fila unificada de trazabilidad: una recomendación de IA + la
    decisión del médico frente a ella, vinculadas y consultables (criterio
    de aceptación de AUD-02)."""

    dominio: str  # "DX" | "EST" | "TX"
    paciente_id: int
    registrado_en: str
    autor: str
    recomendacion_sistema: Optional[str]
    decision_medico: str
    #: None cuando el dominio no calcula esta comparación (DX-03 nunca
    #: compara el juicio del médico contra la priorización del sistema).
    difiere_de_sugerencia: Optional[bool]
    fuente_id: int


def obtener_trazabilidad_ia_paciente(
    *,
    paciente_id: int,
    conn_dx: Optional[sqlite3.Connection] = None,
    conn_est: Optional[sqlite3.Connection] = None,
    conn_tx: Optional[sqlite3.Connection] = None,
) -> tuple[RegistroTrazabilidadIA, ...]:
    """Historial unificado de recomendaciones de IA + decisión médica de un
    paciente, del más reciente al más antiguo.

    Cada conexión es opcional porque cada dominio vive en su propia base de
    datos/tabla (mismo patrón que ya usan DX-03/EST-02/TX-04 por separado);
    el dominio cuya conexión no se provee simplemente se omite del
    resultado, en vez de fallar.
    """
    registros: list[RegistroTrazabilidadIA] = []

    if conn_dx is not None:
        from dx_clinica.juicio_clinico import obtener_historial_juicios

        for juicio in obtener_historial_juicios(conn_dx, paciente_id):
            registros.append(
                RegistroTrazabilidadIA(
                    dominio="DX",
                    paciente_id=paciente_id,
                    registrado_en=juicio.registrado_en,
                    autor=juicio.autor,
                    recomendacion_sistema=(
                        ", ".join(juicio.perfiles_sugeridos_por_sistema)
                        if juicio.perfiles_sugeridos_por_sistema
                        else None
                    ),
                    decision_medico=juicio.diagnostico_registrado,
                    difiere_de_sugerencia=None,
                    fuente_id=juicio.id,
                )
            )

    if conn_est is not None:
        from estadificacion.confirmacion import obtener_historial_confirmaciones

        for confirmacion in obtener_historial_confirmaciones(conn_est, paciente_id):
            registros.append(
                RegistroTrazabilidadIA(
                    dominio="EST",
                    paciente_id=paciente_id,
                    registrado_en=confirmacion.registrado_en,
                    autor=confirmacion.autor,
                    recomendacion_sistema=confirmacion.estadio_sugerido_por_sistema,
                    decision_medico=confirmacion.estadio_confirmado,
                    difiere_de_sugerencia=(
                        confirmacion.difiere_de_sugerencia
                        if confirmacion.sugerencia_disponible
                        else None
                    ),
                    fuente_id=confirmacion.id,
                )
            )

    if conn_tx is not None:
        from clinical_decision.registro import obtener_historial_decisiones

        for decision in obtener_historial_decisiones(conn_tx, paciente_id):
            if decision.tipo_decision == "reject":
                dif: Optional[bool] = True
                decision_texto = f"rechazado: {decision.motivo_rechazo}"
            elif decision.tipo_decision == "accept":
                dif = False
                decision_texto = decision.regimen_final_id or ""
            else:  # modify
                dif = decision.regimen_final_id != decision.regimen_sugerido_id
                decision_texto = decision.regimen_final_id or ""

            registros.append(
                RegistroTrazabilidadIA(
                    dominio="TX",
                    paciente_id=paciente_id,
                    registrado_en=decision.fecha,
                    autor=str(decision.oncologo_id),
                    recomendacion_sistema=decision.regimen_sugerido_id,
                    decision_medico=decision_texto,
                    difiere_de_sugerencia=dif,
                    fuente_id=decision.id,
                )
            )

    registros.sort(key=lambda r: r.registrado_en, reverse=True)
    return tuple(registros)
