-- Extensión aditiva para HC-01: modelo de identidad de paciente.
-- No modifica ninguna tabla existente de historia_clinica_mock.
--
-- NOTA para integrar con el `pacientes` real: si esa tabla ya cubre
-- parte de estos campos, hay que reconciliar (fusionar columnas o
-- migrar datos) antes de usar esto en producción. Se define aquí como
-- tabla nueva para no arriesgar romper nada de HC-01/TX-01 mientras
-- se revisa esa reconciliación.
CREATE TABLE IF NOT EXISTS pacientes_identidad (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_completo TEXT NOT NULL,
    fecha_nacimiento TEXT,
    sexo TEXT NOT NULL,
    tipo_identificacion TEXT NOT NULL,
    numero_identificacion TEXT NOT NULL,
    telefono TEXT,
    email TEXT,
    direccion TEXT,
    antecedentes_personales TEXT,
    antecedentes_familiares TEXT,
    motivo_consulta_inicial TEXT,
    oncologo_id INTEGER NOT NULL,
    registro_completo INTEGER NOT NULL DEFAULT 0,
    fecha_registro TEXT NOT NULL,
    -- Regla de negocio: la identificación debe ser única por institución.
    -- No se aplica UNIQUE a 'temporal' vía este constraint porque cada
    -- identificador temporal ya se genera único (ver generar_identificador_temporal).
    UNIQUE(tipo_identificacion, numero_identificacion)
);

CREATE INDEX IF NOT EXISTS idx_pacientes_identidad_oncologo
    ON pacientes_identidad(oncologo_id);
