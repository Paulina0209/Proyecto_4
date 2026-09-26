-- Esquema de persistencia para DOC-01 — carga de documentos clínicos
-- (PDF, imágenes, DICOM) al expediente de un paciente.
--
-- Es una tabla de solo-inserción (append-only), en el mismo espíritu que
-- `dx_clinica/schema_juicio_clinico.sql`: un documento cargado nunca se
-- sobreescribe ni se reemplaza en su lugar -- si el médico necesita
-- corregir algo, carga un documento nuevo. Esto es lo que permite que
-- "historial de documentos" (AC1: "visible en su historial de
-- documentos") sea, simplemente, listar todas las filas de un paciente
-- en el orden en que se cargaron -- nunca hay una versión "actual" que
-- oculte una anterior.
CREATE TABLE IF NOT EXISTS documentos_clinicos_cargados (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL,
    -- Nombre tal como lo entregó quien lo cargó (para mostrarlo en el
    -- historial); nunca se usa como ruta real en disco -- ver
    -- `ruta_almacenamiento`.
    nombre_archivo_original TEXT NOT NULL,
    -- "PDF" | "Imagen" | "DICOM" -- ver carga_documentos.FORMATOS_SOPORTADOS.
    tipo_documento TEXT NOT NULL,
    extension TEXT NOT NULL,
    tamano_bytes INTEGER NOT NULL,
    -- Ruta real en disco donde se guardó el contenido binario (con un
    -- nombre de archivo generado, nunca el nombre original -- evita
    -- colisiones y cualquier problema de path traversal con el nombre
    -- que entregó quien cargó el documento).
    ruta_almacenamiento TEXT NOT NULL,
    cargado_por TEXT NOT NULL,
    cargado_en TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_documentos_clinicos_cargados_paciente
    ON documentos_clinicos_cargados (paciente_id, id DESC);
