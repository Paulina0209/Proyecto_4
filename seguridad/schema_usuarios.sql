CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_usuario TEXT NOT NULL UNIQUE,
    rol TEXT NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1,
    hash_contrasena TEXT NOT NULL,
    sal TEXT NOT NULL,
    intentos_fallidos INTEGER NOT NULL DEFAULT 0,
    bloqueado_hasta TEXT
);
