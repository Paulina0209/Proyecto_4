"""registrar_decision_tratamiento() -- TX-04.

Envuelve (no reemplaza) auditoria_clinica_extension.justificaciones.
confirmar_tratamiento: ese sigue siendo el mecanismo de bajo nivel para
"¿puedo confirmar este régimen dado el chequeo de interacciones?". Esta
función es la capa de arriba que decide CUÁNDO llamarlo (solo en
accept/modify, nunca en reject) y agrega el tercer camino que antes no
existía.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from tx_clinica.justificaciones import confirmar_tratamiento
from clinical_decision.models import DecisionTratamiento, ResultadoRegistroDecision

_TIPOS_VALIDOS = {"accept", "modify", "reject"}


def inicializar_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS decisiones_tratamiento (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente_id INTEGER NOT NULL,
            oncologo_id INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            tipo_decision TEXT NOT NULL,
            regimen_sugerido_id TEXT,
            regimen_final_id TEXT,
            motivo_rechazo TEXT,
            recomendacion_ia_snapshot TEXT NOT NULL,
            justificaciones_ids TEXT NOT NULL DEFAULT '[]'
        )
        """
    )
    # C4/S5: decisiones_tratamiento es un registro de auditoría -- estos
    # triggers son la garantía real de que es append-only (antes solo era
    # una convención documentada en el docstring de models.py, sin nada
    # que impidiera un UPDATE o DELETE directo sobre la tabla).
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS decisiones_tratamiento_no_update
        BEFORE UPDATE ON decisiones_tratamiento
        BEGIN SELECT RAISE(ABORT, 'decisiones_tratamiento es append-only'); END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS decisiones_tratamiento_no_delete
        BEFORE DELETE ON decisiones_tratamiento
        BEGIN SELECT RAISE(ABORT, 'decisiones_tratamiento es append-only'); END
        """
    )
    conn.commit()


def _persistir(conn: sqlite3.Connection, decision: DecisionTratamiento) -> DecisionTratamiento:
    cursor = conn.execute(
        """
        INSERT INTO decisiones_tratamiento
            (paciente_id, oncologo_id, fecha, tipo_decision, regimen_sugerido_id,
             regimen_final_id, motivo_rechazo, recomendacion_ia_snapshot, justificaciones_ids)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            decision.paciente_id,
            decision.oncologo_id,
            decision.fecha,
            decision.tipo_decision,
            decision.regimen_sugerido_id,
            decision.regimen_final_id,
            decision.motivo_rechazo,
            json.dumps(decision.recomendacion_ia_snapshot, ensure_ascii=False),
            json.dumps(decision.justificaciones_ids),
        ),
    )
    # C4: sin commit aquí a propósito -- el commit es responsabilidad de
    # quien orquesta la transacción completa (registrar_decision_tratamiento,
    # más abajo), para que una decisión y sus justificaciones (si las hay)
    # se confirmen o se reviertan juntas, nunca a medias.
    decision.id = cursor.lastrowid
    return decision


