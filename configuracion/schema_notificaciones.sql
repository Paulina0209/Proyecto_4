-- CFG-02: qué eventos avisan a cada oncólogo y por qué canal. Una fila por
-- usuario y evento; sin fila se usa el valor por defecto (activo, en la aplicación).
CREATE TABLE IF NOT EXISTS preferencias_notificacion (
    usuario_id INTEGER NOT NULL,
    evento TEXT NOT NULL,            -- resultado_critico | estudio_pendiente | interaccion_detectada
    activo INTEGER NOT NULL,
    canales TEXT NOT NULL,           -- separados por coma: en_aplicacion,correo
    actualizado_en TEXT NOT NULL,
    PRIMARY KEY (usuario_id, evento)
);

-- CFG-02: notificaciones que cada usuario ya leyó. Leer no resuelve la alerta de origen.
CREATE TABLE IF NOT EXISTS notificaciones_leidas (
    usuario_id INTEGER NOT NULL,
    notificacion_id TEXT NOT NULL,   -- lab-<id> | alerta-<id>
    leida_en TEXT NOT NULL,
    PRIMARY KEY (usuario_id, notificacion_id)
);
