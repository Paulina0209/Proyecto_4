# Matriz clínica — ESMO RCC localizado/adyuvante

## 1. Identificación

- **Módulo:** `esmo_renal_cell_carcinoma_localized_adjuvant`
- **Fuente:** *Renal cell carcinoma: ESMO Clinical Practice Guideline for diagnosis, treatment and follow-up*
- **Versión fuente:** actualización de mayo de 2024; disponible en línea el 22 de mayo de 2024.
- **DOI:** `10.1016/j.annonc.2024.05.537`
- **Medicamento auditado:** pembrolizumab.
- **Estado:** borrador computable con validación técnica inicial; validación clínica pendiente.

## 2. Alcance

### Incluye

1. ccRCC operable con resección completa y riesgo intermedio-alto según KEYNOTE-564:
   - pT2, grado 4 o diferenciación sarcomatoide, N0, M0;
   - pT3, cualquier grado, N0, M0.
2. ccRCC operable con riesgo alto:
   - pT4, cualquier grado, N0, M0;
   - cualquier pT, cualquier grado, N1, M0.
3. ccRCC oligometastásico tratado completamente y convertido a M1 NED.
4. Inicio, duración, finalización, recurrencia y toxicidad del pembrolizumab adyuvante.

### Excluye

- enfermedad avanzada o metastásica activa;
- histología no clara como ruta positiva adyuvante de pembrolizumab;
- enfermedad residual o resección incompleta;
- riesgo bajo fuera de los criterios positivos de KEYNOTE-564;
- registros anteriores al 22 de mayo de 2024 sin recuperar la versión histórica aplicable.

## 3. Decisión de separación modular

Los casos M1 NED se conservan en este módulo porque no tienen enfermedad metastásica activa y el objetivo del pembrolizumab es adyuvante después del control local completo. La enfermedad M1 activa se envía al módulo `esmo_renal_cell_carcinoma_advanced_metastatic`.

## 4. Variables clínicas esenciales

| Variable | Propósito |
|---|---|
| `rcc_histology` | Confirmar ccRCC, indicación histológica de la recomendación adyuvante. |
| `pathological_t_stage` | Clasificar pT2, pT3 o pT4. |
| `pathological_n_status` | Diferenciar N0 de enfermedad ganglionar positiva. |
| `metastatic_status` | Distinguir M0, M1 NED y M1 activo. |
| `nuclear_grade` | Identificar pT2 grado 4. |
| `sarcomatoid_features` | Identificar pT2 con diferenciación sarcomatoide. |
| `complete_resection` | Confirmar resección completa. |
| `no_evidence_of_disease` | Confirmar ausencia de enfermedad activa. |
| `weeks_since_complete_resection` | Verificar la ventana de inicio de hasta 12 semanas. |
| `months_on_adjuvant_pembrolizumab` | Revisar finalización hasta un año. |
| `adjuvant_pembrolizumab_cycles_completed` | Control contextual del esquema de 17 ciclos. |
| `ici_suitability` | Evitar inferir soporte cuando la inmunoterapia está contraindicada. |
| `guideline_temporal_applicability` | Evitar aplicar retrospectivamente la versión 2024. |

## 5. Catálogo de reglas

| ID | Escenario | Resultado | Evidencia ESMO | MCBS |
|---|---|---|---|---|
| `ESMO-RCC-LOC-ELIG-001` | ccRCC resecado, NED y dentro del alcance | Entrada al módulo | Sin gradación específica de alcance | — |
| `ESMO-RCC-LOC-ADJ-001` | pT2 grado 4 o sarcomatoide, N0 M0 | Apoya pembrolizumab adyuvante | I, A | v1.1 A |
| `ESMO-RCC-LOC-ADJ-002` | pT3, N0 M0 | Apoya pembrolizumab adyuvante | I, A | v1.1 A |
| `ESMO-RCC-LOC-ADJ-003` | pT4, N0 M0 | Apoya pembrolizumab adyuvante | I, A | v1.1 A |
| `ESMO-RCC-LOC-ADJ-004` | cualquier pT, N1 M0 | Apoya pembrolizumab adyuvante | I, A | v1.1 A |
| `ESMO-RCC-LOC-ADJ-005` | oligometastásico completamente resecado, M1 NED | Puede ofrecerse pembrolizumab adyuvante | II, B | v1.1 A |
| `ESMO-RCC-LOC-CONT-001` | 12 meses de tratamiento | Revisar finalización planificada | I, A | v1.1 A |
| `ESMO-RCC-LOC-CONT-002` | 17 ciclos completados | Punto de control del protocolo | Contexto de ensayo, sin gradación propia | — |
| `ESMO-RCC-LOC-CONT-003` | recurrencia durante adyuvancia | Revisión clínica | Límite clínico no graduado | — |
| `ESMO-RCC-LOC-CONT-004` | interrupción por toxicidad | Revisión clínica | Límite clínico no graduado | — |
| `ESMO-RCC-LOC-CONT-005` | intervalo de imagen >6 meses en primeros 2 años de alto riesgo | Aviso de seguimiento | IV, B | — |
| `ESMO-RCC-LOC-EXC-000` | prescripción anterior a la versión | Recuperar guía histórica | Gobernanza temporal | — |
| `ESMO-RCC-LOC-EXC-001` | enfermedad metastásica activa | Enviar a módulo avanzado | Límite modular | — |
| `ESMO-RCC-LOC-EXC-002` | histología no clara | Revisión clínica | Límite de indicación | v1.1 A |
| `ESMO-RCC-LOC-EXC-003` | riesgo bajo | Revisión clínica | Límite de criterios KEYNOTE-564 | v1.1 A |
| `ESMO-RCC-LOC-EXC-004` | inicio después de 12 semanas | Revisión clínica | I, A | v1.1 A |
| `ESMO-RCC-LOC-EXC-005` | enfermedad residual o M1 activa | Revisión clínica | Límite de indicación | — |
| `ESMO-RCC-LOC-EXC-006` | consejería sobre eventos adversos no documentada | Aviso documental | I, A | v1.1 A |

## 6. Interpretación de auditoría

- `supports_prescription`: la prescripción coincide con una ruta positiva.
- `requires_clinical_review`: existe un límite, excepción o información contextual que impide declarar automáticamente desviación.
- `outside_scope`: el caso debe ser evaluado por otro módulo.
- `advisory`: aviso de seguimiento, duración o calidad documental.
- `not_evaluable`: faltan datos necesarios para decidir.

## 7. Validación pendiente

1. Confirmar con oncología/urología la traducción local de N1 y M1 NED.
2. Verificar cómo se registra el grado nuclear y la diferenciación sarcomatoide en la historia clínica.
3. Definir la política institucional para inicios posteriores a 12 semanas.
4. Validar la equivalencia entre ciclos registrados y duración real.
5. Revisar casos reales de 2024 con la versión de guía vigente en la fecha de prescripción.
