-- Esquema de persistencia para EST-02 — ajuste manual de estadificación.
--
-- Regla de negocio: la confirmación del médico nunca es bloqueada ni
-- sobreescrita por el sistema. Por eso esta tabla es de solo-inserción
-- (append-only) desde el punto de vista de la aplicación: no hay ningún
-- UPDATE que modifique una confirmación ya registrada, solo INSERTs
-- nuevos. La "confirmación vigente" de un paciente es siempre la más
-- reciente (mayor id) -- mismo diseño que juicios_clinicos_dx (DX-03).
CREATE TABLE IF NOT EXISTS confirmaciones_estadificacion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL,
    -- Texto libre: el estadio final que registra el médico. Puede
    -- coincidir o no con lo que sugirió el sistema; nunca se valida ni
    -- se rechaza por "no coincidir" con la propuesta de EST-01.
    estadio_confirmado TEXT NOT NULL,
    -- Snapshot opcional (JSON: {"T": "...", "N": "...", "M": "..."}) de
    -- los componentes que el médico confirma o ajusta explícitamente.
    componentes_confirmados TEXT,
    autor TEXT NOT NULL,
    registrado_en TEXT NOT NULL,
    justificacion TEXT,
    -- Snapshot de auditoría de la propuesta de EST-01 al momento de
    -- confirmar (contexto histórico, nunca usado para bloquear ni
    -- validar la confirmación). NULL si no había ninguna propuesta.
    estadio_sugerido_por_sistema TEXT,
    sistema_id TEXT,
    sistema_version TEXT,
    -- 1 si había una sugerencia del sistema y el estadio confirmado es
    -- distinto (normalizado); 0 en cualquier otro caso. Insumo directo
    -- para AUD-02 (trazabilidad de recomendaciones de IA).
    difiere_de_sugerencia INTEGER NOT NULL DEFAULT 0,
    -- 1 si el sistema tenía una sugerencia disponible al momento de
    -- confirmar; distingue "confirmó igual a la sugerencia" de "no había
    -- ninguna sugerencia con la que comparar".
    sugerencia_disponible INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_confirmaciones_estadificacion_paciente
    ON confirmaciones_estadificacion (paciente_id, id DESC);
