# TX-01 — Recomendación de tratamiento y TX-02 — Nivel de evidencia

## Alcance

Implementa TX-01 (recomendación de tratamiento según la guía clínica
configurada, considerando estadio, biomarcadores y comorbilidades) y
TX-02 (nivel de evidencia y fuente exacta por recomendación).

## Diseño

Las reglas computables de `guidelines/` exigen `prescribed_antineoplastic_drugs`
o `prescribed_regimen_id` ya poblados como condición — están escritas
para auditar concordancia, no para generar sugerencias desde cero.

`tx_clinica.builder` evalúa cada régimen conocido de `regimens.yaml` de
forma hipotética contra las reglas del módulo aplicable, usando
`core.engine.evaluate_rule_set_hypothetical` (extensión genérica de
`core/engine.py`, sin nombres de cáncer/fármacos/guías). Ningún régimen
se inventa: solo se consideran los que ya existen en `regimens.yaml`.
Ninguna regla se reescribe.

## Cómo se satisface cada criterio de aceptación

| Criterio de aceptación | Mecanismo en el código |
|---|---|
| (TX-01) Sugerencia alineada con la guía, con razonamiento | `construir_recomendaciones_tratamiento` evalúa cada régimen contra todas las reglas del módulo; cada `RegimenCandidato` expone `rule_id_disparada` y `evidencia`. |
| (TX-01) Comorbilidad que contraindica una opción de primera línea → no se presenta como primera línea, o se presenta con advertencia | Dos mecanismos en `builder.py`: (1) si una comorbilidad bloquea una condición de entrada, se reintenta sin ella — si así calificaría, se marca `requires_clinical_review` con `advertencia_comorbilidad` citando la variable y el valor real; (2) si un régimen calificó pero la regla ganadora nunca revisó una comorbilidad bloqueante presente en el paciente, se degrada igual con advertencia. |
| (TX-01) Sin guía aplicable → se indica explícitamente | `module_selector.seleccionar_modulo` devuelve `None` si ninguna regla de elegibilidad aplica; `sin_guia_aplicable=True` con el mensaje fijo `SIN_GUIA_APLICABLE`. |
| (TX-02) Nivel de evidencia y fuente exacta por opción | `tx_clinica/evidence.py` lee `evidence.native.*` (nivel, grado, MCBS) y `source`/`module_version` directamente de la regla y el módulo. |

## Comorbilidades

`historia_clinica_mock` tiene la tabla `comorbilidades`, con una columna
`condicion` (registro clínico, texto libre, no interpretado por el
sistema) y una columna separada `tipo_contraindicacion_ici`
(`"immediate"` | `"absolute"` | `NULL`), que es el juicio clínico
explícito del oncólogo sobre si esa condición contraindica inmunoterapia.
`tx_clinica/comorbidity_mapping.py` traduce ese juicio ya tomado al
vocabulario de cada módulo (`major_comorbidity_precluding_ici`,
`immune_checkpoint_inhibitor_toxicity_risk`, `ici_suitability`, etc.).

## Agente conversacional

`tx_clinica/agent.py` (LangChain + Ollama local). Las tools
(`obtener_datos_paciente`, `obtener_recomendaciones_tratamiento_por_id`,
`obtener_recomendaciones_tratamiento_con_datos`,
`listar_variables_requeridas`) son wrappers sobre
`builder.py`/`patient_facts.py`; el modelo redacta la respuesta a partir
del JSON que devuelven. Cuando varios módulos podrían aplicar,
`listar_variables_requeridas` devuelve el alcance clínico y un resumen de
evidencia de cada módulo candidato para que el oncólogo elija.

### Limitación observada

Con `qwen2.5:14b-instruct`, en pruebas manuales: (1) en conversaciones
largas el modelo a veces reutiliza el resultado de una tool de un turno
anterior en vez de volver a invocarla; (2) el modelo a veces usa nombres
de variable distintos a los que `listar_variables_requeridas` devolvió.
Mitigado parcialmente en el `_SYSTEM_PROMPT`, no eliminado.

## Alcance de módulos

7 de 9 módulos de `guidelines/` generan sugerencias: `breast_early_tnbc`,
`breast_metastatic_tnbc`, `cutaneous_melanoma`,
`nsclc_early_locally_advanced`, `nsclc_metastatic_non_oncogene`,
`renal_cell_carcinoma_advanced_metastatic`,
`renal_cell_carcinoma_localized_adjuvant`, `uveal_melanoma`.

`sclc_pembrolizumab_review` (sin contenido) y
`nsclc_metastatic_oncogene_addicted` (su `regimens.yaml` se autodeclara
"audit trigger", sin reglas positivas) quedan fuera de alcance —
`module_selector.MODULOS_FUERA_DE_ALCANCE`.

## Formatos de `regimens.yaml`

`regimens.yaml` varía de estructura entre módulos (lista con `includes`,
diccionario con `components`, diccionario con `matching.*`).
`tx_clinica/builder.py` reconoce estas variantes por orden de prioridad;
un régimen en formato no reconocido se excluye, no se adivina.

## Deduplicación por régimen referenciado en conclusión

Varias reglas no condicionan por fármacos, solo por estadio/fase/
elegibilidad. Cuando la conclusión de una regla nombra explícitamente un
régimen (`regimen_id`, `induction_regimen_id`, `maintenance_regimen_id`,
etc.), esa es la respuesta autoritativa — un régimen que se prueba
hipotéticamente solo se acepta si su id coincide con lo que la conclusión
nombra.