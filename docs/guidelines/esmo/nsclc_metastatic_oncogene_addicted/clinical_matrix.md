# Matriz clínica: ESMO NSCLC metastásico oncogén-adicto

## Estado

Borrador computable pendiente de validación clínica.

## Inventario de reglas - Diagnóstico molecular

| ID | Escenario | Consecuente | Evidencia nativa | Efecto de auditoría |
|---|---|---|---|---|
| DX-001 | NSCLC avanzado no escamoso (o escamoso atípico: joven, no/ex fumador ligero) | Test EGFR obligatorio (cobertura exones 18-21) | I, A / III, A | Respalda |
| DX-002 | Recaída tras EGFR TKI de 1ª o 2ª generación | Test T790M obligatorio (tejido y/o plasma) | I, A | Respalda |
| DX-003 | NSCLC avanzado no escamoso | Test ALK obligatorio | I, A | Respalda |
| DX-004 | Cribado ALK | FISH estándar; IHC de alto rendimiento aceptada como alternativa | III, A | Respalda condicional |
| DX-005 | NSCLC avanzado no escamoso | Test ROS1 obligatorio | II, A | Respalda |
| DX-006 | Cribado ROS1 | FISH estándar; IHC como aproximación de cribado | IV, A | Respalda condicional |
| DX-007 | NSCLC avanzado no escamoso | Test BRAF V600 obligatorio | II, A | Respalda |
| DX-008 | NSCLC avanzado no escamoso | Test NTRK obligatorio (IHC o NGS con confirmación) | II, A | Respalda |
| DX-009 | NSCLC avanzado no escamoso | Test MET exón14 skipping, amplificación MET, RET, KRAS G12C, HER2 obligatorio | II, A | Respalda |
| DX-010 | Disponibilidad de plataforma multiplex | NGS preferido sobre tests secuenciales | III, A | Preferencia |
| DX-011 | Identificación de fusiones génicas | NGS basado en ARN preferido | III, B | Preferencia |
| DX-012 | Uso de biopsia líquida (cfDNA) | Puede usarse para drivers y mecanismos de resistencia | II, A | Respalda condicional |
| DX-013 | cfDNA negativo | Biopsia tisular obligatoria igualmente | II, A | Respalda |

## Inventario de reglas - EGFR mutado

| ID | Escenario | Consecuente | Evidencia nativa | Efecto de auditoría |
|---|---|---|---|---|
| EGFR-001 | Primera línea, mutación EGFR sensibilizante (cualquier tipo) | EGFR TKI de primera línea obligatorio, independiente de PS/sexo/tabaquismo/histología | I, A | Respalda |
| EGFR-002 | Primera línea, deleción ex19 o L858R | Osimertinib preferido (especialmente con metástasis SNC) | I, A; MCBS 4; ESCAT I-A | Respalda |
| EGFR-003 | Primera línea, deleción ex19 o L858R | Erlotinib/gefitinib como alternativa monoterapia | I, B; MCBS 4; ESCAT I-A | Respalda condicional |
| EGFR-004 | Primera línea, deleción ex19 o L858R | Afatinib como alternativa monoterapia | I, B; MCBS 5; ESCAT I-A | Respalda condicional |
| EGFR-005 | Primera línea, deleción ex19 o L858R | Dacomitinib como alternativa monoterapia | I, B; MCBS 3; ESCAT I-A | Respalda condicional |
| EGFR-006 | Primera línea, deleción ex19 o L858R | Gefitinib + carboplatino-pemetrexed | I, B; no aprobado EMA | Respalda condicional |
| EGFR-007 | Primera línea, deleción ex19 o L858R | Erlotinib + bevacizumab | I, B; MCBS 2; ESCAT I-A; no aprobado FDA | Respalda condicional |
| EGFR-008 | Primera línea, deleción ex19 o L858R | Erlotinib + ramucirumab | I, B; MCBS 3; ESCAT I-A | Respalda condicional |
| EGFR-009 | Primera línea, valorando toxicidad/costo/comodidad | TKI en monoterapia sigue siendo estándar preferente | I, A; ESCAT I-A | Preferencia |
| EGFR-010 | Mutación EGFR no común, no inserción exón 20, sensibilizante mayor | Afatinib u osimertinib | III, B; MCBS 4 (afatinib); ESCAT I-B | Respalda condicional |
| EGFR-011 | Progresión radiológica moderada con beneficio clínico continuo | Continuar EGFR TKI | III, A | Respalda condicional |
| EGFR-012 | Resistencia a EGFR TKI de 1ª/2ª generación | Testear T790M (plasma y/o rebiopsia) | I, A | Respalda |
| EGFR-013 | Resistencia T790M positiva | Osimertinib como segunda línea | I, A; MCBS 4 | Respalda |
| EGFR-014 | Resistencia T790M negativa | Quimioterapia doblete de platino | III, A | Respalda |
| EGFR-015 | Progresión sobre osimertinib | NGS genómico (tejido, o cfDNA seguido de tejido si no hay diana) | III, C | Respalda condicional débil |
| EGFR-016 | Progresión sobre osimertinib | Quimioterapia doblete de platino (estándar) | III, A | Respalda |
| EGFR-017 | Progresión sobre osimertinib, mecanismo de resistencia identificable | Considerar inclusión en ensayo clínico | III, B | Respalda condicional |
| EGFR-018 | Fallo EGFR TKI, PS 0-1, sin contraindicación ICI | Atezolizumab + bevacizumab + paclitaxel + carboplatino puede considerarse | III, B; MCBS 3 | Respalda condicional |
| EGFR-019 | Solo tras progresión en EGFR TKI y quimioterapia | ICI monoterapia puede considerarse | IV, C | Respalda condicional débil |

