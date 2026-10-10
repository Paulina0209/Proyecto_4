-- ADM-01: datos de gestión de cada usuario institucional. Tabla lateral de
-- `usuarios` (SEC-01): no cambia el esquema de login, y los usuarios dados
-- de alta solo con `registrar_usuario` siguen existiendo sin perfil.
CREATE TABLE IF NOT EXISTS perfiles_usuario (
    usuario_id INTEGER PRIMARY KEY REFERENCES usuarios(id),
    nombre_completo TEXT,
    correo TEXT,
    creado_en TEXT NOT NULL,
    creado_por INTEGER,
    actualizado_en TEXT,
    desactivado_en TEXT,
    motivo_desactivacion TEXT
);
-- Un correo identifica a una sola persona (sin distinguir mayúsculas).
CREATE UNIQUE INDEX IF NOT EXISTS idx_perfiles_usuario_correo
    ON perfiles_usuario (lower(correo)) WHERE correo IS NOT NULL;