def registrar_decision_tratamiento(
    conn: sqlite3.Connection,
    paciente_id: int,
    oncologo_id: int,
    tipo_decision: str,
    recomendacion_ia_snapshot: dict,
    regimenes_candidatos_ids: list[str],
    regimen_sugerido_id: Optional[str],
    regimen_final_id: Optional[str] = None,
    motivo_rechazo: Optional[str] = None,
    chequeo_interacciones=None,  # interacciones_clinica.models.ResultadoChequeoInteracciones
    textos_justificacion: Optional[dict[str, str]] = None,
) -> ResultadoRegistroDecision:
    """
    regimenes_candidatos_ids: los regimen_id de TODOS los candidatos que
        builder.py evaluó para este paciente (viene del mismo resultado
        que ya se le mostró al oncólogo) -- en "modify",
        regimen_final_id DEBE estar en esta lista, decisión ya cerrada
        con el usuario.
    chequeo_interacciones: el resultado de
        interacciones_clinica.checker.construir_chequeo_interacciones,
        YA CALCULADO para el régimen que efectivamente se va a confirmar
        (el sugerido en "accept", el elegido en "modify") -- esta función
        no lo recalcula, así decision_clinica no depende de los
        detalles de cómo se resuelve un chequeo de interacciones.
    """
    ahora = datetime.now(timezone.utc).isoformat()

    if tipo_decision not in _TIPOS_VALIDOS:
        return ResultadoRegistroDecision(
            exito=False, motivo_rechazo=f"tipo_decision inválido: {tipo_decision!r}"
        )

    # C4: todo lo que sigue escribe en la base (la decisión y, si aplica,
    # sus justificaciones) dentro de UNA sola transacción -- o se
    # confirman juntas con un único commit al final, o ante cualquier
    # error se revierte todo con rollback. Antes cada INSERT hacía su
    # propio commit, así que un fallo a mitad de camino podía dejar
    # justificaciones guardadas sin la decisión que las originó.
    try:
        if tipo_decision == "reject":
            # AC2: no pasa por el gate de interacciones, no bloquea nada.
            # Solo exige que el motivo no esté vacío.
            if not (motivo_rechazo or "").strip():
                return ResultadoRegistroDecision(
                    exito=False, motivo_rechazo="Falta el motivo del rechazo."
                )
            decision = DecisionTratamiento(
                paciente_id=paciente_id,
                oncologo_id=oncologo_id,
                fecha=ahora,
                tipo_decision="reject",
                regimen_sugerido_id=regimen_sugerido_id,
                motivo_rechazo=motivo_rechazo.strip(),
                recomendacion_ia_snapshot=recomendacion_ia_snapshot,
            )
            decision = _persistir(conn, decision)
            conn.commit()
            return ResultadoRegistroDecision(exito=True, decision=decision)

        # accept / modify: ambos terminan prescribiendo algo, ambos pasan por
        # el mismo gate de interacciones (AUD-02).
        if tipo_decision == "accept":
            regimen_final_id = regimen_sugerido_id
            if not regimen_final_id:
                return ResultadoRegistroDecision(
                    exito=False,
                    motivo_rechazo="No hay ningún régimen sugerido por la IA para aceptar.",
                )
        else:  # modify
            if not regimen_final_id:
                return ResultadoRegistroDecision(
                    exito=False, motivo_rechazo="Falta el régimen final para 'modify'."
                )
            if regimen_final_id not in regimenes_candidatos_ids:
                return ResultadoRegistroDecision(
                    exito=False,
                    motivo_rechazo=(
                        f"'{regimen_final_id}' no es uno de los regímenes ya evaluados para "
                        "este paciente. En 'modify' el régimen final debe ser uno de los "
                        "candidatos de regimens.yaml que el sistema ya evaluó -- no un "
                        "régimen arbitrario (límite conocido de esta historia)."
                    ),
                )

        if chequeo_interacciones is None:
            return ResultadoRegistroDecision(
                exito=False,
                motivo_rechazo=(
                    "Falta ejecutar chequear_interacciones_tratamiento para el régimen "
                    "final antes de poder registrar esta decisión."
                ),
            )

        # C2: el chequeo de interacciones que se pasa debe corresponder al
        # MISMO paciente y al MISMO régimen que se va a confirmar -- sin
        # esto, un chequeo de otro régimen (o de otro paciente) habilitaría
        # una confirmación que nunca se validó de verdad. Defensa en
        # profundidad: esto es justo lo que habría frenado el bug real
        # donde "accept" terminó confirmando un régimen distinto al que el
        # chequeo de interacciones había evaluado.
        if (
            getattr(chequeo_interacciones, "regimen_evaluado", None) != regimen_final_id
            or getattr(chequeo_interacciones, "paciente_id", paciente_id) != paciente_id
        ):
            return ResultadoRegistroDecision(
                exito=False,
                motivo_rechazo=(
                    "El chequeo de interacciones no corresponde al paciente/régimen que se "
                    "va a confirmar. Vuelve a ejecutar chequear_interacciones_tratamiento "
                    f"para patient_id={paciente_id} y regimen_id='{regimen_final_id}'."
                ),
            )

        resultado_confirmacion = confirmar_tratamiento(
            conn, chequeo_interacciones, oncologo_id, textos_justificacion
        )
        if not resultado_confirmacion.confirmado:
            conn.rollback()
            return ResultadoRegistroDecision(
                exito=False, motivo_rechazo=resultado_confirmacion.motivo_rechazo
            )

        decision = DecisionTratamiento(
            paciente_id=paciente_id,
            oncologo_id=oncologo_id,
            fecha=ahora,
            tipo_decision=tipo_decision,
            regimen_sugerido_id=regimen_sugerido_id,
            regimen_final_id=regimen_final_id,
            recomendacion_ia_snapshot=recomendacion_ia_snapshot,
            justificaciones_ids=[
                j.id for j in (resultado_confirmacion.justificaciones_registradas or []) if j.id is not None
            ],
        )
        decision = _persistir(conn, decision)
        conn.commit()
        return ResultadoRegistroDecision(exito=True, decision=decision)
    except Exception:
        conn.rollback()
        raise
