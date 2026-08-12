# Matriz clínica — ESMO NSCLC temprano y localmente avanzado

## 1. Identificación del módulo

| Campo | Valor |
|---|---|
| Organización | ESMO |
| Módulo | `esmo_nsclc_early_locally_advanced` |
| Guía fuente | *Early and locally advanced non-small-cell lung cancer: ESMO Clinical Practice Guideline for diagnosis, treatment and follow-up* |
| Publicación | 28 de agosto de 2025 |
| DOI | `10.1016/j.annonc.2025.08.003` |
| Estado técnico | `draft_computable` |
| Validación clínica | Pendiente |
| Uso | Investigación académica interna; permisos de publicación pendientes |

## 2. Propósito

Este módulo identifica reglas ESMO relacionadas con la prescripción de
**pembrolizumab** en NSCLC temprano o localmente avanzado. Su función es
apoyar la auditoría de concordancia y generar trazabilidad. No sustituye la
decisión del oncólogo ni ejecuta órdenes terapéuticas.

## 3. Alcance clínico

### Incluye

- NSCLC temprano o localmente avanzado.
- Enfermedad resecable estadio II-III para una estrategia perioperatoria.
- Enfermedad completamente resecada estadio II-IIIA, tumor de al menos
  4 cm, para pembrolizumab adyuvante después de quimioterapia con platino.
- Revisión de continuidad, duración, toxicidad y progresión.
- Revisión de escenarios sin una ruta positiva de pembrolizumab.

### Excluye o redirige

- NSCLC metastásico.
- SCLC y tumores carcinoides.
- Enfermedad estadio III irresecable como ruta positiva de pembrolizumab.
- Casos con EGFR sensibilizante o ALK reordenado, que requieren rutas
  terapéuticas moleculares.
- Prescripciones anteriores al 28 de agosto de 2025 cuando se pretenda usar
  esta versión como estándar contemporáneo.

## 4. Aplicabilidad temporal

La guía se publicó el 28 de agosto de 2025. Por ello, la variable
`guideline_temporal_applicability` debe derivarse antes de evaluar las reglas:

| Resultado | Interpretación |
|---|---|
| `applicable` | La fecha del evento es igual o posterior a la publicación. |
| `not_yet_published` | Se requiere consultar la versión histórica vigente. |
| `uncertain` | La fecha o versión no permite concluir aplicabilidad. |
| `unknown` | No hay información suficiente. |

Una prescripción anterior a la publicación **no se clasifica automáticamente
como desviación**. Se dirige a revisión histórica.

## 5. Recomendaciones positivas de pembrolizumab

| Ruta | Población computable | Secuencia | Evidencia nativa |
|---|---|---|---|
| Perioperatoria | NSCLC resecable estadio II-III, EGFR sin mutación sensibilizante, ALK negativo, biomarcadores completos, revisión por MDT y sin contraindicación para ICI | Pembrolizumab + quimioterapia basada en cisplatino antes de cirugía; cirugía; pembrolizumab adyuvante | `[I, A]`; ESMO-MCBS v2.0 `A (AT)` |
| Adyuvante después de platino | Resección R0, estadio patológico II-IIIA, tumor ≥4 cm, EGFR WT, ALK negativo, sin pembrolizumab neoadyuvante y con quimioterapia previa basada en platino | Pembrolizumab adyuvante durante un año | `[I, A]`; ESMO-MCBS v2.0 `A (AT)` |

La recomendación adyuvante después de platino se modela
**independientemente de la expresión de PD-L1**.

## 6. Catálogo de regímenes

| Identificador | Nombre | Fase | Duración o límite |
|---|---|---|---|
| `pembro_cisplatin_based_chemotherapy_neoadjuvant` | Pembrolizumab con quimioterapia basada en cisplatino | `neoadjuvant` | 4 ciclos |
| `pembro_adjuvant_after_neoadjuvant` | Pembrolizumab adyuvante después de pembrolizumab y quimioterapia neoadyuvantes | `adjuvant` | hasta 13 ciclos |
| `pembro_perioperative_sequence` | Secuencia perioperatoria de pembrolizumab | `secuencia` | Secuencia completa |
| `pembro_adjuvant_after_platinum` | Pembrolizumab adyuvante después de quimioterapia basada en platino | `adjuvant` | 12 meses |

Los límites de cuatro ciclos neoadyuvantes y trece ciclos posoperatorios
proceden del protocolo KEYNOTE-671 descrito por la guía. El sistema los usa
para generar avisos de revisión, no para ordenar una suspensión automática.

## 7. Diccionario de variables

