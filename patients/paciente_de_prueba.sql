-- Paciente de prueba para probar TODO lo agregado desde el refactor:
-- TX-01/TX-02 (recomendación), TX-03 (interacciones), TX-04 (decisión).
--
-- Ajustado contra tu esquema REAL de historia_clinica_mock (el que
-- compartiste): pacientes exige fecha_nacimiento, sexo, identificacion
-- (única) -- no existían en mi versión anterior. consulta_id se deja en
-- NULL (es nullable) para no tener que crear una fila en `consultas`
-- solo para esta prueba.
--
-- Usa nombres de VARIABLE reales de esmo_nsclc_metastatic_non_oncogene
-- (tu variables_por_guideline.md), pero los VALORES elegidos para que
-- el paciente califique son mi mejor estimación -- no tengo tus
-- rules/eligibility.yaml ni rules/first_line.yaml reales para confirmar
-- 100%. Si al probarlo sale requiere_mas_datos=true, esa es justo la
-- Fase 1 que arreglamos funcionando en vivo: te va a decir EXACTAMENTE
-- qué le falta (variables_faltantes_por_modulo) -- agrégalo y reintenta.
--
-- Ajusta el id (6) y la identificacion si ya existen en tu base.

INSERT INTO pacientes (id, nombre, fecha_nacimiento, sexo, identificacion, diagnostico_principal, estadio)
VALUES (6, 'Diana (prueba)', '1968-04-12', 'femenino', 'TEST-000006', 'NSCLC metastasico no oncogenico', 'IV');

INSERT INTO datos_clinicos_estructurados (paciente_id, consulta_id, fecha, variable, valor) VALUES
    (6, NULL, '2026-09-13', 'cancer_type', 'NSCLC'),
    (6, NULL, '2026-09-13', 'histology', 'non_squamous'),
    (6, NULL, '2026-09-13', 'disease_setting', 'metastatic'),
    (6, NULL, '2026-09-13', 'molecular_pathway_status', 'non_oncogene_addicted'),
    (6, NULL, '2026-09-13', 'pdl1_tps', '75'),
    (6, NULL, '2026-09-13', 'ecog_ps', '1'),
    (6, NULL, '2026-09-13', 'smoking_status', 'former_smoker'),
    (6, NULL, '2026-09-13', 'treatment_line', '1'),
    (6, NULL, '2026-09-13', 'treatment_phase', 'induction'),
    (6, NULL, '2026-09-13', 'immunotherapy_contraindication', 'no'),
    (6, NULL, '2026-09-13', 'major_comorbidity_precluding_ici', 'no');

-- Opcional: sin ninguna fila en comorbilidades, el paciente califica
-- limpio (sin advertencia). Si quieres probar el caso de la advertencia
-- de comorbilidad (candidato degradado, no descartado), descomenta esto:
-- INSERT INTO comorbilidades (paciente_id, consulta_id, fecha_registro, condicion, severidad, tipo_contraindicacion_ici)
-- VALUES (6, NULL, '2026-09-13', 'neumonitis previa por ICI', 'moderada', 'absolute');

-- Medicación concomitante (pacientes_clinica_extension, tabla propia
-- nuestra, no de historia_clinica_mock) -- rifampicina dispara la
-- interacción mayor de nsclc_metastatic_non_oncogene.yaml
-- (carboplatin+CYP3A4 inducer); amiodarona dispara la menor
-- (pembrolizumab+QT).
INSERT INTO medicacion_actual
    (paciente_id, medicamento, registrado_por, fecha_registro)
VALUES
    (6, 'rifampicina', 9, '2026-09-13'),
    (6, 'amiodarona', 9, '2026-09-13');

-- Conciliación YA hecha -- si la omites, chequear_interacciones_tratamiento
-- va a decir correctamente "no se ha revisado" en vez de detectar la
-- interacción (es la Capa 0, funcionando como se diseñó). Si quieres
-- probar ese caso primero, comenta este INSERT.
INSERT INTO conciliacion_medicamentos (paciente_id, estado, fecha, registrado_por)
VALUES (6, 'con_medicacion_registrada', '2026-09-13', 9);
