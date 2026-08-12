# Árbol de decisión clínico — ESMO mTNBC (cáncer de mama triple negativo metastásico)

```text
mTNBC confirmado
  |
  +-- ¿Enfermedad metastásica confirmada por biopsia y reevaluación de
  |    receptores (ER, PgR, HER2)?
       |
       +-- No -> fuera del módulo (ver módulo de estadificación)
       |
       +-- Sí
            |
            +-- ¿PD-L1 positivo?
                 |
                 +-- Sí (PD-L1+)
                 |    |
                 |    +-- CPS >=10 y DFI >=6 meses tras (neo)adyuvancia
                 |    |    +-- Pembrolizumab + sacituzumab govitecan (preferido)
                 |    |    +-- Pembrolizumab + ChT (paclitaxel/nab-paclitaxel/
                 |    |         carboplatino-gemcitabina)
                 |    |
                 |    +-- Célula inmune PD-L1 >=1% y DFI >=12 meses tras adyuvancia
                 |    |    +-- Atezolizumab + nab-paclitaxel
                 |    |
                 |    +-- DFI insuficiente o datos limitados post-ICI (neo)adyuvante
                 |         +-- Revisión clínica / reevaluar elegibilidad de ICI
                 |
                 +-- No (PD-L1-) o no candidata a ICI
                      |
                      +-- gBRCA1/2 mutado (germinal)
                      |    +-- Olaparib
                      |    +-- Talazoparib
                      |    +-- Quimioterapia basada en carboplatino
                      |
                      +-- gBRCA1/2 wild type
                      |    |
                      |    +-- Recaída <6 meses tras adyuvancia
                      |    |    +-- Datopotamab deruxtecan (preferido, si disponible)
                      |    |
                      |    +-- Otros escenarios
                      |         +-- Datopotamab deruxtecan o sacituzumab govitecan
                      |         +-- Monoterapia con taxano
                      |         +-- Monoterapia con antraciclina (sin exposición
                      |              previa o si reexposición es posible)
                      |
                      +-- Insuficiencia orgánica inminente (cualquier estatus)
                           +-- Capecitabina (± bevacizumab) o taxano (± bevacizumab)

SEGUNDA LÍNEA Y SIGUIENTES (>=1 línea previa)
  |
  +-- gBRCA1/2 wild type
  |    +-- Sacituzumab govitecan, si no usado previamente (preferido)
  |    +-- ChT: eribulin, capecitabina o vinorelbina
  |
  +-- gBRCA1/2 o gPALB2 mutado
       +-- Olaparib o talazoparib, si PARPi no usado en primera línea
       +-- Quimioterapia basada en carboplatino

TRAS PROGRESIÓN (>=2 líneas previas)
  |
  +-- Sacituzumab govitecan, si no usado previamente
  +-- HER2-low
       +-- Trastuzumab deruxtecan (T-DXd)
```

## Notas

- El biomarcador PD-L1 usa dos ensayos distintos según el régimen (CPS para
  pembrolizumab, positividad de célula inmune para atezolizumab); deben
  modelarse como variables independientes, no como un único campo "PD-L1+/-".
- El DFI (intervalo libre de enfermedad) exigido difiere según el régimen de
  ICI (6 meses para pembrolizumab, 12 meses para atezolizumab) y debe
  validarse contra la fecha de fin de (neo)adyuvancia con inmunoterapia, no
  contra la fecha de fin de cualquier adyuvancia.
- HER2-low (para T-DXd) requiere reevaluación de HER2 en la biopsia
  metastásica, no en el tumor primario original.
- Ninguna de estas ramas ejecuta automáticamente una suspensión del
  tratamiento; los avisos de PARPi/línea previa son informativos.

## Salidas del módulo

| Salida | Significado |
|---|---|
| `supports_prescription` | Existe una regla positiva aplicable. |
| `requires_clinical_review` | El caso necesita revisión experta. |
| `advisory` | Aviso no vinculante (p. ej. no repetir PARPi). |
| `not_evaluable` | Faltan hechos clínicos indispensables (p. ej. estatus PD-L1 o gBRCA). |
| `outside_scope` | El caso corresponde a otro módulo (luminal, HER2+, o enfermedad no metastásica). |
| `historical_guideline_version_required` | Debe consultarse la guía vigente en la fecha del evento. |

## Nota de implementación

Este árbol corresponde al módulo `esmo_breast_metastatic_tnbc`. Al igual que
en `nsclc_metastatic_non_oncogene`, cada archivo de reglas (eligibility,
exclusion, continuation) debe probarse de forma independiente; la ejecución
completa del árbol depende del orquestador de `pathway.yaml`.
