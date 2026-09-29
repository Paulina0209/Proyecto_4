CREATE TABLE IF NOT EXISTS eventos_acceso (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL,
    paciente_id INTEGER,
    accion TEXT NOT NULL,
    fecha TEXT NOT NULL,
    detalle TEXT
);
