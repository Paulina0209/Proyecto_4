# Arquitectura del proyecto

## Versión

Arquitectura base v1.1.

## Decisión arquitectónica

El sistema separa cinco responsabilidades:

1. extracción y normalización de hechos clínicos;
2. navegación por rutas clínicas;
3. evaluación de reglas;
4. normalización de evidencia entre organizaciones;
5. auditoría y priorización de alertas.

El motor no contendrá nombres de patologías, medicamentos ni guías específicas.
El conocimiento clínico permanecerá en módulos independientes bajo `guidelines`.

## Componentes

### core

Contiene modelos, operadores, motor de inferencia, normalización de evidencia,
auditoría y derivación controlada de prioridad de alertas.

Se extendió con evaluate_rule_set_hypothetical: evalúa un rule-set contra los facts reales de un paciente fusionados con overrides explícitos, para poder responder "¿esta regla aplicaría SI estos valores adicionales fueran ciertos?" sin que el motor necesite saber para qué se usa esa pregunta. Usado por tx_clinica para TX-01.

### standards

Contiene los cruces entre sistemas de gradación de organizaciones y las
políticas institucionales de priorización.

### guidelines

Contiene metadatos, variables, rutas, regímenes y reglas de cada escenario clínico.

### ia_clinica

Contiene las capacidades del agente copiloto de IA (épica IA del backlog:
IA-01 a IA-04). Es independiente del motor de reglas de `core`/`guidelines`:
no navega rutas clínicas ni evalúa reglas de tratamiento, y no usa el
contenido de `guidelines` como entrada. Cada historia de la épica IA se
implementa como un submódulo propio (por ejemplo, `ia_clinica/notes` para
IA-02 — generación automática de notas clínicas). Ver
`docs/ia_clinica_notas.md` para el detalle de IA-02.

`ia_clinica/notes` ya conecta un proveedor de LLM real
(`llm_client.OllamaLLMClient`), que reutiliza el mismo modelo local
servido por Ollama que usa `tx_clinica` para TX-01, además del cliente de
referencia sin proveedor externo (`RuleBasedLLMClient`) usado por
defecto en pruebas.

`ia_clinica/review` implementa **IA-03 — revisión y aprobación de la nota
clínica generada**: recibe el borrador de IA-02 y agrega el ciclo de vida
de edición/aprobación (estados explícitos `DRAFT`/`APPROVED`, persistido
en su propia tabla SQLite para que sobreviva a cerrar sesión). Ninguna
nota adquiere estado oficial sin una acción explícita de aprobación con
un identificador de médico autorizado. Ver `docs/ia_clinica_revision.md`.

### clinical_query

Implementa **IA-01 — consulta en lenguaje natural sobre el paciente** y
**IA-06 — manejo de consultas clínicas ambiguas**. IA-06 no es un componente
aparte: es una capa de detección previa a la respuesta dentro del mismo
servicio (`clinical_query/ambiguity.py`), que distingue ambigüedad de paciente,
de dato clínico o de episodio y devuelve una solicitud de aclaración
(`QueryResponse.needs_clarification`) en vez de elegir una interpretación en
silencio. La recuperación siempre se acota al paciente activo. Ver
`docs/clinical_query_ambiguedad.md`.

### estadificacion

Contiene las capacidades de la épica Estadificación. Implementa **EST-01 —
estadificación automática asistida**: propone componentes T/N/M y un grupo de
estadio usando un catálogo versionado de sistemas de estadificación
(`estadificacion/staging_systems.py`, hoy un subconjunto ilustrativo de AJCC 8ª),
seleccionado según el tipo de cáncer del paciente. Cada propuesta conserva el
sistema y la versión aplicados, el criterio usado para cada componente y la
trazabilidad hasta la fila exacta de `datos_clinicos_estructurados` en
`historia_clinica_mock`. Es apoyo a la decisión: no reemplaza el juicio del
profesional y solo aplica criterios del sistema seleccionado. Ver
`docs/estadificacion.md`.

### historia_clinica_mock

Base de datos SQLite pequeña con datos sintéticos (pacientes, consultas,
laboratorios, imagenología, biomarcadores), usada para probar `ia_clinica`
y `dx_clinica` de forma end-to-end. No implementa HC-01 a HC-06
(integración real con sistemas externos); es una herramienta de
prueba/demo. Ver `docs/historia_clinica_mock.md`.
Se extendió con dos tablas para TX-01: datos_clinicos_estructurados (variable/valor genérico, para el vocabulario categórico que cada módulo de guidelines/ necesita — estadio TNM, biomarcadores, ECOG, etc., que no existía en ninguna tabla de texto libre previa) y comorbilidades (registro clínico de condiciones del paciente, con una columna separada tipo_contraindicacion_ici para el juicio explícito del oncólogo sobre si esa condición contraindica inmunoterapia).

### dx_clinica

Contiene las capacidades de la épica Diagnóstico (DX-01, DX-02...).
Implementa DX-02 — apoyo al diagnóstico diferencial: combina los
hallazgos clínicos de `historia_clinica_mock` con un catálogo diagnóstico
explícito y con evidencia leída de `guidelines/*/metadata.yaml` (una
implementación mínima de lo que después será IA-04). No usa las reglas de
tratamiento del motor `core`/`guidelines`; solo lee sus metadatos como
fuente de evidencia citable. Ver `docs/dx_clinica.md`.

### tx_clinica
Contiene las capacidades de la épica Tratamientos (TX-01, TX-02...). Implementa TX-01 — recomendación de tratamiento: evalúa cada régimen conocido de guidelines/<módulo>/regimens.yaml de forma hipotética contra las reglas del módulo aplicable, para generar sugerencias desde estadio/biomarcadores en vez de solo auditar concordancia (que es para lo que esas reglas fueron escritas originalmente). Implementa también TX-02 — nivel de evidencia por recomendación, leyendo evidence.native.* y source/module_version directamente de la regla y el módulo reales. No reescribe ninguna regla existente. 

### docs

Contiene la matriz clínica, el árbol de decisión y el modelo de evidencia.

### tests

Contiene casos sintéticos y pruebas automatizadas.

## Principios

1. Las reglas clínicas no se escriben directamente dentro del motor.
2. Cada regla conserva la gradación original de la organización.
3. La gradación original nunca se reemplaza por un único número universal.
4. La normalización produce dimensiones comparables, no una falsa equivalencia.
5. La aplicabilidad clínica de una regla no depende de su nivel de evidencia.
6. El nivel de evidencia influye únicamente en la explicación y prioridad de revisión.
7. Los datos ausentes no se interpretan como negativos.
8. La concordancia y la prioridad de alerta son procesos separados.
9. Toda regla debe tener fuente, versión, alcance y estado de validación.
10. Las reglas solo se consideran validadas después de revisión clínica.

## Política de estabilidad

No se renombrarán ni moverán carpetas o archivos sin una decisión explícita,
documentada en `CHANGELOG.md`.