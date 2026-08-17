# Borrador de analisis comparativo -- `esmo_nsclc_early_locally_advanced`

## Cambios ya redactados como regla computable

- (OK) El documento nuevo introduce RET como biomarcador ESCAT I-A que debe testearse junto con EGFR y ALK ('EGFR, ALK, RET and PD-L1 testing') antes de decidir la secuencia sistémica en NSCLC resecable estadio II-III, y excluye explícitamente a los pacientes con reordenamiento de RET de la vía de quimioterapia-ICI ('EGFR mutation or ALK/RET rearrangement' se separa de 'EGFR WT and ALK WT' en el algoritmo). El módulo actual no tiene la variable `ret_status` ni ninguna regla de exclusión molecular para RET, por lo que un paciente con RET reordenado, EGFR wild-type y ALK negativo pasaría erróneamente por la vía positiva de pembrolizumab en `pathway.yaml` (nodo `evaluate_alk` -> `evaluate_treatment_phase`).
  - Archivos: rules/exclusions.yaml, variables.yaml, pathway.yaml
  - Fuente: Molecular testing for RET alterations [ESCAT score: I-A] is recommended for patients with stage IB (>3 cm or high risk)-IIIA NSCLC to identify patients suitable for adjuvant selpercatinib [I, A]. ... EGFR mutation or ALK/RET rearrangement -> ChT-ICI ineligible pathway

- (OK) Las reglas positivas de pembrolizumab (ESMO-NSCLC-ELA-NEO-001 en neoadjuvant.yaml y ESMO-NSCLC-ELA-ADJ-002 en adjuvant.yaml) actualmente solo exigen egfr_status=wild_type y alk_status=negative como prerrequisito molecular. Deben incorporar también ret_status=negative/wild_type como condición, dado que el documento nuevo define la población elegible para quimioterapia-ICI (incluyendo pembrolizumab) como 'EGFR and ALK and RET wild-type disease'.
  - Archivos: rules/neoadjuvant.yaml, rules/adjuvant.yaml
  - Fuente: For EGFR and ALK and RET wild-type disease: Neoadjuvant or perioperative chemotherapy–immune checkpoint inhibitor is recommended for resectable stage II-III NSCLC [I, A]

- (OK) La descripción de `biomarker_testing_complete` en variables.yaml define la evaluación mínima como EGFR, ALK y PD-L1. El documento nuevo especifica reiteradamente que la secuencia sistémica óptima requiere biomarcadores 'EGFR, ALK, RET and PD-L1 at a minimum'. La definición y las reglas que la usan (ELIG-002, EXC-010) deben actualizarse para incluir RET.
  - Archivos: variables.yaml, rules/eligibility.yaml, rules/exclusions.yaml
  - Fuente: Optimal sequencing of systemic therapy (neoadjuvant, perioperative or adjuvant) should be defined by a multidisciplinary team prior to treatment decision-making, including biomarker testing for EGFR, ALK, RET and PD-L1 at a minimum [V, A].

- (OK) La regla ESMO-NSCLC-ELA-EXC-003 (estadio III irresecable) tiene una interpretation_note que menciona solo osimertinib (EGFR mutado) y durvalumab (EGFR WT) como alternativas de consolidación no-pembrolizumab. El documento nuevo agrega sugemalimab como opción adicional de consolidación en EGFR WT sin alteraciones de ALK/ROS1. Esto no cambia el veredicto de la regla (sigue siendo flag_for_expert_review ante cualquier prescripción de pembrolizumab en este contexto), pero la nota descriptiva debería actualizarse para reflejar el panorama terapéutico completo.
  - Archivos: rules/exclusions.yaml
  - Fuente: Sugemalimab consolidation [ESMO-MCBS v2.0 score: 3; EMA approved...] is recommended for up to 24 months after concurrent or sequential chemoradiotherapy in patients with EGFR wild-type and no ALK or ROS1 genomic tumour aberrations, stage III NSCLC without disease progression [I, A].

## Cambios que requieren verificacion humana antes de convertirse en regla

- El documento nuevo distingue dos recomendaciones de PD-L1 con grados de evidencia distintos: testeo previo a decisión pre/perioperatoria con ICI [IV, A] (igual a la regla EXC-011 actual) y testeo obligatorio para todos los casos resecados estadio II-IIIA sin ICI preoperatorio, para informar decisión de inmunoterapia adyuvante, con grado superior [I, A]. No es claro si esto amerita una regla adicional separada con mayor prioridad de auditoría para el escenario adyuvante puro, o si la regla única actual (advisory, IV/A) es suficiente. Falta contexto para decidir si se debe escalar el audit_effect en el contexto adyuvante.
  - Fuente: Tumour PD-L1 testing is recommended for all resected stage II-IIIA NSCLC cases if preoperative chemotherapy–immune checkpoint inhibitor was not administered, to inform adjuvant immunotherapy decisions [I, A].

- El documento nuevo introduce un subgrupo específico -tumores del surco superior (T3-4 N0-1)- para los que se recomienda quimiorradioterapia neoadyuvante seguida de cirugía, en lugar de la secuencia de quimioterapia-ICI perioperatoria. El módulo actual no tiene ninguna variable que identifique 'superior sulcus tumour' ni el subestadio T3-4N0-1, por lo que estos pacientes podrían recibir incorrectamente una recomendación de soporte para la secuencia pembrolizumab perioperatoria (regla NEO-001) si cumplen los demás criterios de estadio II-III. Falta definición clínica de cómo representar este subgrupo antes de crear una exclusión.
  - Fuente: Neoadjuvant chemoradiotherapy followed by surgery can be recommended for patients with superior sulcus tumours (T3-4 N0-1) after multidisciplinary team discussion [III, B].

- El documento nuevo indica que, en enfermedad N2, la elección entre terapia sistémica neoadyuvante/perioperatoria y quimiorradioterapia definitiva concurrente debe discutirse individualmente por un MDT experimentado. La variable `node_positive` existe en el módulo pero no se usa en ninguna regla ni en pathway.yaml. No está claro si esta discusión debe modelarse como una condición adicional de mdt_review_completed antes de aplicar NEO-001/ADJ-002, o si permanece fuera del alcance computable actual.
  - Fuente: For patients with N2 disease, resectability and selection for neoadjuvant or perioperative systemic therapy versus concurrent definitive chemoradiotherapy should be discussed for each individual patient by an experienced multidisciplinary team [V, A].

## Sin cambios detectados

(no se registraron confirmaciones explicitas de 'sin cambio')