| Variable | Definición operativa | Tipo | Valores o rango |
|---|---|---|---|
| `cancer_type` | Tipo histológico general para confirmar NSCLC. | `categorical` | `NSCLC`, `SCLC`, `carcinoid`, `other`, `unknown` |
| `histology` | Subtipo escamoso o no escamoso. | `categorical` | `squamous`, `non_squamous`, `not_otherwise_specified`, `unknown` |
| `disease_setting` | Contexto temprano, localmente avanzado o fuera de alcance. | `categorical` | `early`, `locally_advanced`, `metastatic`, `recurrent`, `unknown` |
| `clinical_stage_group` | Grupo de estadio clínico normalizado. | `categorical` | `IA1`, `IA2`, `IA3`, `IB`, `IIA`, `IIB`, `IIIA`, `IIIB`, `IIIC`, `IV`, `unknown` |
| `pathological_stage_group` | Grupo de estadio patológico después de cirugía. | `categorical` | `IA1`, `IA2`, `IA3`, `IB`, `IIA`, `IIB`, `IIIA`, `IIIB`, `IIIC`, `IV`, `not_applicable`, `unknown` |
| `tnm_edition` | Edición TNM usada en el documento fuente del caso. | `categorical` | `TNM7`, `TNM8`, `TNM9`, `unknown` |
| `tumor_size_cm` | Tamaño tumoral máximo en centímetros. | `number` | Numérico ≥ 0 |
| `node_positive` | Presencia documentada de enfermedad ganglionar. | `categorical` | `yes`, `no`, `unknown` |
| `resectability_status` | Estado de resecabilidad definido por el equipo tratante. | `categorical` | `resectable`, `completely_resected`, `unresectable`, `indeterminate`, `unknown` |
| `mdt_review_completed` | Constancia de discusión multidisciplinaria. | `categorical` | `yes`, `no`, `unknown` |
| `egfr_status` | Resultado molecular de EGFR. | `categorical` | `wild_type`, `sensitizing_mutation`, `other_non_sensitizing_alteration`, `pending`, `unknown` |
| `alk_status` | Resultado molecular de ALK. | `categorical` | `negative`, `rearranged`, `pending`, `unknown` |
| `pdl1_test_completed` | Indica si PD-L1 fue evaluado. | `categorical` | `yes`, `no`, `unknown` |
| `pdl1_tc_percent` | Porcentaje de células tumorales con expresión de PD-L1. | `number` | Numérico ≥ 0 |
| `biomarker_testing_complete` | Disponibilidad mínima de EGFR, ALK y PD-L1. | `categorical` | `yes`, `no`, `unknown` |
| `immunotherapy_contraindication` | Contraindicación documentada para inmunoterapia. | `categorical` | `yes`, `no`, `unknown` |
| `platinum_chemotherapy_eligible` | Elegibilidad general para quimioterapia con platino. | `categorical` | `yes`, `no`, `unknown` |
| `cisplatin_eligible` | Elegibilidad específica para cisplatino. | `categorical` | `yes`, `no`, `unknown` |
| `treatment_phase` | Fase terapéutica del evento auditado. | `categorical` | `neoadjuvant`, `surgery`, `adjuvant`, `surveillance`, `definitive_chemoradiotherapy`, `consolidation`, `unknown` |
| `pembrolizumab_pathway` | Ruta perioperatoria o adyuvante aislada. | `categorical` | `perioperative`, `adjuvant_only`, `unknown` |
| `prior_neoadjuvant_pembrolizumab` | Exposición previa a pembrolizumab neoadyuvante. | `categorical` | `yes`, `no`, `unknown` |
| `prior_neoadjuvant_platinum_chemotherapy` | Quimioterapia neoadyuvante previa con platino. | `categorical` | `yes`, `no`, `unknown` |
| `neoadjuvant_pembrolizumab_cycles_completed` | Número de ciclos neoadyuvantes completados. | `integer` | Entero ≥ 0 |
| `surgery_completed` | Confirmación de cirugía. | `categorical` | `yes`, `no`, `unknown` |
| `resection_margin_status` | Estado de margen quirúrgico R0, R1 o R2. | `categorical` | `R0`, `R1`, `R2`, `not_applicable`, `unknown` |
| `pathologic_response` | Respuesta patológica posterior a tratamiento neoadyuvante. | `categorical` | `pCR`, `MPR`, `residual_viable_tumor`, `not_assessed`, `unknown` |
| `prior_adjuvant_platinum_chemotherapy` | Quimioterapia adyuvante previa basada en platino. | `categorical` | `yes`, `no`, `unknown` |
| `adjuvant_pembrolizumab_planned` | Plan documentado de pembrolizumab adyuvante. | `categorical` | `yes`, `no`, `unknown` |
| `adjuvant_pembrolizumab_cycles_completed` | Número de ciclos posoperatorios completados. | `integer` | Entero ≥ 0 |
| `months_on_adjuvant_pembrolizumab` | Duración acumulada del tratamiento adyuvante. | `number` | Numérico ≥ 0 |
| `disease_progression` | Progresión documentada durante el tratamiento. | `categorical` | `yes`, `no`, `unknown` |
| `treatment_discontinuation_reason` | Motivo de interrupción o finalización. | `categorical` | `planned_completion`, `toxicity`, `progression`, `patient_choice`, `other`, `unknown` |
| `prescribed_antineoplastic_drugs` | Medicamentos antineoplásicos de la prescripción. | `list` | Lista de cadenas |
| `prescription_date` | Fecha del evento de prescripción. | `date` | Fecha ISO `YYYY-MM-DD` |
| `guideline_temporal_applicability` | Aplicabilidad de esta versión según la fecha del evento. | `categorical` | `applicable`, `not_yet_published`, `uncertain`, `unknown` |

