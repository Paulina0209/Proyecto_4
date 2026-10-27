# Registrar la decisión y guardar datos (TX-04)

Se carga desde el paso 8 de `SKILL.md`. Aplica solo cuando el oncólogo ya expresó una decisión explícita en
el chat o pidió guardar datos.

## Decisión final: `registrar_decision_tratamiento`

Nunca la registres sin una decisión explícita del oncólogo (aceptar, modificar o rechazar).

- `tipo_decision="accept"`: **solo** si acepta exactamente el régimen que el sistema sugirió como primera
  opción.
- `tipo_decision="modify"`: si elige un régimen **distinto** del sugerido, aunque sea uno de los otros
  candidatos que la misma tool ya mostró. Usa siempre `modify` con ese `regimen_final_id`; la tool rechaza un
  `accept` con un régimen distinto del sugerido.
  - `regimen_final_id` debe ser uno de los `regimen_id` que ya salieron como candidatos para ese mismo
    paciente. Si el oncólogo pide uno que no está entre ellos, explícale esa limitación en vez de intentarlo.
- `tipo_decision="reject"`: exige `motivo_rechazo` **en las palabras del oncólogo**; nunca lo completes tú.
  Rechazar nunca bloquea nada: siempre se puede registrar si el motivo no está vacío.
- Si el chequeo de interacciones devolvió `requires_justification`, pasa `textos_justificacion` con lo que el
  oncólogo escribió, sin cambiarlo. Si devolvió `blocks_confirmation`, no registres `accept` ni `modify`.

## Datos que quedan guardados y datos que no

Los valores que pasas a `completar_datos_paciente_y_recomendar` **no se guardan**: solo sirven para evaluar.
`chequear_interacciones_tratamiento` y `registrar_decision_tratamiento` leen **solo** lo guardado en el
expediente. Si el oncólogo pide guardar datos, o el siguiente paso los necesita guardados:

- `registrar_datos_clinicos_paciente`: con **exactamente** los valores que dio el oncólogo; nunca agregues ni
  deduzcas ninguno.
- `registrar_conciliacion_medicamentos`: con la lista que dio el oncólogo, o `sin_medicacion_concomitante=true`
  solo si él dijo de forma explícita que no toma ninguno.
- Los biomarcadores (`egfr_status`, `her2_status`, `pdl1_tps`, etc.) no se guardan así: dile que se registran
  con su biopsia o confirmando el biomarcador pendiente.

## Aprobación humana

`registrar_decision_tratamiento`, `registrar_datos_clinicos_paciente` y `registrar_conciliacion_medicamentos`
pausan la conversación y piden aprobación humana explícita antes de ejecutarse. Es intencional (AUD-02/TX-04)
y no es un error. Si ocurre, comunícaselo al oncólogo con naturalidad, como una confirmación final antes de
guardar en el expediente.
