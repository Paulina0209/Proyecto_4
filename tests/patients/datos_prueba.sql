-- Datos de prueba del módulo de pacientes. Se cargan al arrancar la API
-- SOLO si no hay ningún paciente (ver db.sembrar_datos_prueba), así que
-- nunca se mezclan con pacientes reales ni se duplican al reiniciar.
-- Para recargarlos desde cero, borra db/pacientes.db.
--
-- Casos que cubren:
--   PAC-02  9 pacientes del oncólogo 1 (más de una página de 5), los
--           cuatro estados de tratamiento, nombres con tildes.
--           Laura Jiménez (10) es del oncólogo 2: el oncólogo 1 nunca la ve.
--   PAC-03  1 María Gómez: expediente completo; tiene un tratamiento previo
--             (se muestra el más reciente) y una alerta ya resuelta (no se muestra).
--           2 Carlos Ruiz: recién remitido, sin diagnóstico, estadio ni tratamiento.
--           7 Andrés Felipe Gómez: solo le falta el estadio.
--           3 Juan Carlos Pérez: más laboratorios de los que caben en la lista.

INSERT INTO pacientes (
    id, nombre_completo, fecha_nacimiento, sexo, tipo_identificacion,
    numero_identificacion, telefono, oncologo_id, registro_completo, fecha_registro
) VALUES
    (1,  'María Gómez',           '1961-05-14', 'femenino',  'cedula', '91000001', '3001000001', 1, 0, '2026-01-10T08:00:00'),
    (2,  'Carlos Ruiz',           '1958-11-02', 'masculino', 'cedula', '91000002', '3001000002', 1, 0, '2026-09-14T08:00:00'),
    (3,  'Juan Carlos Pérez',     '1972-03-20', 'masculino', 'cedula', '91000003', '3001000003', 1, 0, '2026-03-01T08:00:00'),
    (4,  'Ana Sofía Rodríguez',   '1980-07-08', 'femenino',  'cedula', '91000004', '3001000004', 1, 0, '2026-06-25T08:00:00'),
    (5,  'María José Herrera',    '1966-01-30', 'femenino',  'cedula', '91000005', '3001000005', 1, 0, '2025-09-20T08:00:00'),
    (6,  'José Luis Martínez',    '1955-09-12', 'masculino', 'cedula', '91000006', '3001000006', 1, 0, '2026-02-10T08:00:00'),
    (7,  'Andrés Felipe Gómez',   '1950-12-01', 'masculino', 'cedula', '91000007', '3001000007', 1, 0, '2025-04-15T08:00:00'),
    (8,  'Lucía Fernández',       '1985-04-22', 'femenino',  'cedula', '91000008', '3001000008', 1, 0, '2026-07-05T08:00:00'),
    (9,  'Pedro Antonio Castaño', '1969-08-17', 'masculino', 'cedula', '91000009', '3001000009', 1, 0, '2025-07-28T08:00:00'),
    (10, 'Laura Jiménez',         '1963-02-11', 'femenino',  'cedula', '91000010', '3001000010', 2, 0, '2026-06-15T08:00:00');

INSERT INTO diagnosticos (paciente_id, descripcion, estadio, fecha) VALUES
    (1,  'NSCLC metastásico no oncogénico',                  'IV',   '2026-01-15'),
    (3,  'Adenocarcinoma de pulmón EGFR mutado',             'IV',   '2026-03-02'),
    (4,  'Cáncer de mama HER2 positivo',                     'IIIA', '2026-07-01'),
    (5,  'Carcinoma ductal infiltrante de mama RH positivo', 'IIA',  '2025-10-01'),
    (6,  'Adenocarcinoma de colon',                          'IIIB', '2026-02-15'),
    (7,  'Adenocarcinoma de próstata',                       NULL,   '2025-04-20'),
    (8,  'Melanoma cutáneo',                                 'IIIC', '2026-07-10'),
    (9,  'Linfoma no Hodgkin difuso de células B grandes',   'II',   '2025-08-01'),
    (10, 'Adenocarcinoma de pulmón',                         'IV',   '2026-06-20');

INSERT INTO tratamientos (paciente_id, estado, regimen, fecha_inicio) VALUES
    (1,  'finalizado',     'carboplatino + paclitaxel',            '2026-02-10'),
    (1,  'en_tratamiento', 'pembrolizumab + pemetrexed',           '2026-06-01'),
    (3,  'en_tratamiento', 'osimertinib',                          '2026-03-20'),
    (4,  'en_tratamiento', 'trastuzumab + pertuzumab + docetaxel', '2026-07-20'),
    (5,  'en_seguimiento', 'letrozol',                             '2025-11-10'),
    (6,  'suspendido',     'FOLFOX',                               '2026-04-03'),
    (7,  'en_seguimiento', 'enzalutamida',                         '2025-05-12'),
    (8,  'en_tratamiento', 'nivolumab',                            '2026-08-01'),
    (9,  'finalizado',     'R-CHOP',                               '2025-09-01'),
    (10, 'en_tratamiento', 'pembrolizumab',                        '2026-07-01');

