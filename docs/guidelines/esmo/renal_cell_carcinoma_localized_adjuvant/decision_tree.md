# Árbol de decisión — ESMO RCC localizado/adyuvante

```text
INICIO
  |
  +-- ¿La versión ESMO del 22-05-2024 aplica a la fecha?
  |      |
  |      +-- NO / anterior --> recuperar versión histórica --> revisión clínica
  |      |
  |      +-- SÍ
  |
  +-- ¿Diagnóstico e histopatología de RCC confirmados?
  |      |
  |      +-- NO / desconocido --> no evaluable
  |      |
  |      +-- SÍ
  |
  +-- ¿Histología clear-cell?
  |      |
  |      +-- NO --> fuera de la ruta positiva adyuvante --> revisión clínica
  |      |
  |      +-- SÍ
  |
  +-- ¿Existe enfermedad avanzada o metastásica activa?
  |      |
  |      +-- SÍ --> enviar a renal_cell_carcinoma_advanced_metastatic
  |      |
  |      +-- NO
  |
  +-- ¿Resección completa y sin evidencia de enfermedad?
  |      |
  |      +-- NO --> revisión: no es una ruta adyuvante estándar
  |      |
  |      +-- SÍ
  |
  +-- CLASIFICAR RIESGO
         |
         +-- pT2 + (grado 4 O sarcomatoide) + N0 M0
         |      --> pembrolizumab adyuvante respaldado [I,A; MCBS A]
         |
         +-- pT3 + N0 M0
         |      --> pembrolizumab adyuvante respaldado [I,A; MCBS A]
         |
         +-- pT4 + N0 M0
         |      --> pembrolizumab adyuvante respaldado [I,A; MCBS A]
         |
         +-- cualquier pT + N1 M0
         |      --> pembrolizumab adyuvante respaldado [I,A; MCBS A]
         |
         +-- oligometastásico + metastasectomía completa + M1 NED
         |      --> pembrolizumab puede ofrecerse [II,B; MCBS A]
         |
         +-- riesgo bajo / no clasificable
                --> revisión clínica

ANTES DE APOYAR LA PRESCRIPCIÓN
  |
  +-- ¿Inicio <=12 semanas tras resección?
  |      +-- NO --> revisión clínica
  |
  +-- ¿ICI clínicamente adecuada?
         +-- NO / incierto --> revisión clínica

SEGUIMIENTO
  |
  +-- 12 meses o 17 ciclos --> revisar finalización planificada
  +-- recurrencia --> revisión clínica
  +-- toxicidad --> revisión clínica
  +-- seguimiento de alto riesgo en primeros 2 años --> revisar intervalo de imágenes
```

## Nota técnica

El motor genérico actual evalúa archivos de reglas por separado. La versión de producción deberá ejecutar primero `eligibility.yaml`, después el `pathway.yaml` y finalmente las reglas clínicas aplicables.
