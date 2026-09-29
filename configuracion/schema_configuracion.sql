-- CFG-01 — Configuración de guías clínicas institucionales.
--
-- Cada cambio es una versión nueva (solo inserción, garantizado por
-- triggers): el backlog señala como riesgo que "cambios de configuración
-- no versionados dificultan la trazabilidad", y una guía mal configurada
-- afecta a todos los pacientes de la institución. Con el historial
-- completo se puede reconstruir qué guías estaban vigentes en cualquier
-- fecha y quién las cambió y por qué.

CREATE TABLE IF NOT EXISTS configuracion_guias_institucionales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version INTEGER NOT NULL UNIQUE,
    -- Lista ordenada por prioridad, p. ej. ["ESMO", "NCCN"].
    organizaciones_json TEXT NOT NULL,
    protocolo_interno_nombre TEXT,
    protocolo_interno_referencia TEXT,
    motivo TEXT NOT NULL,
    configurado_por INTEGER NOT NULL,
    fecha TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS configuracion_guias_no_update
BEFORE UPDATE ON configuracion_guias_institucionales
BEGIN SELECT RAISE(ABORT, 'configuracion_guias_institucionales es append-only'); END;

CREATE TRIGGER IF NOT EXISTS configuracion_guias_no_delete
BEFORE DELETE ON configuracion_guias_institucionales
BEGIN SELECT RAISE(ABORT, 'configuracion_guias_institucionales es append-only'); END;
