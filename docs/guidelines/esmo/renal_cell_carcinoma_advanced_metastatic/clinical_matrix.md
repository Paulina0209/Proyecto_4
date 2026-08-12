# Matriz clínica — ESMO RCC avanzado/metastásico

## 1. Identificación

- **Módulo:** `esmo_renal_cell_carcinoma_advanced_metastatic`
- **Fuente:** *Renal cell carcinoma: ESMO Clinical Practice Guideline for diagnosis, treatment and follow-up*
- **Versión fuente:** actualización de mayo de 2024; disponible en línea el 22 de mayo de 2024.
- **DOI:** `10.1016/j.annonc.2024.05.537`
- **Medicamento auditado:** pembrolizumab.
- **Estado:** borrador computable con validación técnica inicial; validación clínica pendiente.

## 2. Alcance

### Incluye

1. ccRCC avanzado o metastásico en primera línea:
   - pembrolizumab + lenvatinib;
   - pembrolizumab + axitinib;
   - ambos independientemente del riesgo IMDC.
2. pRCC avanzado:
   - pembrolizumab en monoterapia como alternativa;
   - pembrolizumab + lenvatinib como alternativa;
   - pembrolizumab en líneas posteriores si no fue administrado previamente.
3. RCC cromófobo avanzado:
   - pembrolizumab + lenvatinib como opción.
4. RCC con histología predominantemente sarcomatoide:
   - pembrolizumab + axitinib;
   - pembrolizumab + lenvatinib.
5. Duración, seguimiento, progresión y toxicidad.

### Excluye

- enfermedad localizada o locorregional operable;
- M1 NED después de tratamiento local completo;
- histologías con otra ruta principal: conductos colectores, SMARCB1-deficiente y FH-deficiente;
- reutilización de PD-(L)1 después de progresión con PD-1 de primera línea como ruta positiva.

## 3. Variables clínicas esenciales

| Variable | Propósito |
|---|---|
| `rcc_histology` | Seleccionar la ruta ccRCC, pRCC, cromófoba o sarcomatoide. |
| `histology_documented` | Generar una alerta explícita cuando el subtipo no está documentado. |
| `disease_setting` | Confirmar enfermedad avanzada o metastásica activa. |
| `treatment_line` | Distinguir primera línea y líneas posteriores. |
| `imdc_risk_group` | Registrar pronóstico; no limita las dos combinaciones de pembrolizumab en ccRCC. |
| `ici_suitability` | Identificar contraindicación o falta de disponibilidad de ICI. |
| `prior_pd1_targeted_therapy` | Detectar exposición previa a PD-1. |
| `progression_on_prior_pd1` | Aplicar la recomendación negativa de nueva terapia PD-(L)1. |
| `prior_pembrolizumab` | Evitar interpretar como nueva opción una molécula ya utilizada en pRCC. |
| `months_on_ici` | Revisar finalización después de dos años. |
| `imaging_interval_months` | Revisar CT cada 2-4 meses durante tratamiento. |
| `prescribed_antineoplastic_drugs` | Reconocer los componentes del régimen. |

## 4. Catálogo de reglas

| ID | Escenario | Resultado | Evidencia ESMO | MCBS |
|---|---|---|---|---|
| `ESMO-RCC-ADV-ELIG-001` | RCC confirmado con enfermedad avanzada/metastásica activa | Entrada al módulo | I, A para confirmación histológica | — |
| `ESMO-RCC-ADV-FL-001` | ccRCC primera línea: pembrolizumab + lenvatinib | Apoya régimen | I, A | v1.1 4 |
| `ESMO-RCC-ADV-FL-002` | ccRCC primera línea: pembrolizumab + axitinib | Apoya régimen | I, A | v1.1 4 |
| `ESMO-RCC-ADV-FL-003` | pRCC primera línea: pembrolizumab solo | Alternativa | III, B | — |
| `ESMO-RCC-ADV-FL-004` | pRCC primera línea: pembrolizumab + lenvatinib | Puede considerarse alternativa | III, B | — |
| `ESMO-RCC-ADV-FL-005` | cromófobo avanzado: pembrolizumab + lenvatinib | Puede utilizarse | III, C | — |
| `ESMO-RCC-ADV-FL-006` | sarcomatoide predominante: pembrolizumab + axitinib | Opción ICI preferida | III, A | — |
| `ESMO-RCC-ADV-FL-007` | sarcomatoide predominante: pembrolizumab + lenvatinib | Opción ICI preferida | III, A | — |
| `ESMO-RCC-ADV-SL-001` | pRCC posterior, pembrolizumab no usado | Apoya con cautela | IV, C | — |
| `ESMO-RCC-ADV-SL-002` | nueva terapia PD-(L)1 tras progresión con PD-1 | Posible desviación | I, D | — |
| `ESMO-RCC-ADV-CONT-001` | ICI durante 24 meses | Considerar finalización | IV, B | — |
| `ESMO-RCC-ADV-CONT-002` | intervalo de CT >4 meses | Aviso de seguimiento | IV, B | — |
| `ESMO-RCC-ADV-CONT-003` | progresión durante pembrolizumab | Revisión clínica | No obliga suspensión automática | — |
| `ESMO-RCC-ADV-CONT-004` | interrupción por toxicidad | Revisión clínica | Límite de seguridad | — |
| `ESMO-RCC-ADV-EXC-000` | prescripción anterior a la versión | Recuperar guía histórica | Gobernanza temporal | — |
| `ESMO-RCC-ADV-EXC-001` | M1 NED | Enviar al módulo adyuvante | II, B | v1.1 A |
| `ESMO-RCC-ADV-EXC-002` | enfermedad localizada operable | Enviar al módulo adyuvante | Límite modular | — |
| `ESMO-RCC-ADV-EXC-003` | ICI contraindicada o no disponible | Revisión clínica | Contexto de alternativas | — |
| `ESMO-RCC-ADV-EXC-004` | pembrolizumab solo en primera línea ccRCC | Revisión clínica | La ruta positiva es combinada | v1.1 4 |
| `ESMO-RCC-ADV-EXC-005` | conductos colectores, SMARCB1 o FH-deficiente | Revisión de otra estrategia | Histología específica | — |
| `ESMO-RCC-ADV-EXC-006` | histología desconocida | Solicitar información | I, A | — |

## 5. Consideraciones metodológicas

- La guía no establece preferencia entre pembrolizumab-lenvatinib y pembrolizumab-axitinib para ccRCC.
- El riesgo IMDC debe registrarse, pero no restringe estas dos combinaciones.
- La monoterapia con pembrolizumab en pRCC y su uso en líneas posteriores aparecen con menor certeza y con estatus regulatorio no aprobado por EMA/FDA según la fuente.
- La recomendación negativa de nueva terapia PD-(L)1 después de progresión es de clase; se aplica a pembrolizumab sin presentarla como una afirmación originalmente redactada solo para ese fármaco.
- La progresión radiológica no debe causar una suspensión automática sin juicio clínico.

## 6. Validación pendiente

1. Validar la clasificación histológica local y sus equivalencias terminológicas.
2. Confirmar cómo se registra la línea terapéutica y la exposición previa a ICI.
3. Revisar la política institucional para progresión radiológica y pseudoprogresión.
4. Validar el catálogo de regímenes con farmacia oncológica.
5. Resolver permisos de uso antes de distribución pública.