## Inventario de reglas - ALK reordenado

| ID | Escenario | Consecuente | Evidencia nativa | Efecto de auditoría |
|---|---|---|---|---|
| ALK-001 | Primera línea, ALK reordenado | Alectinib, brigatinib o lorlatinib preferidos | I, A; MCBS 4; ESCAT I-A | Respalda |
| ALK-002 | Primera línea, ALK reordenado | Preferencia sobre crizotinib o ceritinib | I, B; MCBS 4; ESCAT I-A | Preferencia |
| ALK-003 | Progresión/intolerancia a crizotinib | Alectinib recomendado | I, A; MCBS 4; ESCAT I-A | Respalda |
| ALK-004 | Resistencia a crizotinib | Brigatinib como opción adicional | III, A; MCBS 4; ESCAT I-A | Respalda condicional |
| ALK-005 | Resistencia a crizotinib | Ceritinib como opción adicional | I, A; MCBS 4; ESCAT I-A | Respalda condicional |
| ALK-006 | Progresión tras TKI ALK de 2ª generación | Lorlatinib | III, A; MCBS 4; ESCAT I-A | Respalda |
| ALK-007 | Progresión sobre lorlatinib | Quimioterapia platino-pemetrexed | III, A | Respalda |
| ALK-008 | Progresión sobre lorlatinib | Atezolizumab-bevacizumab-paclitaxel-carboplatino puede considerarse | III, B; MCBS 3 | Respalda condicional |

## Inventario de reglas - ROS1 reordenado

| ID | Escenario | Consecuente | Evidencia nativa | Efecto de auditoría |
|---|---|---|---|---|
| ROS1-001 | Primera línea, ROS1 reordenado | Crizotinib o entrectinib | III, A; MCBS 3; ESCAT I-B | Respalda |
| ROS1-002 | Primera línea, metástasis cerebrales | Entrectinib preferido sobre crizotinib | III, A; MCBS 3; ESCAT I-B | Preferencia |
| ROS1-003 | Primera línea (si disponible) | Repotrectinib | III, B; ESCAT I-B; no aprobado EMA | Respalda condicional |
| ROS1-004 | Recibió crizotinib en primera línea, progresión | TKI de nueva generación si disponible | III, A; sin aprobación EMA | Respalda condicional |
| ROS1-005 | Recibió crizotinib en primera línea, progresión, sin TKI nuevo disponible | Quimioterapia basada en platino, segunda línea | IV, A | Respalda |

## Inventario de reglas - BRAF V600 mutado

| ID | Escenario | Consecuente | Evidencia nativa | Efecto de auditoría |
|---|---|---|---|---|
| BRAF-001 | BRAF V600 mutado (cualquier línea) | Dabrafenib + trametinib | III, A; MCBS 2; ESCAT I-B | Respalda |
| BRAF-002 | Progresión tras BRAF-MEK, sin historia tabáquica | Quimioterapia platino +/- inmunoterapia, segunda línea | IV, A | Respalda condicional |
| BRAF-003 | Progresión tras BRAF-MEK, con historia tabáquica | Inmunoterapia +/- quimioterapia según guía no oncogén-adicta | IV, B | Respalda condicional |

## Inventario de reglas - RET fusión positivo

| ID | Escenario | Consecuente | Evidencia nativa | Efecto de auditoría |
|---|---|---|---|---|
| RET-001 | Primera línea, RET fusión positivo | Selpercatinib o pralsetinib | III, A; MCBS 3; ESCAT I-C | Respalda |

## Inventario de reglas - Otros drivers accionables

