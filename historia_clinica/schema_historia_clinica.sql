-- Esquema de HC-01 (integración de historia clínica externa).
--
-- Vive en la MISMA base de datos que `expediente/schema.sql`
-- (se aplica encima de ella): todo lo que se integra aquí termina en las
-- tablas clínicas que ya leen DX, EST, TX e IA (laboratorios,
-- imagenologia, biomarcadores, datos_clinicos_estructurados). Estas
-- tablas solo agregan lo que esas no tienen: la trazabilidad de la
-- integración y los antecedentes que no tienen tabla propia.

-- HC-01: una fila por intento de sincronización, exitoso o no. Un fallo
-- queda registrado aquí (AC3) en vez de propagarse como excepción.
CREATE TABLE IF NOT EXISTS sincronizaciones_externas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL REFERENCES pacientes(id),
    fuente TEXT NOT NULL,
    formato TEXT NOT NULL,          -- fhir | hl7v2 | pdf
    estado TEXT NOT NULL,           -- exitosa | fallida | documento_no_estructurado
    registros_importados INTEGER NOT NULL DEFAULT 0,
    registros_omitidos INTEGER NOT NULL DEFAULT 0,
    mensaje TEXT,
    fecha TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sincronizaciones_paciente
    ON sincronizaciones_externas (paciente_id, id DESC);

-- HC-01: qué fila local salió de qué recurso externo. La restricción
-- UNIQUE hace que re-sincronizar al mismo paciente no duplique datos.
CREATE TABLE IF NOT EXISTS registros_importados (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sincronizacion_id INTEGER NOT NULL REFERENCES sincronizaciones_externas(id),
    fuente TEXT NOT NULL,
    identificador_externo TEXT NOT NULL,
    tabla_destino TEXT NOT NULL,
    fila_id INTEGER NOT NULL,
    UNIQUE (fuente, identificador_externo)
);

-- HC-01: antecedentes (condiciones, procedimientos, medicación) traídos de
-- un sistema externo que no tienen tabla clínica propia en el mock.
CREATE TABLE IF NOT EXISTS antecedentes_externos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL REFERENCES pacientes(id),
    tipo TEXT NOT NULL,             -- condicion | procedimiento | medicacion
    descripcion TEXT NOT NULL,
    fecha TEXT,
    fuente TEXT NOT NULL
);

-- HC-02: momento exacto de la toma y vía por la que llegó cada resultado.
-- `laboratorios.fecha` solo guarda el día (es lo que leen DX, EST e IA);
-- la hora vive aquí para detectar conflictos de "mismo marcador, mismo
-- momento" (AC3) sin cambiar la tabla que ya leen los demás módulos.
CREATE TABLE IF NOT EXISTS recepcion_laboratorio (
    laboratorio_id INTEGER PRIMARY KEY REFERENCES laboratorios(id),
    paciente_id INTEGER NOT NULL REFERENCES pacientes(id),
    fecha_hora TEXT,                -- ISO 8601 con hora, si la fuente la trae
    origen TEXT NOT NULL,           -- manual | hl7v2 | fhir | cbioportal ...
    recibido_en TEXT NOT NULL
);

-- HC-02 AC2: un valor fuera del rango crítico genera una alerta visible en
-- el dashboard 360 hasta que el oncólogo la marca como revisada.
CREATE TABLE IF NOT EXISTS alertas_laboratorio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL REFERENCES pacientes(id),
    laboratorio_id INTEGER NOT NULL UNIQUE REFERENCES laboratorios(id),
    prueba TEXT NOT NULL,
    valor TEXT NOT NULL,
    unidad TEXT,
    limite_superado TEXT NOT NULL,  -- p. ej. "< 2.5 mmol/L (crítico bajo)"
    severidad TEXT NOT NULL DEFAULT 'critica',
    estado TEXT NOT NULL DEFAULT 'activa',  -- activa | revisada
    fecha TEXT NOT NULL,
    revisada_por TEXT,
    fecha_revision TEXT
);
CREATE INDEX IF NOT EXISTS idx_alertas_laboratorio_paciente ON alertas_laboratorio (paciente_id, estado);

-- HC-02 AC3: dos resultados del mismo marcador en el mismo momento con
-- valores distintos. Ninguno se sobrescribe ni se borra: ambos siguen en
-- `laboratorios` y el conflicto queda pendiente de revisión.
CREATE TABLE IF NOT EXISTS conflictos_laboratorio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL REFERENCES pacientes(id),
    prueba_normalizada TEXT NOT NULL,
    momento TEXT NOT NULL,
    laboratorio_a_id INTEGER NOT NULL REFERENCES laboratorios(id),
    laboratorio_b_id INTEGER NOT NULL REFERENCES laboratorios(id),
    estado TEXT NOT NULL DEFAULT 'pendiente',  -- pendiente | resuelto
    resolucion TEXT,                -- valido_a | valido_b | ambos_validos | ninguno_valido
    resuelto_por TEXT,
    fecha_resolucion TEXT,
    nota TEXT,
    fecha_deteccion TEXT NOT NULL,
    UNIQUE (laboratorio_a_id, laboratorio_b_id)
);
CREATE INDEX IF NOT EXISTS idx_conflictos_laboratorio_paciente ON conflictos_laboratorio (paciente_id, estado);

-- HC-04: episodio diagnóstico al que se vinculan las biopsias (AC1).
CREATE TABLE IF NOT EXISTS episodios_diagnosticos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL REFERENCES pacientes(id),
    descripcion TEXT NOT NULL,
    tipo_cancer TEXT,
    fecha_diagnostico TEXT,
    origen TEXT NOT NULL,           -- manual | cbioportal ...
    identificador_externo TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_episodios_paciente ON episodios_diagnosticos (paciente_id);

-- HC-04: resultado de una biopsia (anatomía patológica), siempre dentro de
-- un episodio diagnóstico.
CREATE TABLE IF NOT EXISTS biopsias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL REFERENCES pacientes(id),
    episodio_id INTEGER NOT NULL REFERENCES episodios_diagnosticos(id),
    fecha TEXT NOT NULL,
    sitio TEXT NOT NULL,
    procedimiento TEXT NOT NULL,
    diagnostico_histologico TEXT,
    muestra_externa TEXT,
    origen TEXT NOT NULL,
    registrado_por TEXT,
    identificador_externo TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_biopsias_paciente ON biopsias (paciente_id);

-- HC-04: estructura de un biomarcador. La fila de `biomarcadores` conserva
-- un texto legible (lo que leen HC-05, DX e IA); aquí va el dato validado
-- y si es información clave para el tratamiento (AC2, insumo de TX-01).
CREATE TABLE IF NOT EXISTS detalle_biomarcador (
    biomarcador_id INTEGER PRIMARY KEY REFERENCES biomarcadores(id),
    paciente_id INTEGER NOT NULL REFERENCES pacientes(id),
    biopsia_id INTEGER REFERENCES biopsias(id),
    codigo TEXT NOT NULL,           -- código del catálogo (EGFR, HER2, PDL1_TPS...)
    estado TEXT NOT NULL,
    valor_numerico REAL,
    unidad TEXT,
    metodo TEXT,
    variante TEXT,
    -- accionable_confirmado | pendiente_confirmacion | informativo
    relevancia TEXT NOT NULL,
    terapia_asociada TEXT,
    variable_tx TEXT,
    valor_tx TEXT,
    confirmado_por TEXT,
    fecha_confirmacion TEXT,
    origen TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_detalle_biomarcador_paciente ON detalle_biomarcador (paciente_id, relevancia);
