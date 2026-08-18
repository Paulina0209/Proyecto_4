# Borrador de analisis comparativo -- `esmo_nsclc_early_locally_advanced`

## ATENCION: archivos con errores de generacion

- `rules/exclusions.yaml`: Intento 2: se corto por limite de max_tokens.

## Cambios ya redactados como regla computable

- (OK) Nueva recomendación de testeo molecular de RET (ESCAT I-A) para NSCLC resecable estadio IB (>3cm o alto riesgo)-IIIA, para identificar candidatos a selpercatinib adyuvante. El módulo actual no modela 'ret_status' en absoluto (ni como variable ni en pathway.yaml ni en exclusions.yaml), por lo que un paciente con fusión de RET no es actualmente excluido de la ruta de pembrolizumab de forma análoga a EGFR/ALK. Es necesario crear la variable ret_status, un nodo de evaluación análogo a evaluate_egfr/evaluate_alk, y una regla de exclusión equivalente a EXC-004/EXC-005.
  - Archivos: variables.yaml, pathway.yaml, rules/exclusions.yaml
  - Fuente: Molecular testing for RET alterations [ESCAT score: I-A] is recommended for patients with resectable stage IB (>3 cm or high risk)-IIIA NSCLC to identify patients suitable for adjuvant selpercatinib

- (OK) biomarker_testing_complete se define actualmente como disponibilidad mínima de EGFR, ALK y PD-L1. El documento nuevo agrega recomendaciones de testeo molecular con nivel de evidencia explícito también para RET en el rango de estadios resecables pertinente al módulo, por lo que la definición operativa de 'biomarcadores completos' debería ampliarse para incluir RET cuando corresponda a la ruta perioperatoria/adyuvante.
  - Archivos: variables.yaml, rules/eligibility.yaml, rules/exclusions.yaml
  - Fuente: Molecular testing for RET alterations [ESCAT score: I-A] is recommended... Molecular testing for ALK alterations [ESCAT score: I-A] is recommended for patients with resectable stage II (≥4 cm)-IIIA NSCLC

- (con errores, ver arriba) El documento nuevo separa la recomendación de testeo de PD-L1 en dos escenarios con niveles de evidencia distintos: (1) IV,A cuando se considera quimioterapia-ICI pre/perioperatoria, y (2) I,A (evidencia más fuerte) para todos los casos resecados estadio II-IIIA en que NO se administró ICI preoperatorio, para informar decisiones de inmunoterapia adyuvante. La regla actual EXC-011 modela un único nivel de evidencia (IV,A) sin distinguir el contexto adyuvante-solo, que en realidad tiene I,A.
  - Archivos: rules/exclusions.yaml
  - Fuente: Tumour PD-L1 testing is recommended for all resected stage II-IIIA NSCLC cases if preoperative chemotherapy–immune checkpoint inhibitor was not administered, to inform adjuvant immunotherapy decisions | I, A

- (OK) Nueva recomendación explícita: la detección o el aclaramiento de ctDNA después de tratamiento con intención curativa NO se recomienda para guiar escalamiento o desescalamiento de tratamiento fuera de ensayos clínicos [IV, E]. Esto es directamente relevante para la regla PERI-002 (revisión de omisión adyuvante basada en pCR), ya que introduce un biomarcador distinto (ctDNA) con una recomendación negativa explícita y graduada que actualmente no está modelada en ninguna variable ni regla del módulo.
  - Archivos: variables.yaml, rules/perioperative.yaml
  - Fuente: ctDNA detection or clearance after curative-intent treatment is not recommended to guide treatment escalation or de-escalation outside of clinical trials | IV, E

- (con errores, ver arriba) El documento nuevo detalla el panorama completo de terapia de consolidación para NSCLC estadio III irresecable: osimertinib (EGFR mutado, ESCAT I-A, MCBS v2.0 score 4), durvalumab (EGFR wild-type, ahora diferenciado por CRT concurrente [I,A] vs secuencial [II,B], MCBS v2.0 score 4) y una opción nueva no mencionada antes en el módulo: sugemalimab (EGFR wild-type sin alteraciones ALK/ROS1, hasta 24 meses, MCBS v2.0 score 3, I,A). Ninguna de estas opciones involucra pembrolizumab, por lo que la lógica de la regla EXC-003 (que dirige a revisión cualquier prescripción de pembrolizumab en este contexto) sigue siendo correcta, pero su interpretation_note actual solo menciona osimertinib/durvalumab y ya no refleja el panorama terapéutico completo descrito por la guía.
  - Archivos: rules/exclusions.yaml
  - Fuente: Sugemalimab consolidation [ESMO-MCBS v2.0 score: 3] is recommended for up to 24 months after concurrent or sequential chemoradiotherapy in patients with EGFR wild-type and no ALK or ROS1 genomic tumour aberrations, stage III NSCLC without disease progression

