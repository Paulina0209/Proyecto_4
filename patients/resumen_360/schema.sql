-- Base de datos MOCK para el dashboard 360 del paciente (PAC-03).
--
-- Standalone y ficticia A PROPÓSITO -- se integra con la base de datos
-- real más adelante (decisión explícita del usuario; ver R11 del plan
-- de reorganización: la unificación real de identidad de paciente se
-- resuelve con la migración a una base unificada tipo Supabase, no
-- antes). Mientras tanto, esta base tiene su PROPIA identidad de
-- paciente (pacientes_360.id), independiente de
-- patients.pacientes_identidad e historia_clinica_mock.pacientes --
-- es el mismo patrón que ya usa historia_clinica_mock/ para tx_clinica,
-- replicado aquí para el dashboard 360, no una tercera duplicación
-- nueva sin documentar (ver D1 del plan: esa duplicación ya está
-- identificada y aceptada como riesgo conocido hasta la migración).
--
-- oncologo_id se incluye desde ya (aunque todavía no hay autenticación
-- real, P7 del plan) para que el endpoint pueda aplicar el mismo
-- criterio de propiedad que ya se usa en el resto de patients/api.py
-- (ver D2/D4) -- consistencia de ahora, no una promesa de seguridad
-- real todavía.

CREATE TABLE IF NOT EXISTS pacientes_360 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    oncologo_id INTEGER NOT NULL,
    -- Nulos A PROPÓSITO: el dashboard debe mostrar un indicador de
    -- "información faltante" (AC2 de PAC-03, ligado a HC-05) cuando
    -- estos datos no están -- nunca inventarlos ni asumir un valor por
    -- defecto. Ver service.py::_CAMPOS_CLAVE_DASHBOARD.
    diagnostico_principal TEXT,
    estadio TEXT,
    fecha_diagnostico TEXT
);
CREATE INDEX IF NOT EXISTS idx_pacientes_360_oncologo ON pacientes_360(oncologo_id);

CREATE TABLE IF NOT EXISTS tratamientos_360 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL REFERENCES pacientes_360(id),
    regimen TEXT NOT NULL,
    estado TEXT NOT NULL, -- 'en_tratamiento' | 'en_seguimiento' | 'suspendido' | 'finalizado'
    fecha_inicio TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tratamientos_360_paciente ON tratamientos_360(paciente_id);

-- "Alertas activas (interacciones, estudios pendientes)" de la
-- descripción de PAC-03 -- un solo tipo de alerta, distinguido por
-- `tipo`, para no duplicar la noción de "cosa que necesita atención"
-- en dos tablas separadas.
CREATE TABLE IF NOT EXISTS alertas_360 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL REFERENCES pacientes_360(id),
    tipo TEXT NOT NULL, -- 'interaccion' | 'estudio_pendiente'
    severidad TEXT NOT NULL, -- 'alta' | 'media' | 'baja'
    descripcion TEXT NOT NULL,
    fecha TEXT NOT NULL,
    resuelta INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_alertas_360_paciente ON alertas_360(paciente_id);

-- Las tres tablas de "acceso rápido" (labs/imágenes/notas) guardan solo
-- lo mínimo para una lista de acceso rápido (fecha + resumen corto),
-- no el detalle clínico completo -- ese detalle vive en las pantallas
-- específicas de cada uno, fuera del alcance de PAC-03.

CREATE TABLE IF NOT EXISTS labs_360 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL REFERENCES pacientes_360(id),
    fecha TEXT NOT NULL,
    prueba TEXT NOT NULL,
    resumen TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_labs_360_paciente ON labs_360(paciente_id);

CREATE TABLE IF NOT EXISTS imagenes_360 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL REFERENCES pacientes_360(id),
    fecha TEXT NOT NULL,
    modalidad TEXT NOT NULL,
    resumen TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_imagenes_360_paciente ON imagenes_360(paciente_id);

CREATE TABLE IF NOT EXISTS notas_360 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL REFERENCES pacientes_360(id),
    fecha TEXT NOT NULL,
    resumen TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notas_360_paciente ON notas_360(paciente_id);
