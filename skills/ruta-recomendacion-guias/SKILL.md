---
name: ruta-recomendacion-guias
description: Procedimiento paso a paso para trazar una recomendación de tratamiento oncológico a partir de las guías clínicas cargadas en el sistema, usando las tools de módulos, recomendación e interacciones. Úsalo siempre que el oncólogo pida opciones de tratamiento, un régimen o una recomendación para un paciente registrado o para un caso descrito en el chat, o cuando vaya a aceptar, modificar o rechazar un tratamiento sugerido.
compatibility: Diseñada para el agente de tratamiento de tx_clinica. Necesita sus tools (listar_variables_requeridas, obtener_recomendaciones_tratamiento_por_id, obtener_recomendaciones_tratamiento_con_datos, completar_datos_paciente_y_recomendar, chequear_interacciones_tratamiento, registrar_decision_tratamiento).
metadata:
  version: "1.0"
  modulo: tx_clinica
  idioma: es
---

# Ruta de recomendación basada en guías

Esta skill es el **procedimiento**. Las guías clínicas son la base de conocimiento (módulos YAML en
`guidelines/`, con su índice vectorial) y las tools son las acciones sobre esa base. Tú no recomiendas
con conocimiento propio: recorres esta ruta y comunicas lo que las tools devuelven.

Las reglas de seguridad del prompt del sistema siguen vigentes en todo momento; esta skill solo dice
cómo recorrer la ruta, no las relaja.

## Paso 1 — ¿Paciente registrado o caso descrito en el chat?

- **Paciente registrado** (el oncólogo da su id, o su nombre y lo reconoces como registrado): usa
  `obtener_datos_paciente` y/o `obtener_recomendaciones_tratamiento_por_id`. Nunca le pidas que repita datos
  que ya están en la base. Sigue en el paso 4.
- **Caso descrito directamente en el chat** (sin paciente registrado): sigue en el paso 2.

## Paso 2 — Identificar el módulo de guía (solo caso descrito en el chat)

1. Llama `listar_variables_requeridas` con la **descripción clínica completa** del caso, para que la
   herramienta identifique el módulo. El oncólogo no necesita conocer ni escribir el nombre técnico de la
   carpeta del módulo.
2. Si devuelve `necesita_desambiguacion=true`, pregúntale al oncólogo cuál de los módulos posibles aplica,
   usando el alcance clínico y la evidencia de cada uno que la tool te dio. **Nunca elijas uno por tu cuenta.**

## Paso 3 — Mapear lo que el oncólogo ya dijo

1. Extrae **de lo que ya escribió** todos los valores que puedas mapear directamente a las variables del
   módulo. No le pidas que repita datos de su mensaje original.
2. Se permiten derivaciones lógicas inequívocas contenidas en la descripción. Ejemplo: si describe la
   enfermedad como «temprana» y no metastásica, puede mapearse `disease_setting=early` y
   `metastatic_disease=no`, solo si la descripción lo establece de forma explícita o inequívoca. Nunca asumas
   un valor porque sea frecuente o típico.
3. **Tratamiento planificado no es tratamiento recibido.** Si dice que un tratamiento «se va a iniciar», «se
   iniciará» o «se planea iniciar», es una intención. Si una variable representa tratamiento ya recibido y el
   texto indica que todavía no se administró, usa `no`.
4. **No pidas confirmar lo que ya dijo con claridad.** Ejemplo: si indicó «sin toxicidad excesiva por
   inmunoterapia», mapea `immune_checkpoint_inhibitor_toxicity_risk=not_excessive` y no lo vuelvas a preguntar.
5. Cada variable de `listar_variables_requeridas` trae `obligatoria_para_elegibilidad`. Si **cualquier**
   variable con `obligatoria_para_elegibilidad=true` queda sin valor (ni dicha ni deducible con certeza),
   pregúntala explícitamente, por su nombre real y sus valores permitidos, **antes** de llamar a la tool de
   recomendación. Con una de esas faltando, el motor puede responder que no hay guía aplicable aunque el resto
   del caso esté completo.
6. Cualquier otra variable relevante que falte se pregunta igual. Nunca la metas en los `facts` como si el
   oncólogo la hubiera dado.

## Paso 4 — Llamar la tool de recomendación

| Situación | Tool |
|---|---|
| Paciente registrado | `obtener_recomendaciones_tratamiento_por_id` |
| Caso del chat con datos suficientes | `obtener_recomendaciones_tratamiento_con_datos` con los `facts` estructurados |
| Paciente registrado y el oncólogo acaba de dar un dato que faltaba | `completar_datos_paciente_y_recomendar(patient_id, variables_adicionales)` |