INSERT INTO consultas (paciente_id, fecha, nota) VALUES
    (1,  '2026-06-01', 'Consulta de inicio de tratamiento de primera línea.'),
    (1,  '2026-09-13', 'Consulta de seguimiento: buena tolerancia al tratamiento actual.'),
    (2,  '2026-09-14', NULL),
    (3,  '2026-08-30', NULL),
    (3,  '2026-09-20', 'Buena tolerancia a osimertinib; rash grado 1.'),
    (4,  '2026-09-25', 'Ciclo 4 aplazado una semana por neutropenia.'),
    (5,  '2026-08-15', 'Seguimiento anual sin hallazgos.'),
    (6,  '2026-07-02', 'Tratamiento suspendido por neuropatía grado 3.'),
    (7,  '2026-05-05', 'Control semestral; falta documentar estadificación inicial.'),
    (8,  '2026-09-18', 'Ciclo 3 de nivolumab sin eventos adversos.'),
    (9,  '2026-03-10', 'Fin de tratamiento; pasa a vigilancia.'),
    (10, '2026-09-22', 'Consulta de seguimiento.');

INSERT INTO alertas (paciente_id, tipo, severidad, descripcion, fecha, resuelta) VALUES
    (1, 'interaccion',       'alta',  'Interacción mayor: régimen actual + inductor fuerte de CYP3A4 concomitante.', '2026-09-10', 0),
    (1, 'estudio_pendiente', 'media', 'TAC de tórax de control pendiente de agendar.',                               '2026-09-05', 0),
    (1, 'estudio_pendiente', 'baja',  'Laboratorio de control ya revisado.',                                         '2026-08-01', 1),
    (3, 'estudio_pendiente', 'media', 'Resonancia cerebral de control pendiente.',                                   '2026-09-20', 0),
    (4, 'estudio_pendiente', 'alta',  'Ecocardiograma (FEVI) de control vencido antes del próximo ciclo.',           '2026-09-25', 0),
    (4, 'interaccion',       'baja',  'Omeprazol concomitante: vigilar tolerancia gastrointestinal.',                '2026-09-10', 0),
    (6, 'interaccion',       'media', 'Warfarina concomitante con fluoropirimidina: vigilar INR.',                   '2026-06-30', 0),
    (8, 'estudio_pendiente', 'baja',  'TSH de control pendiente (inmunoterapia).',                                   '2026-09-18', 0);

INSERT INTO estudios (paciente_id, tipo, nombre, resumen, fecha) VALUES
    (1, 'laboratorio', 'Hemograma',         'Sin alteraciones significativas.',               '2026-09-12'),
    (1, 'laboratorio', 'Función hepática',  'Transaminasas levemente elevadas.',              '2026-08-20'),
    (1, 'imagen',      'TAC tórax',         'Enfermedad estable respecto al estudio previo.', '2026-09-01'),
    (2, 'laboratorio', 'Hemograma inicial', 'Pendiente de interpretación por oncología.',     '2026-09-14'),
    (3, 'laboratorio', 'Función renal',     'Creatinina normal.',                             '2026-09-19'),
    (3, 'laboratorio', 'Hemograma',         'Sin alteraciones significativas.',               '2026-09-19'),
    (3, 'laboratorio', 'Función hepática',  'Dentro de rangos normales.',                     '2026-08-29'),
    (3, 'laboratorio', 'Electrolitos',      'Magnesio levemente bajo, suplementado.',         '2026-07-15'),
    (3, 'laboratorio', 'Hemograma',         'Sin alteraciones significativas.',               '2026-06-10'),
    (3, 'imagen',      'TAC tórax-abdomen', 'Respuesta parcial.',                             '2026-09-01'),
    (4, 'laboratorio', 'Hemograma',         'Neutropenia grado 2.',                           '2026-09-24'),
    (4, 'imagen',      'Mamografía',        'Lesión de 3,2 cm en mama derecha.',              '2026-06-28'),
    (5, 'laboratorio', 'Perfil lipídico',   'Colesterol LDL levemente elevado.',              '2026-08-14'),
    (5, 'imagen',      'Mamografía',        'Sin evidencia de recurrencia.',                  '2026-08-10'),
    (6, 'laboratorio', 'CEA',               'Descenso respecto al valor basal.',              '2026-07-01'),
    (6, 'imagen',      'TAC abdomen',       'Enfermedad estable.',                            '2026-06-20'),
    (7, 'laboratorio', 'PSA',               'PSA indetectable.',                              '2026-05-04'),
    (8, 'laboratorio', 'Función tiroidea',  'TSH en límite superior normal.',                 '2026-09-17'),
    (9, 'laboratorio', 'LDH',               'Dentro de rangos normales.',                     '2026-03-09'),
    (9, 'imagen',      'PET-CT',            'Remisión metabólica completa.',                  '2026-02-20');
