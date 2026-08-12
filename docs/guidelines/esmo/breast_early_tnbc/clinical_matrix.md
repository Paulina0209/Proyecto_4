# Matriz clínica: ESMO TNBC temprano (cáncer de mama triple negativo, enfermedad temprana/localmente avanzada)

## Estado

Borrador computable pendiente de validación clínica. Basado en: *Early breast
cancer: ESMO Clinical Practice Guideline for diagnosis, treatment and
follow-up* (Ann Oncol, 2024), sección "TNBC" y las recomendaciones generales
de diagnóstico que aplican a este subtipo (biomarcadores, PD-L1, BRCA
germinal). Solo se incluyen reglas del subtipo triple negativo; DCIS y otros
subtipos (luminal, HER2-positivo) son módulos separados.

## Inventario de reglas — elegibilidad y diagnóstico

| ID | Escenario | Consecuente | Evidencia nativa | Efecto de auditoría |
|---|---|---|---|---|
| ELI-001 | TNBC confirmado, candidata a olaparib adyuvante o cumple criterios nacionales de riesgo hereditario | Ofrecer test germinal BRCA1/2 y consejo genético | I, A; ESCAT I-A | Respalda |
| ELI-002 | TNBC, cualquier estatus PD-L1 | El PD-L1 NO debe usarse para decisiones de tratamiento en enfermedad temprana | I, E | Excluye el uso de PD-L1 como criterio |
| ELI-003 | TNBC, histología adenoide quística o secretora, o pT1a pN0 | Beneficio de ChT adyuvante no establecido / mínimo | II, B | Respalda omisión de ChT |
| ELI-004 | TNBC, pT1b pN0 | Beneficio de ChT adyuvante incierto | Sin grado explícito | Revisión |

## Inventario de reglas — fase neoadyuvante

| ID | Escenario | Consecuente | Evidencia nativa | Efecto de auditoría |
|---|---|---|---|---|
| NEO-001 | cT1c-4 N0, o cualquier N-positivo | Neoadyuvancia preferida sobre cirugía primaria | I, A | Respalda |
| NEO-002 | cT2-4 N0, o cualquier N-positivo (estadio clínico II-III), sin riesgo excesivo de toxicidad por ICI | ChT (antraciclina-taxano o taxano-carboplatino) + pembrolizumab | I, A; MCBS A | Respalda |
| NEO-003 | Fase neoadyuvante en curso con pembrolizumab indicado | Pembrolizumab cada 3 semanas durante toda la fase neoadyuvante | I, A | Respalda |
| NEO-004 | ChT neoadyuvante o adyuvante indicada | Esquemas dose-dense con soporte de G-CSF | I, A | Respalda |
| NEO-005 | ChT indicada (con o sin ICI) | Duración 12-24 semanas (4-8 ciclos) | I, A | Respalda |

## Inventario de reglas — fase adyuvante / manejo de enfermedad residual

| ID | Escenario | Consecuente | Evidencia nativa | Efecto de auditoría |
|---|---|---|---|---|
| ADJ-001 | Pembrolizumab recibido en neoadyuvancia (independiente del estatus de pCR) | Pembrolizumab adyuvante, 9 ciclos de 3 semanas | I, A; MCBS A | Respalda |
| ADJ-002 | gBRCA1/2 mutado, alto riesgo (no-pCR o estadio patológico II-III) | Olaparib adyuvante durante 1 año | I, A; MCBS A; ESCAT I-A | Respalda |
| ADJ-003 | Enfermedad residual (no-pCR), no recibió ICI | Capecitabina adyuvante, 6-8 ciclos | I, A | Respalda |
| ADJ-004 | gBRCA1/2 mutado, capecitabina y olaparib combinados | Combinación no recomendada | V, C | Posible desviación |
| ADJ-005 | ICI y capecitabina combinados | Puede considerarse de forma individual; sin datos de eficacia establecidos | Sin grado explícito | Revisión |

## Inventario de reglas — exclusión y continuación

| ID | Escenario | Consecuente | Evidencia nativa | Efecto de auditoría |
|---|---|---|---|---|
| EXC-001 | ICI prescrito solo en fase adyuvante, sin ICI neoadyuvante previo | No respaldado | V, D | Posible desviación |
| CONT-001 | Pembrolizumab adyuvante en curso | Vigilar toxicidad inmunorrelacionada según guía ESMO de manejo de toxicidad por inmunoterapia | V, A | Aviso |
| CONT-002 | Olaparib adyuvante en curso | Duración total planificada: 1 año | I, A | Aviso |

## Decisiones metodológicas

- Estructura por **fase** (neoadyuvante / adyuvante), no por línea de
  tratamiento, a diferencia del módulo metastásico.
- El PD-L1 se modela explícitamente como un campo que **no debe** activar ni
  bloquear ninguna regla en este módulo (a diferencia de mTNBC, donde sí es
  determinante); es una exclusión, no una ausencia de dato.
- El gate de ICI adyuvante depende de haber recibido ICI en neoadyuvancia,
  no del estatus de pCR: el estatus de pCR determina la adyuvancia
  citotóxica/PARPi adicional, no la continuidad del pembrolizumab.
- Las reglas de clase se identifican como `class_level`.
- Los límites inferidos no reciben grados inventados.
- Solo se incluyen reglas del subtipo TNBC.
- Las reglas deben validarse con oncología antes de usarse sobre historias
  reales.
