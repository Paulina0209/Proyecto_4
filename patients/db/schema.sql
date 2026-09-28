-- Única base de datos del módulo de pacientes (HC-01, PAC-02, PAC-03).
--
-- Todo cuelga de `pacientes`: la identidad del paciente se define una
-- sola vez (nota técnica de HC-01) y el resto de tablas la referencian.
-- El resumen 360 (PAC-03) no tiene tablas propias de diagnóstico o
-- tratamiento: lee las mismas que usa la búsqueda (PAC-02).

-- HC-01: identidad, datos demográficos, antecedentes y motivo de consulta.
CREATE TABLE IF NOT EXISTS pacientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_completo TEXT NOT NULL,
    fecha_nacimiento TEXT,
    sexo TEXT NOT NULL,
    tipo_identificacion TEXT NOT NULL,
    -- Documento, o identificador temporal (TEMP-...) si no tiene.
    numero_identificacion TEXT NOT NULL,
    telefono TEXT,
    email TEXT,
    direccion TEXT,
    antecedentes_personales TEXT,
    antecedentes_familiares TEXT,
    motivo_consulta_inicial TEXT,
    oncologo_id INTEGER NOT NULL,
    -- 0 mientras falten antecedentes o motivo ("completar después").
    registro_completo INTEGER NOT NULL DEFAULT 0,
    fecha_registro TEXT NOT NULL,
    -- Regla de negocio: identificación única por institución.
    UNIQUE (tipo_identificacion, numero_identificacion)
);
CREATE INDEX IF NOT EXISTS idx_pacientes_oncologo ON pacientes(oncologo_id);

-- PAC-02 filtra por diagnóstico; PAC-03 muestra el más reciente con su estadio.
CREATE TABLE IF NOT EXISTS diagnosticos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL REFERENCES pacientes(id),
    descripcion TEXT NOT NULL,
    estadio TEXT,
    fecha TEXT
);
CREATE INDEX IF NOT EXISTS idx_diagnosticos_paciente ON diagnosticos(paciente_id);

-- El tratamiento más reciente da el estado para PAC-02 y el régimen para PAC-03.
CREATE TABLE IF NOT EXISTS tratamientos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL REFERENCES pacientes(id),
    estado TEXT NOT NULL, -- en_tratamiento | en_seguimiento | suspendido | finalizado
    regimen TEXT,
    fecha_inicio TEXT
);
CREATE INDEX IF NOT EXISTS idx_tratamientos_paciente ON tratamientos(paciente_id);

-- PAC-02 filtra por la última consulta; su nota es la que PAC-03 muestra
-- en "notas recientes".
CREATE TABLE IF NOT EXISTS consultas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL REFERENCES pacientes(id),
    fecha TEXT NOT NULL,
    nota TEXT
);
CREATE INDEX IF NOT EXISTS idx_consultas_paciente ON consultas(paciente_id);

-- PAC-03: alertas activas (interacciones y estudios pendientes).
CREATE TABLE IF NOT EXISTS alertas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL REFERENCES pacientes(id),
    tipo TEXT NOT NULL,      -- interaccion | estudio_pendiente
    severidad TEXT NOT NULL, -- alta | media | baja
    descripcion TEXT NOT NULL,
    fecha TEXT NOT NULL,
    resuelta INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_alertas_paciente ON alertas(paciente_id);

-- PAC-03: acceso rápido a laboratorios e imágenes (solo lo que cabe en
-- la lista; el detalle vive en otras pantallas).
CREATE TABLE IF NOT EXISTS estudios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL REFERENCES pacientes(id),
    tipo TEXT NOT NULL,   -- laboratorio | imagen
    nombre TEXT NOT NULL, -- prueba de laboratorio o modalidad de imagen
    resumen TEXT NOT NULL,
    fecha TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_estudios_paciente ON estudios(paciente_id);
