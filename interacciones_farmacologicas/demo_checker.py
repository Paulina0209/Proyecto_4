"""Demo manual de interacciones_farmacologicas -- NO toca guidelines/ ni
docs/rules_interacciones/ real.

Usa un directorio temporal desechable (vía ruta_reglas_interacciones,
el parámetro de override pensado para tests) solo para poder correr
construir_chequeo_interacciones() de punta a punta de forma aislada,
sin escribir nada permanente. Para contenido de prueba PERMANENTE (para
usar con el agente de verdad, vía chat), ver
docs/rules_interacciones/*.yaml -- esos sí quedan cargados de verdad.

Requiere que core/engine.py real esté en el PYTHONPATH (mismo repo) --
checker.py lo importa automáticamente si está disponible.

Uso:
    python -m interacciones_farmacologicas.demo_checker
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import yaml

from interacciones_farmacologicas.checker import construir_chequeo_interacciones

MODULO_DEMO = "demo_modulo_interacciones"

# Contenido de EJEMPLO -- mismo formato que docs/rules_interacciones/*.yaml
# real, pero NUNCA se escribe ahí. Solo vive en un directorio temporal
# mientras corre este script.
REGLAS_DEMO = [
    {
        "id": "DEMO-INT-001",
        "conditions": {
            "all": [
                {"field": "prescribed_antineoplastic_drugs", "operator": "contains", "value": "paclitaxel"},
                {"field": "concomitant_strong_cyp3a4_inducer", "operator": "equals", "value": True},
            ]
        },
        "conclusion": {
            "interaction_id": "paclitaxel_cyp3a4_inducer_demo",
            "concomitant_drug": "inductor fuerte de CYP3A4 (ej. rifampicina)",
            "severity": "major",
            "audit_effect": "requires_justification",
            "description": "Reduce significativamente la exposición a paclitaxel (EJEMPLO, no validado).",
            "recommendation": "Evitar el uso concomitante cuando sea posible.",
            "source": {"titulo": "Ejemplo de demo, no validado clínicamente"},
        },
    },
    {
        "id": "DEMO-INT-002",
        "conditions": {
            "all": [
                {"field": "prescribed_antineoplastic_drugs", "operator": "contains", "value": "pembrolizumab"},
                {"field": "concomitant_qt_prolonging_agent", "operator": "equals", "value": True},
            ]
        },
        "conclusion": {
            "interaction_id": "pembro_qt_demo",
            "concomitant_drug": "agente prolongador del QT",
            "severity": "minor",
            "audit_effect": "informational",
            "description": "Sin interacción farmacocinética directa conocida (EJEMPLO, no validado).",
            "recommendation": "Monitoreo clínico habitual.",
            "source": {"titulo": "Ejemplo de demo, no validado clínicamente"},
        },
    },
    {
        "id": "DEMO-INT-003",
        "conditions": {
            "all": [
                {"field": "prescribed_antineoplastic_drugs", "operator": "contains", "value": "farmaco_ficticio_demo"},
                {"field": "concomitant_qt_prolonging_agent", "operator": "equals", "value": True},
            ]
        },
        "conclusion": {
            "interaction_id": "farmaco_ficticio_qt_contraindicado_demo",
            "concomitant_drug": "agente prolongador del QT",
            "severity": "contraindicated",
            "audit_effect": "blocks_confirmation",
            "description": "Riesgo de arritmia grave (EJEMPLO -- fármaco ficticio, solo para forzar el bloqueo en esta demo).",
            "recommendation": "Contraindicado, no confirmar.",
            "source": {"titulo": "Ejemplo de demo, no validado clínicamente"},
        },
    },
]


def _crear_directorio_reglas_temporal() -> Path:
    raiz = Path(tempfile.mkdtemp(prefix="reglas_interacciones_demo_"))
    with (raiz / f"{MODULO_DEMO}.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump({"rules": REGLAS_DEMO}, f, allow_unicode=True)
    return raiz


def _ejecutar_escenario(titulo: str, ruta_reglas: Path, **kwargs) -> None:
    print(f"\n=== {titulo} ===")
    resultado = construir_chequeo_interacciones(ruta_reglas_interacciones=ruta_reglas, **kwargs)
    print(f"  sin_interacciones_conocidas:        {resultado.sin_interacciones_conocidas}")
    print(f"  requiere_conciliacion_medicamentos: {resultado.requiere_conciliacion_medicamentos}")
    print(f"  advertencia_cobertura_incompleta:   {resultado.advertencia_cobertura_incompleta}")
    print(f"  medicamentos_no_mapeados:           {resultado.medicamentos_no_mapeados}")
    for i in resultado.interacciones:
        print(f"  -> {i.interaccion_id}  [{i.severidad} / {i.audit_effect}]")
        print(f"     {i.descripcion}")


def main() -> None:
    ruta_reglas = _crear_directorio_reglas_temporal()
    try:
        comun = dict(
            paciente_id=1,
            modulo_guia=MODULO_DEMO,
            base_facts={},
        )

        _ejecutar_escenario(
            "1. Capa 0 -- sin conciliar medicación (NUNCA debe decir 'sin interacciones')",
            ruta_reglas,
            regimen_propuesto_id="regimen_paclitaxel_demo",
            regimen_propuesto_drugs=["paclitaxel"],
            medicacion_actual=[],
            conciliacion_medicamentos_estado="no_realizada",
            **comun,
        )

        _ejecutar_escenario(
            "2. Conciliado, sin medicación concomitante -- AQUÍ SÍ debe decir 'sin interacciones'",
            ruta_reglas,
            regimen_propuesto_id="regimen_paclitaxel_demo",
            regimen_propuesto_drugs=["paclitaxel"],
            medicacion_actual=[],
            conciliacion_medicamentos_estado="sin_medicacion_concomitante",
            **comun,
        )

        _ejecutar_escenario(
            "3. Interacción MAYOR (requires_justification) -- rifampicina + paclitaxel",
            ruta_reglas,
            regimen_propuesto_id="regimen_paclitaxel_demo",
            regimen_propuesto_drugs=["paclitaxel"],
            medicacion_actual=["rifampicina"],
            conciliacion_medicamentos_estado="con_medicacion_registrada",
            **comun,
        )

        _ejecutar_escenario(
            "4. Interacción MENOR (informational) -- amiodarona + pembrolizumab",
            ruta_reglas,
            regimen_propuesto_id="regimen_pembro_demo",
            regimen_propuesto_drugs=["pembrolizumab"],
            medicacion_actual=["amiodarona"],
            conciliacion_medicamentos_estado="con_medicacion_registrada",
            **comun,
        )

        _ejecutar_escenario(
            "5. Interacción BLOQUEANTE (blocks_confirmation) -- fármaco ficticio + amiodarona",
            ruta_reglas,
            regimen_propuesto_id="regimen_ficticio_demo",
            regimen_propuesto_drugs=["farmaco_ficticio_demo"],
            medicacion_actual=["amiodarona"],
            conciliacion_medicamentos_estado="con_medicacion_registrada",
            **comun,
        )

        _ejecutar_escenario(
            "6. Capa 1 -- medicamento NO mapeado (nunca debe decir 'sin interacciones')",
            ruta_reglas,
            regimen_propuesto_id="regimen_paclitaxel_demo",
            regimen_propuesto_drugs=["paclitaxel"],
            medicacion_actual=["un_suplemento_no_catalogado"],
            conciliacion_medicamentos_estado="con_medicacion_registrada",
            **comun,
        )

        _ejecutar_escenario(
            "7. Módulo válido, pero SIN archivo de reglas -- disclaimer explícito, nunca 'sin interacciones'",
            ruta_reglas,
            paciente_id=1,
            modulo_guia="modulo_que_no_tiene_archivo_cargado",
            base_facts={},
            regimen_propuesto_id="x",
            regimen_propuesto_drugs=["x"],
            medicacion_actual=[],
            conciliacion_medicamentos_estado="con_medicacion_registrada",
        )
    finally:
        shutil.rmtree(ruta_reglas, ignore_errors=True)


if __name__ == "__main__":
    main()
