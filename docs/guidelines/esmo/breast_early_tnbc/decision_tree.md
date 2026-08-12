# Árbol de decisión — ESMO TNBC temprano y localmente avanzado

## 1. Propósito

Este árbol representa el enrutamiento del módulo `esmo_breast_early_tnbc`. Se
limita al subtipo triple negativo (TNBC) y a las decisiones sistémicas
(neoadyuvancia, adyuvancia, pembrolizumab, olaparib, capecitabina),
separando una recomendación positiva de un caso que solo requiere revisión.
No modela en detalle cirugía ni radioterapia.

## 2. Flujo general

```text
INICIO
  |
  +-- ¿Diagnóstico = TNBC (triple negativo) confirmado por biopsia?
  |      |
  |      +-- No -> FUERA DE ALCANCE (otro subtipo)
  |      |
  |      +-- Sí
  |           |
  |           +-- ¿Enfermedad metastásica (M1)?
  |                  |
  |                  +-- Sí -> MÓDULO METASTÁSICO
  |                  |         (esmo_breast_metastatic_tnbc)
  |                  |
  |                  +-- No
  |                       |
  |                       +-- ¿Histología especial de bajo riesgo (adenoide
  |                            quística, secretora) o pT1a pN0?
```

## 3. Rama de histología / riesgo mínimo

```text
HISTOLOGÍA Y RIESGO MÍNIMO
  |
  +-- Adenoide quística o secretora, riesgo clínico bajo
  |      --> Beneficio de ChT no establecido; ChT no recomendada de rutina
  |
  +-- pT1a pN0 (fuera de histologías especiales)
  |      --> Beneficio de ChT adyuvante mínimo o ausente
  |
  +-- pT1b pN0
  |      --> Beneficio de ChT adyuvante incierto; revisión clínica
  |
  +-- Ninguna de las anteriores -> Evaluar estadio clínico
```

## 4. Rama de estadio y elección neoadyuvancia vs. cirugía primaria

```text
ESTADIO CLÍNICO
  |
  +-- cT1c-4 N0, o cualquier N-positivo
  |      --> Neoadyuvancia preferida (ver sección 5)
  |
  +-- cT1a-b N0 (fuera de histologías especiales y pT1a/b ya cubiertos)
  |      --> Cirugía primaria; ver sección 7
  |
  +-- Estadio indeterminado o datos incompletos
         --> NO EVALUABLE
```

## 5. Ruta neoadyuvante

```text
FASE NEOADYUVANTE
  |
  +-- cT2-4 N0, o cualquier N-positivo (estadio clínico II-III)
  +-- Sin factores de riesgo de toxicidad inmunorrelacionada excesiva
  |
  +--> RESPALDAR:
       ChT (antraciclina-taxano o taxano-carboplatino)
       + pembrolizumab cada 3 semanas
       durante toda la fase neoadyuvante [I, A; MCBS A]
       |
       +--> CIRUGÍA
             |
             +-- Continuar en sección 6 (manejo tras cirugía)
  |
  +-- cT1c N0 (bajo volumen, estadio I)
         --> Neoadyuvancia también preferida; discutir con la paciente la
             alternativa de cirugía primaria
```

Evidencia nativa de la recomendación de ChT + pembrolizumab: `[I, A]`,
ESMO-MCBS v1.1 `A`.

## 6. Manejo tras cirugía (fase adyuvante, ruta neoadyuvante)

```text
MANEJO TRAS CIRUGÍA
  |
  +-- ¿Pembrolizumab recibido en neoadyuvancia?
  |      |
  |      +-- Sí
  |      |    --> RESPALDAR: pembrolizumab adyuvante, 9 ciclos de 3
  |      |        semanas, independientemente del estatus de pCR [I, A]
  |      |
  |      +-- No -> continuar solo con evaluación de pCR
  |
  +-- ¿pCR alcanzada?
         |
         +-- Sí (pCR)
         |      --> Sin adyuvancia citotóxica adicional obligatoria
         |
         +-- No (enfermedad residual)
                |
                +-- gBRCA1/2 mutado, alto riesgo (no-pCR o estadio
                |    patológico II-III)
                |      --> RESPALDAR: olaparib adyuvante durante 1 año
                |          [I, A; MCBS A; ESCAT I-A]
                |          Nota: combinación con capecitabina no
                |          recomendada [V, C]
                |
                +-- No recibió ICI (ni neo ni adyuvante)
                       --> RESPALDAR: capecitabina adyuvante,
                           6-8 ciclos [I, A]
```

## 7. Ruta de cirugía primaria (sin neoadyuvancia)

```text
CIRUGÍA PRIMARIA
  |
  +-- ChT adyuvante con el mismo backbone que en neoadyuvancia
  |
  +-- gBRCA1/2 mutado, alto riesgo
  |      --> RESPALDAR: olaparib adyuvante 1 año [I, A; ESCAT I-A]
  |
  +-- Nota: pembrolizumab exclusivamente en fase adyuvante, sin
       exposición neoadyuvante previa, NO está respaldado [V, D]
```

## 8. Ramas de revisión

```text
¿Se presenta alguna de estas condiciones?
  |
  +-- PD-L1 usado como criterio para indicar o excluir pembrolizumab
  |      --> Desviación: el PD-L1 no debe usarse para decisiones de
  |          tratamiento en enfermedad temprana [I, E]
  |
  +-- ICI prescrito solo en fase adyuvante, sin ICI neoadyuvante previo
  |      --> Revisión clínica [V, D]
  |
  +-- Olaparib y capecitabina combinados en gBRCA1/2 mutado
  |      --> Revisión clínica; combinación no recomendada [V, C]
  |
  +-- Histología especial de bajo riesgo con ChT prescrita
  |      --> Revisión; beneficio no establecido
  |
  +-- Estatus germinal BRCA1/2 no evaluado en candidata a olaparib
  |      --> Solicitar información / no evaluable
  |
  +-- Estadio clínico o histología no documentados
         --> NO EVALUABLE
```

## 9. Continuación y seguridad

```text
TRATAMIENTO EN CURSO
  |
  +-- Pembrolizumab adyuvante y 9 ciclos completados
  |      --> Aviso de finalización planificada
  |
  +-- Toxicidad inmunorrelacionada durante pembrolizumab
  |      --> Seguir la guía ESMO de manejo de toxicidad por
  |          inmunoterapia [V, A]
  |
  +-- Olaparib adyuvante y 1 año completado
         --> Aviso de finalización planificada
```

Ninguna de estas ramas ejecuta automáticamente una suspensión del
tratamiento.

## 10. Salidas del módulo

| Salida | Significado |
|---|---|
| `supports_prescription` | Existe una regla positiva aplicable. |
| `requires_clinical_review` | El caso necesita revisión experta. |
| `advisory` | Aviso no vinculante de duración o seguimiento. |
| `not_evaluable` | Faltan hechos clínicos indispensables. |
| `outside_scope` | El caso corresponde a otro módulo (otro subtipo o enfermedad metastásica). |
| `historical_guideline_version_required` | Debe consultarse la guía vigente en la fecha del evento. |

## 11. Nota de implementación

`pathway.yaml` contendría este flujo de forma declarativa. Como en los
demás módulos, cada archivo de reglas (eligibility, exclusion,
continuation) se prueba de manera independiente; la ejecución automática
del árbol completo requiere el orquestador del `pathway`.