## 8. Catálogo completo de reglas

| Regla | Archivo | Escenario | Efecto de auditoría | Evidencia | Localizador |
|---|---|---|---|---|---|
| `ESMO-NSCLC-ELA-ELIG-001` | `eligibility.yaml` | Caso dentro del alcance del módulo | `none` | Sin gradación explícita / política interna | system_scope |
| `ESMO-NSCLC-ELA-ELIG-002` | `eligibility.yaml` | Evaluación sistémica preparada con biomarcadores y discusión multidisciplinaria | `none` | V/A | p. 1253 |
| `ESMO-NSCLC-ELA-NEO-001` | `neoadjuvant.yaml` | Pembrolizumab con quimioterapia neoadyuvante como parte de una secuencia perioperatoria | `supports_prescription` | I/A; MCBS 2.0 A (AT) | p. 1253 |
| `ESMO-NSCLC-ELA-PERI-001` | `perioperative.yaml` | Continuidad de la secuencia perioperatoria después de cirugía | `supports_prescription` | I/A; MCBS 2.0 A (AT) | pp. 1252-1253 |
| `ESMO-NSCLC-ELA-PERI-002` | `perioperative.yaml` | Revisión de omisión adyuvante basada únicamente en respuesta patológica completa | `requires_clinical_review` | Sin gradación explícita / política interna | p. 1252 |
| `ESMO-NSCLC-ELA-ADJ-001` | `adjuvant.yaml` | Pembrolizumab adyuvante como continuación de la secuencia perioperatoria | `supports_prescription` | I/A; MCBS 2.0 A (AT) | pp. 1252-1253 |
| `ESMO-NSCLC-ELA-ADJ-002` | `adjuvant.yaml` | Pembrolizumab adyuvante durante un año después de resección completa y quimioterapia con platino | `supports_prescription` | I/A; MCBS 2.0 A (AT) | p. 1253 |
| `ESMO-NSCLC-ELA-CONT-001` | `continuation.yaml` | Revisión al completar trece ciclos posoperatorios en la secuencia perioperatoria | `advisory` | Sin gradación explícita / política interna | p. 1252 |
| `ESMO-NSCLC-ELA-CONT-002` | `continuation.yaml` | Revisión al completar un año de pembrolizumab adyuvante | `advisory` | I/A; MCBS 2.0 A (AT) | p. 1253 |
| `ESMO-NSCLC-ELA-CONT-003` | `continuation.yaml` | Progresión durante pembrolizumab perioperatorio o adyuvante | `requires_clinical_review` | Sin gradación explícita / política interna | Follow-up, long-term implications and survivorship |
| `ESMO-NSCLC-ELA-CONT-004` | `continuation.yaml` | Interrupción por toxicidad durante pembrolizumab | `requires_clinical_review` | Sin gradación explícita / política interna | Follow-up, long-term implications and survivorship |
| `ESMO-NSCLC-ELA-EXC-000` | `exclusions.yaml` | La prescripción es anterior a la publicación de esta versión de la guía | `requires_clinical_review` | Sin gradación explícita / política interna | — |
| `ESMO-NSCLC-ELA-EXC-001` | `exclusions.yaml` | Pembrolizumab prescrito en estadio I sin una ruta respaldada por este módulo | `requires_clinical_review` | Sin gradación explícita / política interna | Figure 1, p. 1249 |
| `ESMO-NSCLC-ELA-EXC-002` | `exclusions.yaml` | Enfermedad metastásica fuera del alcance de este módulo | `none` | Sin gradación explícita / política interna | system_scope |
| `ESMO-NSCLC-ELA-EXC-003` | `exclusions.yaml` | Pembrolizumab en NSCLC estadio III irresecable requiere revisión | `requires_clinical_review` | Sin gradación explícita / política interna | pp. 1255-1256 |
| `ESMO-NSCLC-ELA-EXC-004` | `exclusions.yaml` | Alteración sensibilizante de EGFR fuera de la ruta perioperatoria de pembrolizumab | `requires_clinical_review` | I/A; MCBS 2.0 A (AT) | p. 1253 |
| `ESMO-NSCLC-ELA-EXC-005` | `exclusions.yaml` | Rearreglo de ALK fuera de la ruta perioperatoria de pembrolizumab | `requires_clinical_review` | I/A; MCBS 2.0 A (AT) | p. 1253 |
| `ESMO-NSCLC-ELA-EXC-006` | `exclusions.yaml` | Pembrolizumab neoadyuvante sin quimioterapia basada en cisplatino | `requires_clinical_review` | Sin gradación explícita / política interna | p. 1252 |
| `ESMO-NSCLC-ELA-EXC-006B` | `exclusions.yaml` | Paciente no elegible para cisplatino dentro de la secuencia KEYNOTE-671 | `requires_clinical_review` | Sin gradación explícita / política interna | p. 1252 |
| `ESMO-NSCLC-ELA-EXC-007` | `exclusions.yaml` | Pembrolizumab adyuvante aislado sin quimioterapia previa basada en platino | `requires_clinical_review` | I/A; MCBS 2.0 A (AT) | p. 1253 |
| `ESMO-NSCLC-ELA-EXC-008` | `exclusions.yaml` | Pembrolizumab adyuvante después de resección incompleta | `requires_clinical_review` | Sin gradación explícita / política interna | Figures 1-2 and systemic therapy recommendations |
| `ESMO-NSCLC-ELA-EXC-009` | `exclusions.yaml` | Contraindicación documentada para inmunoterapia | `requires_clinical_review` | Sin gradación explícita / política interna | Systemic therapy eligibility |
| `ESMO-NSCLC-ELA-EXC-010` | `exclusions.yaml` | Biomarcadores mínimos incompletos antes de definir la secuencia sistémica | `requires_clinical_review` | V/A | p. 1253 |
| `ESMO-NSCLC-ELA-EXC-011` | `exclusions.yaml` | PD-L1 no evaluado antes de definir la estrategia perioperatoria | `advisory` | IV/A | p. 1247 |
| `ESMO-NSCLC-ELA-EXC-012` | `exclusions.yaml` | Estadio III resecable sin discusión multidisciplinaria documentada | `requires_clinical_review` | V/A | p. 1253 |

