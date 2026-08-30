# DX-03 — Manejo de la incertidumbre diagnóstica y juicio clínico

## Alcance de esta implementación

Este documento describe el diseño de `dx_clinica.incertidumbre` y
`dx_clinica.juicio_clinico`, que implementan la historia de usuario
**DX-03** del backlog (épica Diagnóstico):

> Como oncólogo, quiero que el sistema identifique cuándo la información
> clínica disponible es insuficiente para establecer una priorización
> confiable de diagnósticos diferenciales, para poder reconocer la
> incertidumbre y decidir qué información adicional considerar.

DX-03 depende formalmente de DX-02, HC-02 y HC-04. DX-02 ya está
implementado en este repositorio (`dx_clinica.builder`); HC-02
(laboratorios) y HC-04 (biomarcadores) siguen cubiertos, como en DX-02,
por `historia_clinica_mock`. DX-03 no vuelve a tocar ninguno de esos dos
componentes: es una capa que **analiza** el `ResultadoDiagnosticoDiferencial`
que ya produce DX-02, y una capa separada que **registra** el juicio del
médico — ninguna de las dos modifica `dx_clinica.builder`.

## Dos partes independientes

La historia tiene, en la práctica, dos mecanismos distintos que conviene
no confundir:

1. **`dx_clinica.incertidumbre`** (AC1, AC2, AC3): analiza si la
   priorización de DX-02 merece una advertencia explícita de
   incertidumbre, y si es así, qué información adicional podría ayudar.
   Es de solo lectura: nunca modifica el resultado de DX-02.
2. **`dx_clinica.juicio_clinico`** (AC4, AC5): permite que el médico
   registre su propio juicio diagnóstico — de acuerdo o no con el
   sistema — y hace que ese juicio sea lo que se considera vigente de
   ahí en adelante. Es un mecanismo de persistencia (SQLite), independiente
   del análisis de incertidumbre.

## Cómo se satisface cada criterio de aceptación

| Criterio de aceptación | Mecanismo en el código |
|---|---|
| El sistema comunica explícitamente la presencia de incertidumbre | `incertidumbre.analizar_incertidumbre()` devuelve `AnalisisIncertidumbre.hay_incertidumbre` (booleano explícito) y `.mensaje` (texto explicativo, nunca un simple `False` silencioso). |
| Indica qué información adicional podría ayudar a diferenciar entre alternativas | `AnalisisIncertidumbre.informacion_adicional_sugerida`: los `criterios_sin_sustento` de la(s) alternativa(s) líder(es), o — si no hay ningún candidato — los criterios de todo el catálogo disponible. Siempre acompañado de `disclaimer_sugerencias`. |
| No fuerza una priorización artificial cuando falta información | `analizar_incertidumbre()` es puramente analítico: nunca modifica, reordena, ni rellena `resultado.candidatos`. Cuando hay empate, ambas alternativas quedan intactas en el resultado original — el análisis solo lo señala, no lo "resuelve" a la fuerza. Cuando no hay ningún candidato, `resultado.candidatos` sigue siendo `()`. |
| El juicio del médico se conserva sin bloquearlo ni sobreescribirlo | `juicio_clinico.registrar_juicio_clinico()` nunca compara `diagnostico_registrado` contra la priorización del sistema — la única validación es de forma (texto y autor no vacíos), nunca de contenido/concordancia. |
| La decisión del médico prevalece como juicio clínico final | `juicio_clinico.obtener_decision_diagnostica_vigente()` devuelve `fuente="juicio_medico"` con el contenido del médico siempre que exista un juicio registrado, sin importar qué sugiera `resultado_sistema` en ese momento. |

## Los tres tipos de incertidumbre (nota técnica de DX-03)

La nota técnica pide distinguir entre información faltante, información
contradictoria, e incertidumbre inherente al caso. Se implementan como
tres señales distintas y verificables, cada una detectada a partir de una
parte distinta del resultado de DX-02:

- **`INFORMACION_FALTANTE`**: la alternativa líder tiene
  `criterios_sin_sustento` — hay un hueco conocido y nombrable en el
  expediente. Es el caso directo de "más información podría ayudar".
- **`AMBIGUEDAD_ENTRE_ALTERNATIVAS`**: dos o más alternativas quedan
  empatadas exactamente en el primer lugar (mismo número de criterios
  sustentados y mismo número total de criterios del perfil). Esta es la
  interpretación que usa este proyecto de "información contradictoria":
  la evidencia disponible sustenta por igual a más de una alternativa,
  sin ningún hallazgo que las distinga. **Límite de alcance explícito:**
  no se detectan contradicciones literales entre valores clínicos (por
  ejemplo, dos resultados de laboratorio incompatibles para la misma
  prueba) — eso requeriría un modelo de datos clínicos más rico del que
  tiene `historia_clinica_mock` hoy. Se documenta esta limitación en vez
  de fingir una detección de contradicciones que no existe.
