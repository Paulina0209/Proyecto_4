-- Esquema de la base de datos mock de historia clínica oncológica.
--
-- Cada tabla clínica (laboratorios, imagenologia, biomarcadores) tiene una
-- columna `consulta_id` que puede ser NULL. Cuando no es NULL, indica que
-- ese resultado fue *registrado o revisado durante esa consulta puntual*,
-- que es justo el recorte de información que necesita IA-02 ("información
-- disponible de la consulta"), a diferencia de todo el historial del
-- paciente a lo largo del tiempo.

CREATE TABLE IF NOT EXISTS pacientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    fecha_nacimiento TEXT NOT NULL,
    sexo TEXT NOT NULL,
    identificacion TEXT NOT NULL UNIQUE,
    diagnostico_principal TEXT,
    estadio TEXT
);

CREATE TABLE IF NOT EXISTS consultas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL REFERENCES pacientes(id),
    fecha TEXT NOT NULL,
    motivo TEXT NOT NULL,
    notas_libres TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS laboratorios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL REFERENCES pacientes(id),
    consulta_id INTEGER REFERENCES consultas(id),
    fecha TEXT NOT NULL,
    prueba TEXT NOT NULL,
    valor TEXT NOT NULL,
    unidad TEXT,
    rango_referencia TEXT,
    alterado INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS imagenologia (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL REFERENCES pacientes(id),
    consulta_id INTEGER REFERENCES consultas(id),
    fecha TEXT NOT NULL,
    modalidad TEXT NOT NULL,
    region TEXT NOT NULL,
    hallazgos TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS biomarcadores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL REFERENCES pacientes(id),
    consulta_id INTEGER REFERENCES consultas(id),
    fecha TEXT NOT NULL,
    biomarcador TEXT NOT NULL,
    resultado TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS datos_clinicos_estructurados (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL REFERENCES pacientes(id),
    consulta_id INTEGER REFERENCES consultas(id),
    fecha TEXT NOT NULL,
    variable TEXT NOT NULL,
    valor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS comorbilidades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL REFERENCES pacientes(id),
    consulta_id INTEGER REFERENCES consultas(id),
    fecha_registro TEXT NOT NULL,
    condicion TEXT NOT NULL,
    severidad TEXT,
    tipo_contraindicacion_ici TEXT
);