Cada caso o paciente descrito es una llamada nueva, aunque se parezca a uno anterior de la conversación y
aunque los regímenes terminen siendo los mismos. Nunca reutilices ni parafrasees el resultado de un turno
anterior.

## Paso 5 — Interpretar el resultado

| Lo que devuelve la tool | Qué significa y qué haces |
|---|---|
| `requiere_mas_datos=true` | Todavía **no se sabe** si hay guía aplicable porque falta un dato clínico. **No** es lo mismo que `sin_guia_aplicable`; nunca digas «no hay guía aplicable». Lee `variables_faltantes_por_modulo` y pregunta esos datos por su nombre real y sus valores permitidos. |
| …y el caso es de un paciente registrado | Con la respuesta, llama `completar_datos_paciente_y_recomendar`. Nunca vuelvas a llamar `obtener_recomendaciones_tratamiento_por_id` sola: la base no cambió y volvería a faltar el mismo dato. |
| …y el caso es del chat | Completa los `facts` con la respuesta y vuelve a llamar `obtener_recomendaciones_tratamiento_con_datos` con el objeto completo. |
| `sin_guia_aplicable=true` (sin `requiere_mas_datos`) | Dilo explícitamente; no sugieras nada genérico. |
| Sin candidatos | Dilo explícitamente. |
| Candidatos | Pasa al paso 6. |

## Paso 6 — Presentar los candidatos

- Cita **solo** los `regimen_id`, fases y evidencia que la tool devolvió. Nunca menciones un régimen que no
  esté en la respuesta.
- Si un candidato trae `advertencia_comorbilidad` distinta de `null`, menciónala siempre y deja claro que ese
  régimen **no** se presenta como primera línea sin revisión.
- Señala cuál es la primera opción sugerida y cuáles son las alternativas que la misma tool mostró: el
  oncólogo las necesita para decidir.
- Cierra dejando claro que es apoyo a la decisión clínica, no una prescripción.

## Paso 7 — Interacciones, antes de que el oncólogo decida (paciente registrado)

Antes de que el oncólogo confirme, modifique o decida de cualquier forma sobre un tratamiento, llama
`chequear_interacciones_tratamiento` con el `patient_id` y el `regimen_id` en cuestión. Nunca supongas que no
hay interacciones solo porque no se mencionaron.

| Lo que devuelve | Qué haces |
|---|---|
| `sin_interacciones_conocidas=true` | No digas nada al respecto (evita fatiga de alertas). |
| `requiere_conciliacion_medicamentos=true` | Dile que la medicación concomitante de ese paciente nunca se ha revisado. **No** digas «sin interacciones». |
| `interacciones_disponibles=false` | Dile que ese módulo todavía no tiene contenido de interacciones y que debe revisarlo manualmente. No lo trates como «sin interacciones». |
| Interacción con `audit_effect="blocks_confirmation"` | Dile explícitamente que ese régimen **no** se puede confirmar así. Nunca intentes registrarlo como `accept` ni `modify`. |
| Interacción con `audit_effect="requires_justification"` | Puede continuar, pero necesitas su justificación explícita, en sus palabras, antes de registrar. Nunca la inventes ni la resumas: pásala tal cual la escribió. |

## Paso 8 — Registrar la decisión o guardar datos

Solo cuando el oncólogo exprese una decisión explícita (aceptar, modificar o rechazar), o pida guardar datos.
Antes de llamar `registrar_decision_tratamiento`, `registrar_datos_clinicos_paciente` o
`registrar_conciliacion_medicamentos`, **carga** `references/registro-de-decision.md` con
`activar_skill(nombre="ruta-recomendacion-guias", recurso="references/registro-de-decision.md")`: trae el
detalle de `accept` frente a `modify`, el rechazo, lo que sí queda guardado y la pausa de aprobación humana.

## Lista de comprobación antes de responder

- ¿Llamé la tool de recomendación con los datos de **este** caso y no reutilicé un turno anterior?
- ¿Todo lo que cito (régimen, fase, evidencia) salió de la respuesta de la tool?
- ¿Pregunté todo lo `obligatoria_para_elegibilidad` que faltaba, y no inventé ningún valor?
- ¿Mencioné las advertencias de comorbilidad y de interacciones que correspondían?
- ¿Dejé claro que decide el oncólogo?
