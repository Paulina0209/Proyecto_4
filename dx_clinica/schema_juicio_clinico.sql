-- Esquema de persistencia para DX-03 — juicio clínico del médico sobre el
-- diagnóstico diferencial de un paciente.
--
-- Regla de negocio: el juicio del médico nunca es bloqueado ni
-- sobreescrito por el sistema. Por eso esta tabla es de solo-inserción
-- (append-only) desde el punto de vista de la aplicación: no hay ningún
-- UPDATE que modifique un juicio ya registrado, solo INSERTs nuevos. El
-- "juicio vigente" de un paciente es siempre el más reciente (mayor id),
-- lo que le permite al médico registrar un juicio nuevo más adelante
-- (por ejemplo, en una consulta de seguimiento) sin que eso implique que
-- el anterior fue "incorrecto" — ambos quedan en el historial.
CREATE TABLE IF NOT EXISTS juicios_clinicos_dx (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL,
    -- Texto libre: la conclusión diagnóstica del médico. Puede coincidir
    -- o no con lo que sugirió el sistema; nunca se valida ni se rechaza
    -- por "no coincidir" con la priorización del sistema.
    diagnostico_registrado TEXT NOT NULL,
    autor TEXT NOT NULL,
    registrado_en TEXT NOT NULL,
    -- Snapshot de auditoría de lo que el sistema sugería al momento de
    -- registrar el juicio (JSON: lista de perfil_id). Es solo contexto
    -- histórico -- nunca se usa para bloquear ni validar el juicio.
    perfiles_sugeridos_por_sistema TEXT NOT NULL DEFAULT '[]',
    advertencia_sistema TEXT
);

CREATE INDEX IF NOT EXISTS idx_juicios_clinicos_dx_paciente
    ON juicios_clinicos_dx (paciente_id, id DESC);
