-- NFR-06 — Cumplimiento de datos personales y gestión de derechos.
--
-- Las cuatro tablas son de solo-inserción, igual que el resto de
-- registros de evidencia del proyecto (eventos_acceso, decisiones_tratamiento,
-- juicios_clinicos_dx): un cambio de política es una versión nueva, una
-- revocación es una autorización nueva con estado "revocada" y el avance
-- de una solicitud es un evento nuevo. Así la evidencia de lo que estaba
-- vigente en cada momento nunca se pierde. Los triggers lo garantizan a
-- nivel de base de datos, no solo por convención.

CREATE TABLE IF NOT EXISTS politicas_tratamiento (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL,
    version INTEGER NOT NULL,
    jurisdiccion TEXT NOT NULL,
    nombre TEXT NOT NULL,
    -- Referencia libre a la norma que la institución aplica (dato, no código).
    marco_normativo TEXT,
    finalidades_json TEXT NOT NULL,
    bases_legales_json TEXT NOT NULL,
    derechos_json TEXT NOT NULL,
    plazo_respuesta_dias INTEGER NOT NULL,
    requiere_evidencia_autorizacion INTEGER NOT NULL,
    configurado_por INTEGER NOT NULL,
    fecha TEXT NOT NULL,
    UNIQUE (codigo, version)
);

CREATE TABLE IF NOT EXISTS autorizaciones_tratamiento (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL,
    -- Versión exacta de la política bajo la que se registró.
    politica_id INTEGER NOT NULL REFERENCES politicas_tratamiento(id),
    finalidad TEXT NOT NULL,
    base_legal TEXT NOT NULL,
    estado TEXT NOT NULL,           -- otorgada | revocada | denegada
    medio TEXT,                     -- escrito | digital | verbal_registrado ...
    evidencia_ref TEXT,             -- id de documento, hash, ruta del soporte
    registrado_por INTEGER NOT NULL,
    fecha TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_autorizaciones_paciente
    ON autorizaciones_tratamiento (paciente_id, finalidad, id DESC);

CREATE TABLE IF NOT EXISTS solicitudes_derechos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL,
    politica_id INTEGER NOT NULL REFERENCES politicas_tratamiento(id),
    tipo_derecho TEXT NOT NULL,
    descripcion TEXT NOT NULL,
    solicitante TEXT NOT NULL,
    fecha_recepcion TEXT NOT NULL,
    fecha_limite TEXT NOT NULL,
    registrado_por INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS eventos_solicitud_derechos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    solicitud_id INTEGER NOT NULL REFERENCES solicitudes_derechos(id),
    estado TEXT NOT NULL,           -- recibida | en_tramite | atendida | rechazada
    detalle TEXT,
    usuario_id INTEGER NOT NULL,
    fecha TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS politicas_tratamiento_no_update
BEFORE UPDATE ON politicas_tratamiento
BEGIN SELECT RAISE(ABORT, 'politicas_tratamiento es append-only'); END;
CREATE TRIGGER IF NOT EXISTS politicas_tratamiento_no_delete
BEFORE DELETE ON politicas_tratamiento
BEGIN SELECT RAISE(ABORT, 'politicas_tratamiento es append-only'); END;

CREATE TRIGGER IF NOT EXISTS autorizaciones_tratamiento_no_update
BEFORE UPDATE ON autorizaciones_tratamiento
BEGIN SELECT RAISE(ABORT, 'autorizaciones_tratamiento es append-only'); END;
CREATE TRIGGER IF NOT EXISTS autorizaciones_tratamiento_no_delete
BEFORE DELETE ON autorizaciones_tratamiento
BEGIN SELECT RAISE(ABORT, 'autorizaciones_tratamiento es append-only'); END;

CREATE TRIGGER IF NOT EXISTS solicitudes_derechos_no_update
BEFORE UPDATE ON solicitudes_derechos
BEGIN SELECT RAISE(ABORT, 'solicitudes_derechos es append-only'); END;
CREATE TRIGGER IF NOT EXISTS solicitudes_derechos_no_delete
BEFORE DELETE ON solicitudes_derechos
BEGIN SELECT RAISE(ABORT, 'solicitudes_derechos es append-only'); END;

CREATE TRIGGER IF NOT EXISTS eventos_solicitud_derechos_no_update
BEFORE UPDATE ON eventos_solicitud_derechos
BEGIN SELECT RAISE(ABORT, 'eventos_solicitud_derechos es append-only'); END;
CREATE TRIGGER IF NOT EXISTS eventos_solicitud_derechos_no_delete
BEFORE DELETE ON eventos_solicitud_derechos
BEGIN SELECT RAISE(ABORT, 'eventos_solicitud_derechos es append-only'); END;
