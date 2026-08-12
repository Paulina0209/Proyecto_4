# Árbol de decisión — ESMO NSCLC temprano y localmente avanzado

## 1. Propósito

Este árbol representa el enrutamiento del módulo
`esmo_nsclc_early_locally_advanced`. Se limita a decisiones relacionadas con
pembrolizumab y separa claramente una recomendación positiva de un caso que
solo requiere revisión.

## 2. Flujo general

```text
INICIO
  |
  +-- ¿Diagnóstico = NSCLC?
  |      |
  |      +-- No ------------------------------> FUERA DE ALCANCE
  |      |
  |      +-- Sí
  |           |
  |           +-- ¿Contexto = temprano o localmente avanzado?
  |                  |
  |                  +-- No ------------------> OTRO MÓDULO
  |                  |
  |                  +-- Sí
  |                       |
  |                       +-- ¿Versión ESMO 2025 aplicable por fecha?
  |                              |
  |                              +-- No publicada todavía
  |                              |      --> REVISAR GUÍA HISTÓRICA
  |                              |
  |                              +-- Fecha incierta
  |                              |      --> NO EVALUABLE
  |                              |
  |                              +-- Sí
  |                                   |
  |                                   +-- Evaluar resecabilidad
```

## 3. Rama de resecabilidad

```text
RESECABILIDAD
  |
  +-- Resecable -----------------------------> Usar estadio clínico
  |
  +-- Completamente resecado ----------------> Usar estadio patológico
  |
  +-- Irresecable estadio III
  |      |
  |      +-- Pembrolizumab prescrito --------> REVISIÓN CLÍNICA
  |      |
  |      +-- Nota: la guía modela CRT seguida de durvalumab
  |          o consolidación con osimertinib según EGFR;
  |          no se identificó una ruta positiva de pembrolizumab.
  |
  +-- Indeterminada -------------------------> REVISIÓN POR MDT
  |
  +-- Desconocida ---------------------------> NO EVALUABLE
```

## 4. Rama de estadio

```text
ESTADIO
  |
  +-- IA1, IA2, IA3 o IB
  |      |
  |      +-- Pembrolizumab prescrito --------> REVISIÓN CLÍNICA
  |          No se identificó una ruta positiva en este módulo.
  |
  +-- IIA, IIB, IIIA o IIIB resecable
  |      |
  |      +-- Evaluar EGFR
  |             |
  |             +-- Mutación sensibilizante u otra alteración
  |             |      --> RUTA MOLECULAR / REVISIÓN
  |             |
  |             +-- WT
  |                    |
  |                    +-- Evaluar ALK
  |                           |
  |                           +-- Reordenado
  |                           |      --> RUTA MOLECULAR / REVISIÓN
  |                           |
  |                           +-- Negativo
  |                                  --> Evaluar fase terapéutica
  |
  +-- IIIC o estadio ambiguo ----------------> REVISIÓN / NO EVALUABLE
  |
  +-- IV ------------------------------------> MÓDULO METASTÁSICO
```

## 5. Ruta perioperatoria

```text
FASE NEOADYUVANTE
  |
  +-- Estadio II-III resecable
  +-- EGFR WT
  +-- ALK negativo
  +-- EGFR, ALK y PD-L1 disponibles
  +-- Discusión multidisciplinaria documentada
  +-- Sin contraindicación para inmunoterapia
  +-- Elegible para cisplatino
  |
  +--> RESPALDAR:
       pembrolizumab + quimioterapia basada en cisplatino
       durante la fase neoadyuvante
       |
       +--> CIRUGÍA
             |
             +-- Sin progresión
             +-- Sin nueva contraindicación
             |
             +--> RESPALDAR:
                  pembrolizumab adyuvante
                  como continuidad de la misma secuencia
```

Evidencia nativa de la recomendación: `[I, A]`, ESMO-MCBS v2.0
`A (AT)`.

El protocolo descrito por KEYNOTE-671 comprende cuatro ciclos
neoadyuvantes y hasta trece ciclos posoperatorios. Alcanzar el límite genera
un aviso de revisión de finalización.

## 6. Ruta adyuvante después de platino

```text
FASE ADYUVANTE
  |
  +-- Cirugía completada
  +-- Resección R0
  +-- Estadio patológico II-IIIA
  +-- Tumor >= 4 cm
  +-- EGFR WT
  +-- ALK negativo
  +-- No recibió pembrolizumab neoadyuvante
  +-- Recibió quimioterapia adyuvante basada en platino
  +-- Sin progresión
  +-- Sin contraindicación para inmunoterapia
  |
  +--> RESPALDAR:
       pembrolizumab adyuvante durante un año
       independientemente de PD-L1
```

Evidencia nativa de la recomendación: `[I, A]`, ESMO-MCBS v2.0
`A (AT)`.

## 7. Ramas de revisión

```text
¿Se presenta alguna de estas condiciones?
  |
  +-- Prescripción anterior al 28-08-2025
  |      --> Revisar versión histórica
  |
  +-- Estadio I con pembrolizumab
  |      --> Revisión clínica
  |
  +-- Estadio III irresecable con pembrolizumab
  |      --> Revisión clínica
  |
  +-- EGFR alterado o ALK reordenado
  |      --> Ruta molecular / revisión clínica
  |
  +-- Pembrolizumab neoadyuvante sin cisplatino
  |      --> Revisar concordancia del régimen
  |
  +-- Paciente no elegible para cisplatino
  |      --> Revisar alternativa y justificación
  |
  +-- Adyuvancia aislada sin platino previo
  |      --> Revisar prerrequisito
  |
  +-- Resección R1 o R2
  |      --> Revisión multidisciplinaria
  |
  +-- Contraindicación para inmunoterapia
  |      --> Revisión clínica
  |
  +-- Biomarcadores incompletos
  |      --> Solicitar información / no evaluable
  |
  +-- Omisión adyuvante basada solo en pCR
  |      --> Revisión; desescalamiento no establecido
```

## 8. Continuación y seguridad

```text
TRATAMIENTO EN CURSO
  |
  +-- Ruta perioperatoria y 13 ciclos posoperatorios
  |      --> Aviso de finalización planificada
  |
  +-- Ruta adyuvante aislada y 12 meses
  |      --> Aviso de finalización planificada
  |
  +-- Progresión durante tratamiento
  |      --> Revisión clínica
  |
  +-- Interrupción por toxicidad
         --> Revisión clínica
```

Ninguna de estas ramas ejecuta automáticamente una suspensión del
tratamiento.

## 9. Salidas del módulo

| Salida | Significado |
|---|---|
| `supports_prescription` | Existe una regla positiva aplicable. |
| `requires_clinical_review` | El caso necesita revisión experta. |
| `advisory` | Aviso no vinculante de duración o seguimiento. |
| `not_evaluable` | Faltan hechos clínicos indispensables. |
| `outside_scope` | El caso debe enviarse a otro módulo. |
| `historical_guideline_version_required` | Debe consultarse la guía vigente en la fecha del evento. |

## 10. Nota de implementación

`pathway.yaml` contiene este flujo de forma declarativa. En la versión técnica
actual, las pruebas evalúan cada archivo de reglas de manera independiente.
La ejecución automática de todo el árbol requiere implementar el orquestador
del `pathway`.