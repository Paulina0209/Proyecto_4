"""Middleware de aprobación humana -- TX-04.

La regla de negocio de TX-04 ("la decisión clínica es del médico, no del
sistema") deja de depender solo del prompt (que ya sabemos que
qwen2.5:14b no sigue de forma confiable -- ver bugs reales documentados
en el resumen del proyecto: reutiliza turnos anteriores, inventa
variables) y pasa a ser una garantía ESTRUCTURAL del grafo: aunque el
modelo decida por su cuenta llamar a registrar_decision_tratamiento, la
ejecución se pausa y espera una aprobación humana real antes de escribir
nada en la base de datos.

Requiere un checkpointer en create_agent() (ver agent.py) -- sin eso,
HumanInTheLoopMiddleware no tiene dónde guardar el estado para poder
pausar y reanudar.
"""

from __future__ import annotations

from langchain.agents.middleware import HumanInTheLoopMiddleware

#: Solo las tools que ESCRIBEN una decisión clínica van acá. Las de solo
#: lectura (obtener_datos_paciente, obtener_recomendaciones_tratamiento_*,
#: chequear_interacciones_tratamiento, consultar_medicacion_actual,
#: listar_variables_requeridas, completar_datos_paciente_y_recomendar)
#: NO requieren aprobación -- pausar para aprobar una consulta sería
#: fricción sin ningún beneficio de seguridad.
TOOLS_QUE_REQUIEREN_APROBACION_HUMANA = {
    # True = se permiten las 3 decisiones (approve/edit/reject) -- tiene
    # sentido que el oncólogo pueda, desde la misma pausa, corregir un
    # argumento mal interpretado (ej. tipo_decision incorrecto) en vez de
    # solo aprobar o rechazar en bloque.
    "registrar_decision_tratamiento": True,
}


def construir_middleware_aprobacion_humana() -> HumanInTheLoopMiddleware:
    return HumanInTheLoopMiddleware(
        interrupt_on=TOOLS_QUE_REQUIEREN_APROBACION_HUMANA,
        description_prefix="Decisión de tratamiento pendiente de aprobación del oncólogo",
    )
