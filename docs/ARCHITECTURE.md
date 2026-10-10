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
(`llm_client.OpenAILLMClient`, un modelo GPT de OpenAI, el mismo que usa
el agente de `tx_clinica`; ver `docs/llm_openai.md`), además del cliente de
referencia sin proveedor externo (`RuleBasedLLMClient`) usado por
defecto en pruebas.

`ia_clinica/review` implementa **IA-03 — revisión y aprobación de la nota
clínica generada**: recibe el borrador de IA-02 y agrega el ciclo de vida
de edición/aprobación (estados explícitos `DRAFT`/`APPROVED`, persistido
en su propia tabla SQLite para que sobreviva a cerrar sesión). Ninguna
nota adquiere estado oficial sin una acción explícita de aprobación con
un identificador de médico autorizado. Ver `docs/ia_clinica_revision.md`.

`ia_clinica/summary` implementa **IA-04 — resumen clínico de caso para
junta médica / interconsulta**: a diferencia de `ia_clinica/notes`
(acotado a una consulta), combina *todo* el expediente disponible del
paciente (mismo alcance que `dx_clinica`, vía
`expediente.adapters.construir_contexto_resumen_caso`) en un
documento de cuatro secciones (diagnóstico, estadio, tratamientos
previos, estado actual). Diagnóstico y estadio se toman directamente del
registro estructurado del paciente, sin pasar por ningún LLM; las otras
dos secciones reutilizan la misma interfaz `LLMClient` (y el mismo
`OpenAILLMClient`) que IA-02/IA-03, con la misma validación de
trazabilidad. Cualquier sección sin información suficiente queda marcada
explícitamente, nunca inventada. Ver `docs/ia_clinica_resumen_caso.md`.

