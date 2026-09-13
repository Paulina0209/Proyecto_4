from .decision_tools import registrar_decision_tratamiento

from .guideline_tools import (
    listar_variables_requeridas,
)

from .recommendation_tools import (
    obtener_recomendaciones_tratamiento_por_id,
    obtener_recomendaciones_tratamiento_con_datos,
    completar_datos_paciente_y_recomendar,
)

from .interaction_tools import (
    consultar_medicacion_actual,
    chequear_interacciones_tratamiento,
)

from .patients_tools import obtener_datos_paciente


TOOLS = [
    obtener_datos_paciente,
    obtener_recomendaciones_tratamiento_por_id,
    completar_datos_paciente_y_recomendar,
    obtener_recomendaciones_tratamiento_con_datos,
    listar_variables_requeridas,
    consultar_medicacion_actual,
    chequear_interacciones_tratamiento,
    registrar_decision_tratamiento,
]