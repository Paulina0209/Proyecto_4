CREATE TABLE IF NOT EXISTS eventos_acceso (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL,
    paciente_id INTEGER,
    accion TEXT NOT NULL,
    fecha TEXT NOT NULL,
    detalle TEXT
);

-- NFR-04 (AC4): la traza es de solo inserción también a nivel de base de
-- datos, no solo porque el módulo no exponga funciones para cambiarla.
CREATE TRIGGER IF NOT EXISTS eventos_acceso_no_update
BEFORE UPDATE ON eventos_acceso
BEGIN SELECT RAISE(ABORT, 'eventos_acceso es append-only'); END;
CREATE TRIGGER IF NOT EXISTS eventos_acceso_no_delete
BEFORE DELETE ON eventos_acceso
BEGIN SELECT RAISE(ABORT, 'eventos_acceso es append-only'); END;