> Nota de numeración: el backlog (`backlog_copiloto_oncologico.md`)
> registra un **IA-04** distinto ("razonamiento y fuentes de cada
> recomendación"), ya cubierto por `ia_clinica/explainability/`. Esta
> historia de "resumen de caso" se recibió esta sesión explícitamente
> rotulada como IA-04 con otras dependencias (`AI-02, HC-06`); se
> implementó tal como se pidió, quedando pendiente reconciliar la
> numeración en el backlog.

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
`expediente`. Es apoyo a la decisión: no reemplaza el juicio del
profesional y solo aplica criterios del sistema seleccionado.
`estadificacion/incompleta.py` añade **EST-03 — manejo de la estadificación
incompleta**: una capa de lectura sobre la propuesta de EST-01 que identifica
explícitamente los componentes indeterminados, indica qué información falta para
cada uno y comunica el rango de estadios posibles sin asumir valores ni presentar
un estadio definitivo cuando la información es insuficiente.
`estadificacion/confirmacion.py` añade **EST-02 — ajuste manual de
estadificación**: registra en su propia tabla SQLite de solo-inserción
(`confirmaciones_estadificacion`, mismo diseño que
`dx_clinica/juicio_clinico.py` para DX-03) el estadio que el médico confirma o
ajusta; ese siempre prevalece como el estadio vigente sobre la propuesta de
EST-01, sin ninguna validación de concordancia, y deja registrado si difirió de
la sugerencia (insumo directo de AUD-02, todavía no implementada). Ver
`docs/estadificacion.md`.

### expediente

Base de datos SQLite pequeña con datos sintéticos (pacientes, consultas,
laboratorios, imagenología, biomarcadores), usada para probar `ia_clinica`
y `dx_clinica` de forma end-to-end. No implementa HC-01 a HC-06
(integración real con sistemas externos); es una herramienta de
prueba/demo. Ver `docs/expediente.md`.
Se extendió con dos tablas para TX-01: datos_clinicos_estructurados (variable/valor genérico, para el vocabulario categórico que cada módulo de guidelines/ necesita — estadio TNM, biomarcadores, ECOG, etc., que no existía en ninguna tabla de texto libre previa) y comorbilidades (registro clínico de condiciones del paciente, con una columna separada tipo_contraindicacion_ici para el juicio explícito del oncólogo sobre si esa condición contraindica inmunoterapia).

### historia_clinica

Épica Historia Clínica, sobre la **misma** base de datos de
`expediente` (`historia_clinica.db.crear_conexion` aplica ambos
esquemas), así que lo que se integra aquí lo leen DX, EST, TX e IA sin
adaptadores adicionales.

- `integracion_externa.py` — **HC-01**: importa historia previa desde FHIR
  R4 y HL7 v2 ORU^R01, o asocia un PDF no estructurado reutilizando DOC-01.
  Verifica la identidad antes de importar, importa cada mensaje en una sola
  transacción, es idempotente y registra los fallos en
  `sincronizaciones_externas` sin bloquear el expediente. Ver
  `docs/historia_clinica_integracion.md`.
- `imagenes_pacs.py` — **HC-03**: lista los estudios de imagen del PACS por
  DICOMweb (QIDO-RS), los enlaza a su informe de `imagenologia` solo si el
  enlace es único y entrega el `StudyInstanceUID` a un visor de terceros
  (no hay visor propio). Verifica la identidad de cada estudio y, si el PACS
  no está disponible, lo informa de forma explícita (tablas `estudios_pacs` y
  `consultas_pacs`). Ver `docs/historia_clinica_imagenes_pacs.md`.
- `informacion_faltante.py` — **HC-05**: evalúa el expediente contra un
  checklist configurable por tipo de cáncer y fase
  (`checklists_informacion.yaml`). Nunca devuelve "completo" si no hay
  checklist. Ver `docs/historia_clinica_informacion_faltante.md`.
- `laboratorios.py` — **HC-02**:
  - todo laboratorio que entra (HL7, FHIR, cBioPortal o manual) pasa por `procesar_resultados` en la misma transacción;
  - alerta por valor crítico (`rangos_criticos_laboratorio.yaml`);
  - conflicto cuando hay dos resultados del mismo marcador y momento con valores distintos, sin sobrescribir ninguno;
  - tendencias por marcador;
  - doble validación de identidad (identificación + nombre).

  Tablas laterales: `recepcion_laboratorio`, `alertas_laboratorio` y `conflictos_laboratorio`. Ver `docs/historia_clinica_laboratorios.md`.
- `biopsias_biomarcadores.py` — **HC-04**:
  - episodios diagnósticos, con las biopsias vinculadas a ellos;
  - biomarcadores validados contra `catalogo_biomarcadores.yaml` (que a su vez se valida contra `guidelines/*/variables.yaml`), con doble ingreso;
  - los accionables se destacan y su variable se escribe en `datos_clinicos_estructurados` para TX-01;
  - los importados quedan pendientes hasta que el oncólogo los confirma.

  Tablas: `episodios_diagnosticos`, `biopsias` y `detalle_biomarcador`. Ver `docs/historia_clinica_biomarcadores.md`.

### cbioportal

Importa pacientes reales desidentificados de cBioPortal (MSK-CHORD) al
expediente por el camino de HC-01, y opcionalmente a la base de `patients`.
Tiene dos modos:

- **Índice:** todos los pacientes con datos básicos; el detalle se trae al abrir cada uno.
- **Completo:** todo el detalle de cada paciente, de una vez.

Después de importar, vincula las muestras con HC-04 (episodio, biopsias y
biomarcadores pendientes de confirmación). Ver `docs/cbioportal.md`.

### patients

Módulo de pacientes:

- registro, búsqueda (PAC-02) y resumen 360 (PAC-03), sobre su propia base (`patients/db`);
- API HTTP (`patients/api.py`) que también expone HC-02, HC-03 y HC-04 sobre el expediente;
- `patients/expediente.py` vincula las dos bases por identificación;
- cliente de consola: `python -m patients.demo`.

Ver `docs/pacientes.md` y `docs/PACIENTES_DEMO.md`.

### dx_clinica

Contiene las capacidades de la épica Diagnóstico. Implementa **DX-02** —
apoyo al diagnóstico diferencial: combina los hallazgos clínicos de
`expediente` con un catálogo diagnóstico explícito y con
evidencia leída de `guidelines/*/metadata.yaml` (una implementación
mínima de lo que después sería un IA-04 de explicabilidad/trazabilidad de
evidencia — ver nota de numeración más abajo). No usa las reglas de
tratamiento del motor `core`/`guidelines`; solo lee sus metadatos como
fuente de evidencia citable. Ver `docs/dx_clinica.md`.

También implementa **DX-03** — manejo de la incertidumbre diagnóstica y
juicio clínico: analiza (sin modificarlo) el resultado de DX-02 para
distinguir información faltante, ambigüedad entre alternativas empatadas
e incertidumbre inherente a un perfil poco específico, y persiste en
SQLite (solo-inserción) el juicio diagnóstico del médico, que siempre
prevalece sobre la sugerencia del sistema. Ver
`docs/dx_clinica_incertidumbre.md`.

Y **DX-01** — recomendación de estudios necesarios: dada una sospecha
diagnóstica (texto) y el expediente completo del paciente (mismo
`obtener_hallazgos_de_paciente` de DX-02), sugiere una lista priorizada
de estudios de laboratorio/imagenología/biomarcadores con justificación
explícita, sin repetir un estudio si ya existe uno equivalente **reciente**
en el expediente (un resultado antiguo, fuera de la ventana de recencia
configurable, sí se vuelve a sugerir). Ver
`docs/dx_clinica_recomendacion_estudios.md`.

### documentos_clinicos

Contiene las capacidades de la épica Gestión Documental. Implementa
**DOC-01** — carga de documentos clínicos: `carga_documentos.py` recibe
un archivo (PDF, imagen o DICOM) y lo asocia al expediente de un
paciente (validado contra `expediente.pacientes`, que cumple
en la práctica el rol de PAC-01 en este repositorio). Nunca confía solo
en la extensión del archivo: verifica también la firma binaria real del
contenido (`%PDF-`, cabecera JPEG/PNG, preámbulo DICOM), rechazando con
un mensaje explícito tanto un formato no soportado como uno soportado
cuyo contenido no le corresponde. El contenido binario se guarda en
disco (bajo un directorio configurable, con un nombre generado); solo
los metadatos y la ruta resultante se guardan en una tabla propia de
solo-inserción (mismo diseño que `dx_clinica/juicio_clinico.py` para
DX-03), de forma que "el historial de documentos del paciente" sea
simplemente listar sus filas. Ver `docs/documentos_clinicos_carga.md`.

También implementa **DOC-02** — exportación de expediente médico a PDF:
`pdf_export.py` es un renderizador genérico que no conoce `ia_clinica`,
`dx_clinica` ni `expediente` — recibe un `DocumentoExportable`
(título, referencia de paciente, secciones con bloques de texto o tabla,
disclaimer y advertencias opcionales) y produce un PDF con formato
profesional, sin generar nunca un PDF a partir de un documento sin
contenido real (`DocumentoInsuficienteError`). `adaptadores.py` traduce
las dos fuentes que permite la historia — el resumen de caso de IA-04 y
el expediente clínico completo directamente desde
`expediente` — al modelo genérico, cada una en su propia
función. Ver `docs/documentos_clinicos_exportacion.md`.

### configuracion

**CFG-01 — guías clínicas institucionales por defecto** (NCCN, ESMO y/o
protocolo interno, en orden de prioridad). La configuración está versionada
(solo inserción), restringida al rol `administrador_clinico` y auditada.
Filtra EV-01 (`EvidenceSearchService.search(organizations=...)`) y expone
`modulos_habilitados()` para los demás consumidores. Ver
`docs/configuracion_guias.md`.

### privacidad

**NFR-06 — cumplimiento de datos personales y gestión de derechos.**
Políticas de tratamiento configurables por jurisdicción (la norma es un
dato, no código), autorizaciones con evidencia y finalidad, solicitudes de
derechos del titular con plazo y recopilación de su información, todo con
traza en `auditoria.eventos_acceso` (AUD-01). Tablas de solo inserción.
Ver `docs/privacidad.md`.

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