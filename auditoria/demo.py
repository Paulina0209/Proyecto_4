"""Demo de AUD-01 (log de accesos) y AUD-02 (trazabilidad de recomendaciones de IA).

Ejecutar: python -m auditoria.demo
"""

from __future__ import annotations

from auditoria.models import TipoAccion
from auditoria.registro_acceso import crear_conexion, obtener_eventos_de_paciente, registrar_acceso
from auditoria.trazabilidad_ia import obtener_trazabilidad_ia_paciente
from clinical_decision.registro import crear_conexion as crear_conexion_tx
from clinical_decision.registro import registrar_decision_tratamiento
from dx_clinica.juicio_clinico import crear_conexion as crear_conexion_dx
from dx_clinica.juicio_clinico import registrar_juicio_clinico
from estadificacion.confirmacion import confirmar_estadificacion
from estadificacion.confirmacion import crear_conexion as crear_conexion_est


def main() -> None:
    print("=" * 78)
    print("AUD-01 — REGISTRO DE AUDITORÍA DE ACCESOS Y ACCIONES")
    print("=" * 78)

    conn_aud = crear_conexion(":memory:")
    registrar_acceso(
        conn_aud, usuario_id=10, accion=TipoAccion.VER, paciente_id=1,
        detalle="Apertura del expediente desde el dashboard 360°.",
    )
    registrar_acceso(
        conn_aud, usuario_id=10, accion=TipoAccion.EDITAR, paciente_id=1,
        detalle="Ajuste manual de estadificación (EST-02).",
    )
    registrar_acceso(
        conn_aud, usuario_id=99, accion=TipoAccion.EXPORTAR, paciente_id=1,
        detalle="Exportación de resumen a PDF.",
    )

    for evento in obtener_eventos_de_paciente(conn_aud, paciente_id=1):
        print(f"[{evento.fecha}] usuario={evento.usuario_id} accion={evento.accion.value} -- {evento.detalle}")

    print("\n" + "=" * 78)
    print("AUD-02 — TRAZABILIDAD DE RECOMENDACIONES DE IA (vista unificada DX + EST + TX)")
    print("=" * 78)

    conn_dx = crear_conexion_dx(":memory:")
    conn_est = crear_conexion_est(":memory:")
    conn_tx = crear_conexion_tx(":memory:")

    registrar_juicio_clinico(
        conn_dx, paciente_id=1,
        diagnostico_registrado="Carcinoma ductal infiltrante, sin metástasis a distancia.",
        autor="dra. Gómez",
    )
    confirmar_estadificacion(
        conn_est, paciente_id=1, estadio_confirmado="IIIA", autor="dra. Gómez",
        justificacion="Reevaluación de ganglios en junta multidisciplinaria.",
    )
    registrar_decision_tratamiento(
        conn_tx,
        paciente_id=1,
        oncologo_id=10,
        tipo_decision="reject",
        recomendacion_ia_snapshot={"modulo": "breast_early_tnbc"},
        regimenes_candidatos_ids=[],
        regimen_sugerido_id="AC-T",
        motivo_rechazo="Paciente con neuropatía previa; se prefiere un esquema alternativo evaluado en junta.",
    )

    for registro in obtener_trazabilidad_ia_paciente(
        paciente_id=1, conn_dx=conn_dx, conn_est=conn_est, conn_tx=conn_tx
    ):
        print(
            f"[{registro.dominio}] {registro.registrado_en} autor={registro.autor} | "
            f"sugerido_ia={registro.recomendacion_sistema!r} -> decision_medico={registro.decision_medico!r} "
            f"(difiere={registro.difiere_de_sugerencia})"
        )


if __name__ == "__main__":
    main()