- **`INCERTIDUMBRE_INHERENTE_AL_CASO`**: la alternativa líder pertenece a
  un perfil diagnóstico con muy pocos criterios definidos en total
  (umbral configurable, `minimo_criterios_perfil_confiable`, por defecto
  2). Aquí el problema no es un dato puntual faltante — es que el perfil
  mismo es demasiado poco específico para sostener una conclusión con
  confianza, sin importar qué tan completo esté el expediente. Pedir más
  información del mismo tipo no reduce esta incertidumbre, por eso se
  distingue de `INFORMACION_FALTANTE`. Ejemplo real del catálogo actual:
  `toxicidad_hepatica_tratamiento` se define con un solo criterio
  (enzimas hepáticas alteradas), que por sí solo es compatible con muchas
  causas distintas a la toxicidad por tratamiento.

Un mismo análisis puede reportar varios tipos a la vez (por ejemplo, un
perfil de un solo criterio que además todavía no está sustentado).

## Por qué las sugerencias nunca son "órdenes"

La nota técnica es explícita: "las sugerencias de información adicional
deben presentarse como elementos que podrían aportar al razonamiento
diagnóstico y no como órdenes clínicas automáticas". Por eso
`AnalisisIncertidumbre` nunca expone una lista llamada algo como
`examenes_a_solicitar` ni genera ningún objeto con forma de orden médica:
solo reutiliza las descripciones de criterios clínicos ya existentes en
`dx_clinica.knowledge_base` (texto descriptivo, no una acción), y siempre
las acompaña de `disclaimer_sugerencias`, un texto fijo que aclara
explícitamente que no son instrucciones automáticas y que la decisión de
qué buscar sigue siendo del oncólogo.

## Por qué el juicio del médico se persiste en SQLite y es de solo-inserción

Igual que en IA-03, demostrar "el juicio del médico prevalece" de forma
convincente requiere que ese juicio sobreviva más allá de un objeto en
memoria de una sola llamada. `dx_clinica/schema_juicio_clinico.sql`
define una tabla independiente (`juicios_clinicos_dx`) en la que nunca se
hace `UPDATE`, solo `INSERT`: un paciente puede acumular varios juicios a
lo largo del tiempo (por ejemplo, en distintas consultas de seguimiento),
y el "vigente" es siempre el más reciente
(`obtener_juicio_vigente`/`obtener_decision_diagnostica_vigente`). Esto
evita necesitar una operación de "corregir" o "deshacer" un juicio ya
registrado, y conserva el historial completo para auditoría
(`obtener_historial_juicios`) sin que un juicio nuevo borre el anterior.

`resultado_sistema` se guarda únicamente como contexto de auditoría (qué
sugería el sistema en el momento del juicio) — nunca se usa para validar,
bloquear, ni advertir en contra del juicio del médico.

## Componentes

- `dx_clinica/incertidumbre.py`: `TipoIncertidumbre`,
  `AnalisisIncertidumbre`, `analizar_incertidumbre()`,
  `DISCLAIMER_SUGERENCIAS`.
- `dx_clinica/juicio_clinico.py` + `schema_juicio_clinico.sql`:
  `JuicioClinico`, `DecisionDiagnosticaVigente`,
  `registrar_juicio_clinico()`, `obtener_juicio_vigente()`,
  `obtener_historial_juicios()`, `obtener_decision_diagnostica_vigente()`.
- `dx_clinica/demo_incertidumbre.py`: cuatro escenarios construidos a
  mano (uno por cada combinación relevante de tipos de incertidumbre, más
  el caso sin incertidumbre) y un caso real (Carlos, NSCLC) para mostrar
  el registro de un juicio médico que prevalece sobre la sugerencia del
  sistema.

## Cómo probarlo

```
python -m dx_clinica.demo_incertidumbre
pytest tests/dx_clinica/test_incertidumbre.py tests/dx_clinica/test_juicio_clinico.py -v
```

## Fuera de alcance de esta historia

- **Detección de contradicciones clínicas literales** (dos valores de
  datos que se contradicen entre sí): requeriría enriquecer el modelo de
  datos de `historia_clinica_mock`; ver limitación documentada arriba.
- **Notificar automáticamente al médico** cuando se detecta incertidumbre
  (por ejemplo, una alerta push): esta historia solo genera el análisis y
  lo deja disponible para quien consuma `dx_clinica`; el canal de
  notificación es una decisión de una capa de presentación que no existe
  todavía en este repositorio.
- **Editar o retractar un juicio clínico ya registrado**: a propósito no
  existe (ver diseño append-only arriba) — el médico registra uno nuevo
  en su lugar, y ese pasa a prevalecer.