## 9. Interpretación de los resultados

| Efecto | Uso |
|---|---|
| `supports_prescription` | La regla aplicable respalda la ruta evaluada. |
| `requires_clinical_review` | El caso requiere revisión experta; no equivale por sí solo a desviación. |
| `advisory` | Aviso de duración, biomarcadores o seguimiento. |
| `none` | Regla de alcance o enrutamiento sin veredicto de concordancia. |

## 10. Límites metodológicos actuales

1. El motor disponible evalúa archivos de reglas de forma independiente.
   `pathway.yaml` ya describe el flujo, pero todavía falta un orquestador que
   recorra automáticamente todos sus nodos.
2. `regimens.yaml` funciona como catálogo canónico. La comparación automática
   entre una prescripción y un `regimen_id` todavía debe integrarse al motor.
3. Los casos de prueba son sintéticos y validan lógica computacional; no
   demuestran validez clínica externa.
4. Las reglas de seguridad y cobertura sin gradación explícita conservan
   valores nulos y no inventan evidencia.
5. La transformación entre TNM8 y TNM9 debe conservar la edición original y
   ser revisada clínicamente antes de usar datos reales.
6. La clasificación definitiva de una alerta requiere validación con el
   especialista y comparación con la versión de guía vigente en la fecha de
   prescripción.

## 11. Criterios para validación clínica

| Elemento | Estado |
|---|---|
| Alcance del módulo revisado por oncología torácica | Pendiente |
| Variables disponibles en las historias clínicas | Pendiente |
| Correspondencia TNM y resecabilidad | Pendiente |
| Regímenes y secuencias revisados | Pendiente |
| Reglas positivas revisadas | Pendiente |
| Reglas de revisión/exclusión revisadas | Pendiente |
| Casos sintéticos revisados | Pendiente |
| Umbrales para alertas institucionales aprobados | Pendiente |

## 12. Fuente clínica utilizada

Zer, A., et al. (2025). *Early and locally advanced non-small-cell lung
cancer: ESMO Clinical Practice Guideline for diagnosis, treatment and
follow-up*. *Annals of Oncology, 36*(11), 1245-1262.
`https://doi.org/10.1016/j.annonc.2025.08.003`

Localizadores principales usados en el módulo:

- biomarcadores y diagnóstico: pp. 1246-1247;
- algoritmo de estadio I: figura 1, p. 1249;
- KEYNOTE-671 y terapia perioperatoria: pp. 1252-1253;
- pembrolizumab adyuvante: p. 1253;
- estadio III irresecable: pp. 1255-1256.
