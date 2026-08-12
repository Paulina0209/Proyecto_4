# Matriz clínica: ESMO mTNBC (cáncer de mama triple negativo metastásico)

## Estado

Borrador computable pendiente de validación clínica. Basado en: *Metastatic
breast cancer: ESMO Clinical Practice Guideline for diagnosis, treatment and
follow-up* (Ann Oncol, 2026), secciones "Diagnosis, pathology and molecular
biology" (parte TNBC de la Figura 1) y "Management of metastatic TNBC"
(Figuras 8 y 9). Solo se incluyen reglas relativas al subtipo triple negativo;
las reglas de luminal (ER+) y HER2-positivo pertenecen a otros módulos.

## Inventario de reglas — primera línea

| ID | Escenario | Consecuente | Evidencia nativa | Efecto de auditoría |
|---|---|---|---|---|
| FL-001 | Primera línea, PD-L1 CPS ≥10, DFI ≥6 meses tras (neo)adyuvancia | Pembrolizumab + sacituzumab govitecan | I, A | Respalda |
| FL-002 | Primera línea, PD-L1 CPS ≥10, DFI ≥6 meses tras (neo)adyuvancia | Pembrolizumab + ChT (paclitaxel, nab-paclitaxel o carboplatino-gemcitabina) | I, A; MCBS 4 | Respalda |
| FL-003 | Primera línea, PD-L1 (célula inmune) ≥1%, DFI ≥12 meses tras adyuvancia | Atezolizumab + nab-paclitaxel | II, A; MCBS 3 | Respalda condicional |
| FL-004 | Primera línea, PD-L1 negativo, gBRCA1/2 mutado | Olaparib | I, A | Respalda (no aprobado EMA/FDA en 1ª línea) |
| FL-005 | Primera línea, PD-L1 negativo, gBRCA1/2 mutado | Talazoparib | I, A | Respalda (no aprobado EMA/FDA en 1ª línea) |
| FL-006 | Primera línea, PD-L1 negativo, gBRCA1/2 mutado | Quimioterapia basada en carboplatino | II, A | Respalda |
| FL-007 | Primera línea, PD-L1 negativo o no candidata a ICI, gBRCA1/2 wt, recaída <6 meses tras adyuvancia | Datopotamab deruxtecan (preferido) | I, A | Respalda |
| FL-008 | Primera línea, PD-L1 negativo o no candidata a ICI, gBRCA1/2 wt | Sacituzumab govitecan | I, A | Respalda |
| FL-009 | Primera línea, PD-L1 negativo o no candidata a ICI, gBRCA1/2 wt | Monoterapia con taxano | I, A | Respalda |
| FL-010 | Primera línea, PD-L1 negativo o no candidata a ICI, gBRCA1/2 wt, sin exposición previa a antraciclina o reexposición posible | Monoterapia con antraciclina | I, A | Respalda |
| FL-011 | Primera línea, insuficiencia orgánica inminente (cualquier estatus PD-L1/BRCA) | Capecitabina (± bevacizumab) o taxano (± bevacizumab) | I, B/C | Respalda (preferencia por rapidez de respuesta) |

## Inventario de reglas — segunda línea y siguientes

| ID | Escenario | Consecuente | Evidencia nativa | Efecto de auditoría |
|---|---|---|---|---|
| SL-001 | ≥1 línea previa, gBRCA1/2 wt, sacituzumab govitecan no usado previamente | Sacituzumab govitecan (preferido) | I, A; MCBS 5 | Respalda |
| SL-002 | ≥1 línea previa, gBRCA1/2 wt | ChT: eribulin, capecitabina o vinorelbina | I, B | Respalda |
| SL-003 | ≥1 línea previa, gBRCA1/2 o gPALB2 mutado, PARPi no usado en 1ª línea | Olaparib o talazoparib | I, A | Respalda |
| SL-004 | ≥1 línea previa, gBRCA1/2 mutado | Quimioterapia basada en carboplatino | II, A | Respalda |
| TL-001 | ≥2 líneas previas (tras progresión), sacituzumab govitecan no usado previamente | Sacituzumab govitecan | I, A; MCBS 5 | Respalda |
| TL-002 | ≥2 líneas previas (tras progresión), HER2-low | Trastuzumab deruxtecan (T-DXd) | II, B; MCBS 4 | Respalda |

## Inventario de reglas — exclusión y continuación

| ID | Escenario | Consecuente | Evidencia nativa | Efecto de auditoría |
|---|---|---|---|---|
| EXC-001 | PD-L1 negativo y pembrolizumab/atezolizumab prescrito en 1ª línea | Combinación con ICI no respaldada por biomarcador | I, A | Posible desviación |
| EXC-002 | DFI insuficiente (<6 meses para pembrolizumab, <12 para atezolizumab) tras ICI (neo)adyuvante y reinicio de ICI en 1ª línea | Datos limitados; reevaluar indicación | I, A | Revisión |
| CONT-001 | gBRCA1/2 wt, PD-L1 negativo, ≥2 líneas previas | Selección de línea depende de exposición previa, DFI y preferencia de la paciente | V, B | Aviso |
| CONT-002 | PARPi usado en primera línea | No repetir PARPi en líneas subsecuentes | I, A | Aviso |

## Decisiones metodológicas

- Las reglas de clase se identifican como `class_level`.
- PD-L1 se evalúa con dos biomarcadores distintos según el régimen: CPS (combined
  positive score, para pembrolizumab) vs. positividad en célula inmune (para
  atezolizumab); no son intercambiables y deben modelarse como campos separados.
- Los límites inferidos no reciben grados inventados.
- La recomendación positiva no se invierte automáticamente.
- La prioridad de la alerta se deriva después de establecer concordancia.
- Solo se incluyen reglas del subtipo TNBC; luminal y HER2-positivo son módulos
  separados.
- Las reglas deben validarse con oncología antes de usarse sobre historias reales.
