-- Esquema de persistencia para IA-03 (revisión y aprobación de notas
-- clínicas generadas por IA).
--
-- Es una tabla independiente de historia_clinica_mock: una nota en
-- revisión no es un dato clínico del expediente del paciente, sino un
-- artefacto del propio flujo de trabajo del copiloto de IA (borrador ->
-- edición -> aprobación). Guardarla en su propia tabla evita mezclar dos
-- responsabilidades distintas en el mismo esquema.
--
-- Se persiste en SQLite (no solo en memoria de un objeto Python) a
-- propósito: es justamente lo que permite sostener el criterio de
-- aceptación "si cierro sesión o abandono la edición, la nota sigue
-- identificada como borrador no confirmado" — el estado sobrevive a la
-- conexión/proceso actual, no depende de que nadie mantenga vivo un
-- objeto en memoria.
CREATE TABLE IF NOT EXISTS revision_notas (
    nota_id TEXT PRIMARY KEY,
    paciente_ref TEXT NOT NULL,
    -- Copia congelada del contenido tal como lo produjo IA-02. Nunca se
    -- sobreescribe: sirve para poder comparar en cualquier momento qué
    -- cambió el médico respecto a lo que generó la IA.
    contenido_ia_original TEXT NOT NULL,
    -- Contenido vigente de la nota (JSON: clave de sección -> texto).
    -- Empieza igual a contenido_ia_original y se actualiza con cada
    -- edición guardada.
    contenido_actual TEXT NOT NULL,
    -- 'DRAFT' o 'APPROVED' (ver ia_clinica.review.models.EstadoNota).
    estado TEXT NOT NULL DEFAULT 'DRAFT',
    creado_en TEXT NOT NULL,
    -- Historial completo de ediciones guardadas (JSON: lista de objetos
    -- autor/seccion_key/contenido_anterior/contenido_nuevo/editado_en).
    historial_ediciones TEXT NOT NULL DEFAULT '[]',
    -- NULL mientras la nota siga en borrador. Solo se llenan los dos
    -- juntos, y solo dentro de aprobar_nota().
    aprobado_por TEXT,
    aprobado_en TEXT
);