| ID | Escenario | Consecuente | Evidencia nativa | Efecto de auditoría |
|---|---|---|---|---|
| MET-001 | MET exón14 skipping, primera línea | Capmatinib o tepotinib | III, A; MCBS 3; ESCAT I-B; FDA no EMA | Respalda condicional |
| MET-002 | MET exón14 skipping, segunda línea | Capmatinib o tepotinib | III, A; MCBS 3; ESCAT I-B | Respalda condicional |
| MET-003 | MET exón14 skipping, sin TKI MET disponible en 1ª línea | Quimioterapia platino +/- ICI | IV, B | Respalda |
| HER2-001 | HER2 mutación exón20, primera línea | Quimioterapia platino +/- ICI | IV, B | Respalda |
| HER2-002 | HER2 mutación exón20, tras primera línea | Trastuzumab-deruxtecan (si disponible) | III, B; ESCAT II-B; no aprobado EMA | Respalda condicional |
| NTRK-001 | NTRK fusión, primera línea | Quimioterapia platino +/- ICI | IV, B | Respalda |
| NTRK-002 | NTRK fusión, sin opciones satisfactorias previas | Larotrectinib o entrectinib | III, A; MCBS 3; ESCAT I-C | Respalda condicional |
| KRAS-001 | KRAS G12C mutado, primera línea | Seguir algoritmo de NSCLC no oncogén-adicto | III, A | Respalda |
| KRAS-002 | KRAS G12C, progresión sobre ICI monoterapia 1ª línea | Quimioterapia doblete de platino, 2ª línea | III, A | Respalda |
| KRAS-003 | KRAS G12C, fallo de terapia previa | Sotorasib | I, B; MCBS 3; ESCAT I-B | Respalda |
| KRAS-004 | KRAS G12C, fallo de terapia previa | Adagrasib | III, B; MCBS 2; ESCAT I-B; FDA no EMA | Respalda condicional |
| EX20-001 | EGFR exón20 inserción, primera línea | Quimioterapia doblete de platino | Sin grado explícito (preferencia clínica) | Respalda condicional |
| EX20-002 | EGFR exón20 inserción, fallo de terapia previa | Amivantamab | III, B; MCBS 3; ESCAT I-B | Respalda |
| EX20-003 | EGFR exón20 inserción, fallo de terapia previa | Mobocertinib puede darse | III, C; MCBS 2; ESCAT I-B; FDA no EMA | Respalda condicional débil |

## Inventario de reglas - Poblaciones especiales y seguimiento

| ID | Escenario | Consecuente | Evidencia nativa | Efecto de auditoría |
|---|---|---|---|---|
| SP-001 | PS 2, driver oncogénico presente | TKI debe administrarse igualmente | III, A | Respalda |
| SP-002 | Paciente anciano (≥65 años), driver oncogénico presente | TKI debe administrarse igualmente | II, A | Respalda |
| SP-003 | Enfermedad oligometastásica al diagnóstico | Sistémico + terapia ablativa local (LAT) puede dar SLP prolongada; preferir ensayo clínico | II, B | Respalda condicional |
| SP-004 | Oligoprogresión bajo terapia dirigida molecular | LAT puede beneficiar (evidencia limitada); preferir ensayo clínico | Evidencia limitada, sin grado uniforme | Revisión |
| FU-001 | Opción de siguiente línea de tratamiento disponible | Seguimiento cada 8-12 semanas | IV, A | Respalda |
| FU-002 | Necesidad detectada | Apoyo psicosocial | IV, A | Respalda |
| FU-003 | Paciente fumador activo | Fomentar cesación tabáquica | IV, A | Respalda |
| FU-004 | Estadio IV, en paralelo al tratamiento oncológico estándar | Cuidados paliativos tempranos | I, A | Respalda |

## Inventario de reglas - Posibles desviaciones

| ID | Escenario | Consecuente | Evidencia nativa | Efecto de auditoría |
|---|---|---|---|---|
| EXC-001 | Mutación EGFR sensibilizante confirmada y no se prescribe EGFR TKI en primera línea | Desviación del estándar | I, A | Posible desviación |
| EXC-002 | ALK reordenado confirmado y se prescribe quimioterapia sin TKI ALK en primera línea | Desviación del estándar | I, A | Posible desviación |
| EXC-003 | RET fusión positivo confirmado y no se ofrece selpercatinib/pralsetinib en primera línea | Desviación del estándar | III, A | Posible desviación |
| EXC-004 | ICI en monoterapia prescrito en EGFR mutado sin fallo previo de TKI y quimioterapia | Fuera de indicación soportada | IV, C | Posible desviación |
| EXC-005 | Progresión sobre TKI 1ª/2ª generación sin test de T790M solicitado | Vacío diagnóstico antes de decisión terapéutica | I, A | Posible desviación |

## Decisiones metodológicas

- Las reglas de clase se identifican por prefijo de driver molecular (`EGFR-`, `ALK-`, `ROS1-`, etc.).
- Los límites inferidos (p. ej., preferencias de secuenciación) no reciben grados inventados; se marcan como "sin grado explícito".
- La recomendación positiva no se invierte automáticamente en regla de exclusión.
- Las reglas EXC-xxx derivan de la ausencia de una acción obligatoria explícita en el texto fuente, no de interpretación clínica adicional.
- Las reglas deben validarse con oncología antes de usarse sobre historias reales.