## Cambios que requieren verificacion humana antes de convertirse en regla

- El documento nuevo corresponde a la ESMO Living Guideline v1.2 (junio 2026), una actualización posterior a la versión fija 2025-08-28 usada actualmente como base temporal del módulo. No está claro si esta actualización debe tratarse como una nueva 'fixed_source_version' completa (con nueva fecha de corte para guideline_temporal_applicability) o como una actualización incremental de la misma guía madre. Se requiere criterio clínico/editorial antes de modificar metadata.yaml.
  - Fuente: Early and Locally Advanced Non-Small-Cell Lung Cancer — ESMO Living Guideline, v1.2 June 2026

- Tanda 2/3: la deteccion se corto por limite de max_tokens (no es un error de formato JSON) -- puede faltar informacion de esta tanda, revisar manualmente.
  - Fuente: ```json
[
  {
    "description": "El documento nuevo (ESMO Living Guideline v1.2, junio 2026) exige testeo de RET además de EGFR, ALK y PD-L1 antes de decidir la secuencia sistémica, y define una vía positiva ESCAT I-A específica (adyuvante con selpercatinib) para NSCLC resecable con reordenamiento de RET, que se agrupa junto con EGFR mutado/ALK reordenado en la rama que omite la inmunoterapia neoadyuvante/perioperatoria y va directo a cirugía. El módulo actual no modela ret_status en absoluto, 

- El documento nuevo incorpora un bloque detallado de seguimiento y supervivencia (frecuencia de TC, uso selectivo de PET-CT tras SBRT/CRT, seguimiento personalizado según riesgo de recurrencia) que no está representado en ningún archivo del módulo actual, el cual solo modela continuidad/toxicidad/progresión específicas de pembrolizumab. No está claro si este protocolo general de vigilancia debe incorporarse a este módulo (ampliando su alcance) o si corresponde a un módulo de seguimiento separado.
  - Fuente: Surveillance can be recommended at a minimum of every 6 months for 2 years, then annually until 5 years from definitive therapy with visits comprising history, physical examination, bloodwork and preferably contrast-enhanced chest CT scan including the adrenals

- El documento nuevo se identifica como 'ESMO Early and Locally Advanced NSCLC Living Guideline v1.2 June 2026', una versión de guía viviente posterior a la fuente fija registrada en metadata.yaml (28 de agosto de 2025, DOI 10.1016/j.annonc.2025.08.003). No está claro si el enfoque de 'fixed_source_version: true' y la lógica de guideline_temporal_applicability deben actualizarse para reconocer esta nueva versión viviente, ni si el contenido específico de pembrolizumab cambió en v1.2 respecto a la versión original de 2025.
  - Fuente: ESMO Early and Locally Advanced NSCLC Living Guideline v1.2 June 2026

## Sin cambios detectados

- El nuevo diagrama de manejo del estadio I confirma que, incluso para tumores T>3-4cm N0 con testeo EGFR/RET, las únicas rutas sistémicas recomendadas son osimertinib o selpercatinib adyuvantes (o vigilancia); no aparece ninguna ruta de pembrolizumab en estadio I. Esto es consistente con la lógica actual de EXC-001 (pembrolizumab en estadio I sin ruta respaldada por el módulo) y no requiere cambios en las reglas de pembrolizumab.
- Las recomendaciones sobre cribado con TC de baja dosis, cesación tabáquica, diagnóstico patológico (clasificación OMS 2021), métodos de biopsia, estadificación clínica/patológica IASLC-TNM, estadificación ganglionar y evaluación de riesgo pre-tratamiento (función cardiopulmonar) son nuevas en el documento pero quedan fuera del alcance computable actual del módulo, que se centra exclusivamente en decisiones de prescripción de pembrolizumab. No generan cambios en las reglas existentes.
- Se detallan recomendaciones específicas de quimiorradioterapia concurrente/secuencial y dosis de radioterapia (60 Gy) para NSCLC estadio III irresecable. Esta información queda fuera del alcance declarado del módulo (drug_of_interest: pembrolizumab) y no requiere ninguna variable o regla nueva; confirma que el enrutamiento actual a evaluate_unresectable_context / exclusions.yaml sigue siendo válido.