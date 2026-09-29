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
