# Changelog

## [Sin versionar] — Rama `NatiMejia`

### Añadido

- Nuevo componente `ia_clinica/` (agente copiloto de IA), con el submódulo
  `ia_clinica/notes` que implementa **IA-02 — Generación automática de
  notas clínicas**: generación de un borrador estructurado (SOAP o formato
  configurado por la institución) a partir del contexto de la consulta,
  con validación de trazabilidad para evitar contenido no verificable y
  marcado explícito de todo resultado como borrador generado por IA.
- Pruebas automatizadas en `tests/ia_clinica/notes/` cubriendo los cuatro
  criterios de aceptación de IA-02.
- `conftest.py` en la raíz del repositorio para que los paquetes de primer
  nivel (`ia_clinica`, `guidelines`) sean importables en las pruebas sin
  instalar el proyecto.
- `docs/ia_clinica_notas.md`: documentación de diseño de IA-02.
- `ClinicalContext.from_text()` y `split_sentences()` en
  `ia_clinica.notes.models`: permiten construir el contexto a partir de un
  único párrafo de texto libre (no solo fragmentos ya separados a mano).
- Nuevo componente `historia_clinica_mock/`: base de datos SQLite con
  datos sintéticos (pacientes, consultas, laboratorios, imagenología,
  biomarcadores) y un adaptador (`adapters.construir_contexto_clinico`)
  que conecta esos datos con `ia_clinica.notes` para poder generar
  borradores de nota a partir de una consulta guardada, con trazabilidad
  hasta la fila exacta de la base de datos. Ver
  `docs/historia_clinica_mock.md`.
- Pruebas en `tests/historia_clinica_mock/` (esquema, seed, repository,
  adaptador e integración end-to-end con IA-02).
- `historia_clinica_mock`: nuevas consultas a nivel de todo el paciente
  (`laboratorios_de_paciente`, `imagenologia_de_paciente`,
  `biomarcadores_de_paciente`) y `obtener_hallazgos_de_paciente` (modelo
  `HallazgoClinico`), para historias que necesitan combinar todo el
  expediente disponible, no una sola consulta.
- Nuevo componente `dx_clinica/` que implementa **DX-02 — Apoyo al
  diagnóstico diferencial**: lista priorizada de alternativas
  diagnósticas sustentadas en hallazgos reales del expediente
  (`historia_clinica_mock`) y en evidencia trazable leída de
  `guidelines/*/metadata.yaml` (implementación mínima de IA-04, que
  todavía no existe como historia propia). Incluye detección simple de
  negación en el emparejamiento de texto (para no confundir "sin
  hallazgos de progresión" con progresión real) y nunca presenta
  porcentajes ni probabilidades numéricas, solo un orden explicable por
  conteo de criterios sustentados. Ver `docs/dx_clinica.md`.
- Pruebas en `tests/dx_clinica/` (matcher/negación, catálogo de
  evidencia, y los cinco criterios de aceptación de DX-02).
- `ia_clinica.notes.llm_client.OllamaLLMClient`: nuevo cliente `LLMClient`
  que conecta el generador de notas de IA-02 con el modelo local ya
  configurado con Ollama en este proyecto (el mismo servidor que usa
  `tx_clinica` para TX-01), siguiendo el mismo contrato JSON que
  `RuleBasedLLMClient` — `ClinicalNoteGenerator` no requirió ningún
  cambio. Incluye `esta_disponible()` (chequeo de salud sin generar
  texto) para poder usar `RuleBasedLLMClient` como respaldo automático si
  no hay servidor Ollama corriendo. Pruebas en
  `tests/ia_clinica/notes/test_ollama_llm_client.py` (sin depender de un
  servidor Ollama real: se simula `requests`).
- Nuevo componente `ia_clinica/review/` que implementa **IA-03 —
  Revisión y aprobación de la nota clínica generada**: ciclo de vida
  explícito de una nota en revisión (estados `DRAFT`/`APPROVED`,
  persistidos en SQLite propio — no en memoria — para sostener el
  criterio de "sigue como borrador no confirmado aunque cierre sesión"),
  edición manual de secciones con historial completo de cambios, y una
  única función de aprobación (`aprobar_nota`) que exige un identificador
  no vacío del médico autorizado y que es la única forma de llegar al
  estado oficial. Una vez aprobada, la nota deja de aceptar ediciones
  desde este flujo de borrador. Ver `docs/ia_clinica_revision.md`.
- Pruebas en `tests/ia_clinica/review/` cubriendo los cinco criterios de
  aceptación de IA-03, incluyendo un caso que cierra y reabre la conexión
  SQLite (archivo real, no `:memory:`) para simular "cerrar sesión y
  volver a entrar".
- Nuevo `ia_clinica.notes.llm_client.OllamaLLMClient`: cliente `LLMClient`
  que conecta el generador de notas de IA-02 con el modelo local ya
  configurado con Ollama en el proyecto (el mismo servidor que usa
  `tx_clinica` para TX-01), con `esta_disponible()` como chequeo de salud
  sin generar texto. Usa `base_url="http://127.0.0.1:11434"` (en vez de
  `localhost`, que en algunas máquinas Windows resuelve primero a `::1`
  y puede fallar aunque el servidor esté corriendo) y `"format": "json"`
  por defecto (restringe la decodificación a una gramática JSON válida;
  se puede desactivar con `usar_formato_json=False` si resulta muy lento
  en una máquina concreta, a costa de arriesgar una respuesta con un
  error de sintaxis a mitad de generación). Pruebas en
  `tests/ia_clinica/notes/test_ollama_llm_client.py` (sin depender de un
  servidor Ollama real).
- `dx_clinica/incertidumbre.py`: implementa **DX-03 — Manejo de la
  incertidumbre diagnóstica y juicio clínico** (parte 1 de 2). Analiza el
  `ResultadoDiagnosticoDiferencial` de DX-02 sin modificarlo y distingue
  tres tipos de incertidumbre (información faltante, ambigüedad entre
  alternativas empatadas, e incertidumbre inherente a un perfil poco
  específico), con sugerencias de información adicional explícitamente
  rotuladas como no vinculantes (nunca como órdenes clínicas automáticas).
- `dx_clinica/juicio_clinico.py` + `schema_juicio_clinico.sql`:
  implementa DX-03 (parte 2 de 2). Persiste en SQLite (tabla de
  solo-inserción) el juicio diagnóstico que registra el médico, que
  siempre prevalece sobre la sugerencia del sistema
  (`obtener_decision_diagnostica_vigente`) sin ninguna validación de
  concordancia — el sistema nunca bloquea ni sobreescribe ese juicio.
- Pruebas en `tests/dx_clinica/test_incertidumbre.py` y
  `tests/dx_clinica/test_juicio_clinico.py` cubriendo los cinco criterios
  de aceptación de DX-03. Demo en `dx_clinica/demo_incertidumbre.py`. Ver
  `docs/dx_clinica_incertidumbre.md`.
- Nuevo componente `ia_clinica/summary/` que implementa **IA-04 — Resumen
  clínico de caso para junta médica / interconsulta**: genera un
  documento estructurado (diagnóstico, estadio, tratamientos previos,
  estado actual) a partir de *todo* el expediente disponible del
  paciente, no de una sola consulta (mismo alcance que DX-02). Las
  secciones "diagnóstico" y "estadio" se toman directamente del registro
  estructurado del paciente, sin pasar por ningún LLM; "tratamientos
  previos" y "estado actual" se redactan a partir de los hallazgos no
  estructurados del expediente reutilizando la misma interfaz
  `LLMClient` de IA-02/IA-03 (y, por tanto, el mismo `OllamaLLMClient` ya
  configurado), con la misma validación de trazabilidad y el mismo
  descarte de contenido sin cita válida. Si alguna sección queda sin
  información suficiente, el documento la marca explícitamente en vez de
  inventar contenido, con una advertencia visible al inicio listando qué
  falta (criterio de aceptación AC2). Ver `docs/ia_clinica_resumen_caso.md`.
- Nuevo adaptador `historia_clinica_mock.adapters.construir_contexto_resumen_caso`,
  que combina `diagnostico_principal`/`estadio` del paciente con los
  mismos hallazgos que ya reúne `obtener_hallazgos_de_paciente` (DX-02)
  en un `CaseSummaryContext` para IA-04.
- Pruebas en `tests/ia_clinica/summary/` (modelos, prompts/cliente de
  referencia, y los dos criterios de aceptación de IA-04 más la regla de
  no-alucinación), y casos añadidos a
  `tests/historia_clinica_mock/test_adapters.py` para el nuevo adaptador.
  Demo en `ia_clinica/summary/demo.py`.

- Nuevo `dx_clinica/catalogo_estudios.py` + `dx_clinica/recomendacion_estudios.py`:
  implementan **DX-01 — Recomendación de estudios necesarios**. Dada una
  sospecha diagnóstica (texto) y el expediente completo de un paciente
  (`obtener_hallazgos_de_paciente`, mismo alcance que DX-02), sugiere una
  lista priorizada de estudios (laboratorio, imagenología o biomarcador),
  cada uno con su justificación clínica explícita. Antes de sugerir un
  estudio, se cruza contra los hallazgos ya registrados del mismo tipo:
  si ya existe uno equivalente **reciente** (dentro de una ventana de
  días configurable, 90 por defecto), no se vuelve a sugerir — pero uno
  antiguo (fuera de la ventana) sí se sugiere de nuevo, porque un
  resultado desactualizado no descarta la necesidad clínica de
  repetirlo. Si la sospecha diagnóstica no coincide con ningún perfil
  del catálogo, no se inventa una lista genérica: se devuelve vacía con
  una advertencia explícita. Reutiliza `dx_clinica.matcher.coincide_sin_negacion`
  (mismo detector simple de negación que ya usa DX-02) tanto para
  reconocer la sospecha diagnóstica como para detectar estudios
  equivalentes. Ver `docs/dx_clinica_recomendacion_estudios.md`.
- Pruebas en `tests/dx_clinica/test_recomendacion_estudios.py` cubriendo
  los dos criterios de aceptación de DX-01 (lista priorizada con
  justificación; no repetir estudios redundantes), la regla de "ventana
  de recencia" configurable, y una integración con los pacientes
  sintéticos reales (María, Carlos). Demo en `dx_clinica/demo_estudios.py`.

> Nota de numeración: el documento `backlog_copiloto_oncologico.md`
> registra **IA-04** como "razonamiento y fuentes de cada recomendación"
> (ya cubierto por `ia_clinica/explainability/`). La historia de usuario
> de "resumen de caso para junta médica / interconsulta" se recibió esta
> sesión explícitamente rotulada como **IA-04** (con dependencias
> `AI-02, HC-06`), distinta de la que aparece con ese mismo id en el
> backlog. Se implementó tal como se pidió; vale la pena reconciliar la
> numeración en el backlog cuando se tenga oportunidad.

- `clinical_query/ambiguity.py` + cambios en `service.py`/`normalizer.py`/`models.py`:
  implementan **IA-06 — Manejo de consultas clínicas ambiguas**. Antes de
  construir la respuesta, el servicio detecta tres tipos de ambigüedad
  (paciente distinto al activo, más de un dato clínico posible, o dato presente
  en más de un episodio) y devuelve una solicitud de aclaración
  (`QueryResponse.needs_clarification`) con opciones concretas, en vez de elegir
  una interpretación en silencio como hacía IA-01. La recuperación sigue
  acotada siempre al paciente activo; la conversación se reanuda pasando un
  `Clarification` junto con la misma pregunta (servicio sin estado). Nuevo
  `detect_concepts` (lista todos los conceptos posibles; `detect_concept` se
  conserva). Pruebas en `tests/clinical_query/test_ia06_ambiguous_queries.py`;
  `demo_ia01.py` muestra el ciclo de aclaración. Ver
  `docs/clinical_query_ambiguedad.md`.
- Nuevo componente `estadificacion/` que implementa **EST-01 — Estadificación
  automática asistida**: `proponer_estadificacion` propone componentes T/N/M y un
  grupo de estadio a partir de las variables estructuradas del expediente
  (`historia_clinica_mock`), usando un catálogo versionado de sistemas de
  estadificación (`estadificacion/staging_systems.py`, subconjunto ilustrativo de
  AJCC 8ª, no validado clínicamente). Cada propuesta conserva el sistema y la
  versión aplicados, el criterio de cada componente y la trazabilidad hasta la
  fila `dato-<id>` de origen; solo se leen variables del sistema seleccionado y
  los componentes ausentes se reportan como faltantes sin inventar valores. Es
  apoyo a la decisión (`DISCLAIMER`). Pruebas en `tests/estadificacion/`; demo en
  `estadificacion/demo.py`. Ver `docs/estadificacion.md`.
- `estadificacion/incompleta.py`: implementa **EST-03 — Manejo de la
  estadificación incompleta**. Capa de lectura sobre la `PropuestaEstadificacion`
  de EST-01 (mismo patrón que `dx_clinica/incertidumbre.py` respecto a DX-02):
  `analizar_estadificacion_incompleta` identifica explícitamente los componentes
  T/N/M que no se pueden determinar, el motivo y la información clínica requerida
  para cada uno (texto versionado por sistema en `ComponenteDef`), y calcula el
  rango de estadios posibles (`estadios_candidatos`) explorando los valores que
  podrían tomar los componentes pendientes — sin asumir ninguno. `estadio_confirmado`
  solo es `True` con un único estadio posible y sin componentes pendientes.
  `ComponenteEstadio.familia` y `PropuestaEstadificacion.cancer_type` son campos
  nuevos (con default) para soportar el análisis. Pruebas en
  `tests/estadificacion/test_incompleta.py` (los cinco criterios de aceptación de
  EST-03); paciente sintético Laura ampliado con `pT3 N0` y M pendiente. Ver
  `docs/estadificacion.md`.
- `estadificacion/confirmacion.py` + `schema_confirmacion_estadio.sql`:
  implementa **EST-02 — Ajuste manual de estadificación**. Mismo diseño que
  `dx_clinica/juicio_clinico.py` para DX-03: tabla propia de solo-inserción
  (`confirmaciones_estadificacion`, conexión SQLite separada de
  `historia_clinica_mock`), "vigente" = la confirmación más reciente, y
  ninguna validación de concordancia — `confirmar_estadificacion` nunca
  compara el estadio del médico contra la propuesta de EST-01 para aceptarla o
  rechazarla, solo para calcular `difiere_de_sugerencia` (insumo directo de
  AUD-02) y dejar un snapshot de auditoría de qué sugería el sistema.
  `obtener_estadificacion_vigente` resuelve qué mostrar: la confirmación del
  médico si existe, o la propuesta del sistema rotulada como apoyo si no.
  Pruebas en `tests/estadificacion/test_confirmacion.py`; demo ampliada en
  `estadificacion/demo.py`. Ver `docs/estadificacion.md`.
- `historia_clinica_mock/seed.py`: nuevo paciente sintético 6
  (`Diana Sofía Restrepo`, NSCLC temprano) con hemoglobina en dos consultas
  (para IA-06) y T/N/M clínico completo (para EST-01); variables `clinical_m_status`
  añadidas a María y T/N/M a Roberto. Solo son filas nuevas: no se modificó
  ningún registro sintético existente. Se actualizaron dos aserciones de
  `tests/historia_clinica_mock/test_db_y_seed.py` que fijaban el número exacto de
  pacientes/consultas del seed (ya desactualizadas en `main`) para fijar el
  mínimo y las invariantes en su lugar.

- Nuevo `documentos_clinicos/carga_documentos.py` que implementa
  **DOC-01 — Carga de documentos clínicos**: `cargar_documento_clinico`
  valida que el paciente exista (contra `historia_clinica_mock`, que
  cumple en la práctica el rol de PAC-01 en este repositorio), que la
  extensión del archivo esté en el catálogo `FORMATOS_SOPORTADOS`
  (`.pdf`, `.jpg`/`.jpeg`/`.png`, `.dcm`) y que el contenido real tenga
  la firma binaria correspondiente a ese formato (nunca confía solo en
  la extensión), antes de guardar el archivo en disco y su metadato en
  una tabla propia de solo-inserción
  (`schema_documentos_clinicos.sql`, mismo diseño que
  `dx_clinica/juicio_clinico.py` para DX-03). `listar_documentos_de_paciente`
  es el historial de documentos del paciente (AC1); un formato no
  reconocido o un contenido que no coincide con el formato declarado se
  rechazan con mensajes explícitos y distintos
  (`FormatoNoSoportadoError`, `ContenidoNoCoincideConFormatoError`),
  listando los formatos aceptados (AC2).
- Pruebas en `tests/documentos_clinicos/test_carga_documentos.py`
  cubriendo los dos criterios de aceptación de DOC-01, el rechazo por
  contenido no coincidente y las validaciones básicas de forma; demo en
  `documentos_clinicos/demo_carga_documentos.py`. Ver
  `docs/documentos_clinicos_carga.md`.
- Nuevo componente `documentos_clinicos/` que implementa **DOC-02 —
  Exportación de expediente médico a PDF**: `pdf_export.py` es un
  renderizador genérico (basado en `reportlab`) que recibe un modelo
  independiente de fuente (`DocumentoExportable`, con secciones de texto
  y/o tabla, disclaimer y advertencias opcionales) y produce un PDF con
  formato profesional (encabezado, pie de página con paginación,
  callout de disclaimer, tablas con estilo); nunca genera un PDF a
  partir de un documento sin contenido real (`DocumentoInsuficienteError`).
  `adaptadores.py` traduce las dos fuentes que permite la historia — el
  resumen de caso de IA-04 (`resumen_caso_a_documento_exportable`,
  conservando su disclaimer de IA y exponiendo sus secciones faltantes
  como advertencia visible) y el expediente clínico completo de un
  paciente directamente desde `historia_clinica_mock`
  (`expediente_completo_a_documento_exportable`, sin ningún LLM
  involucrado) — al modelo genérico.
- Pruebas en `tests/documentos_clinicos/` (renderizado a PDF y su
  comportamiento defensivo ante documentos vacíos, y los dos
  adaptadores) y demo end-to-end en
  `documentos_clinicos/demo_exportacion.py`. Ver
  `docs/documentos_clinicos_exportacion.md`.

### Notas

- No se modificó ni se movió ningún archivo existente de `guidelines/`,
  `docs/guidelines/` ni `tests/guidelines/`.
- Se detectó (pero no se modificó) que las pruebas existentes en
  `tests/guidelines/` importan `cdss.core.engine`, un paquete que todavía
  no existe en este repositorio (no hay carpeta `src/cdss` ni `core/`).
  Esas pruebas ya fallaban en `main` antes de esta rama por este motivo;
  queda fuera del alcance de IA-02 resolverlo.

## [Sin versionar] — SEC-01, AUD-01 y AUD-02

### Añadido

- Nuevo componente `seguridad/` que implementa **SEC-01 — Autenticación y
  control de acceso por rol**: `seguridad/autenticacion.py` (alta de
  usuarios y login con hash PBKDF2-HMAC-SHA256 con sal por usuario, sin
  dependencias nuevas, y bloqueo temporal de la cuenta tras 5 intentos
  fallidos consecutivos) y `seguridad/autorizacion.py` (modelo de permisos
  por rol — oncólogo, enfermería, administrativo, auditor — con
  `verificar_permiso`; una acción sin reglas explícitas se deniega a todos
  los roles por diseño). Conectado de forma real y retrocompatible a
  **TX-04**: `clinical_decision.registro.registrar_decision_tratamiento`
  ahora acepta un `usuario: Optional[Usuario] = None`; si se provee, exige
  el permiso de confirmar tratamiento antes de registrar accept/modify/
  reject (si se omite, el comportamiento es idéntico al de antes de esta
  historia). Pruebas en `tests/seguridad/` y
  `tests/clinical_decision/test_registro_control_de_acceso.py`. Demo en
  `seguridad/demo.py`. Ver `docs/seguridad.md`.
- Nuevo componente `auditoria/` que implementa **AUD-01 — Registro de
  auditoría de accesos y acciones**: `auditoria/registro_acceso.py`, tabla
  `eventos_acceso` de solo-inserción (mismo patrón que
  `confirmaciones_estadificacion`/`juicios_clinicos_dx`/
  `decisiones_tratamiento`) sin ninguna función de UPDATE/DELETE expuesta.
  Conectado de forma real y retrocompatible a la API de `patients/`: `GET
  /pacientes/{id}` acepta un `usuario_id` opcional que, si se provee dejar
  el acceso registrado. Pruebas en `tests/auditoria/test_registro_acceso.py`
  y dos pruebas nuevas en `tests/patients/test_api.py`. Ver `docs/auditoria.md`.
- `auditoria/trazabilidad_ia.py`: implementa **AUD-02 — Trazabilidad de
  recomendaciones de IA** como una consulta unificada de solo lectura
  (`obtener_trazabilidad_ia_paciente`) sobre los tres registros de
  recomendación+decisión que ya existían por separado y sin punto de
  consulta común: `dx_clinica.juicio_clinico` (DX-03),
  `estadificacion.confirmacion` (EST-02) y `clinical_decision.registro`
  (TX-04) — este último sin ninguna función de lectura hasta ahora, se le
  agregaron `obtener_decision_por_id`, `obtener_historial_decisiones`,
  `obtener_decision_vigente` y `crear_conexion`. No persiste nada nuevo.
  Pruebas en `tests/auditoria/test_trazabilidad_ia.py`. Demo conjunta con
  AUD-01 en `auditoria/demo.py`. Ver `docs/auditoria.md`.

## [Sin versionar] — HC-01, HC-05 y NFR-06

### Añadido

- Nuevo componente `historia_clinica/` sobre la misma base de datos de
  `historia_clinica_mock`:
  - **HC-01 — Integración de historia clínica externa**
    (`integracion_externa.py`): importación desde FHIR R4 (`FuenteFHIR`,
    `importar_bundle_fhir`) y HL7 v2 ORU^R01 (`importar_mensaje_hl7`) hacia
    `laboratorios`, `imagenologia` y la nueva tabla `antecedentes_externos`.
    Si no hay integración, `cargar_historia_pdf` asocia el PDF vía DOC-01.
    Verifica la identidad del paciente, importa todo o nada, es idempotente
    (`registros_importados`) y registra los fallos en
    `sincronizaciones_externas` sin bloquear el expediente. Ver
    `docs/historia_clinica_integracion.md`.
  - **HC-05 — Detección de información faltante**
    (`informacion_faltante.py`): checklist configurable por tipo de cáncer y
    fase (`checklists_informacion.yaml`) con resultado `COMPLETA`,
    `INCOMPLETA` (cada ítem faltante o no concluyente, con la fila de
    origen) o `NO_EVALUABLE`. Nunca asume completitud. Ver
    `docs/historia_clinica_informacion_faltante.md`.
- Nuevo componente `privacidad/` — **NFR-06 — Cumplimiento de datos
  personales y gestión de derechos**: políticas versionadas y configurables
  por jurisdicción, sin normas escritas en el código; autorizaciones con
  evidencia, estado y finalidad; solicitudes de derechos del titular con
  plazo, ciclo de vida y `recopilar_informacion_titular` (exportable a
  JSON). Tablas de solo inserción con triggers. Ver `docs/privacidad.md`.
- `auditoria.models.TipoAccion`: nuevas acciones
  `configurar_politica_datos`, `registrar_autorizacion` y
  `gestionar_derechos_titular`. Cada operación de NFR-06 deja su evento en la
  misma transacción que el registro.
- Pruebas en `tests/historia_clinica/` y `tests/privacidad/`.

## [Sin versionar] — CFG-01

### Añadido

- Nuevo componente `configuracion/` — **CFG-01 — Configuración de guías
  clínicas institucionales**: el administrador clínico elige las
  organizaciones que usa la institución por defecto (NCCN, ESMO), en orden de
  prioridad, y puede declarar un protocolo interno. Cada cambio es una versión
  nueva (solo inserción) con motivo obligatorio, auditada en AUD-01, incluidos
  los intentos denegados. Guardar una configuración sin módulos computables
  exige confirmación explícita. Ver `docs/configuracion_guias.md`.
- `seguridad`: nuevo rol `administrador_clinico` y acción
  `configurar_guias_institucionales`.
- `auditoria.models.TipoAccion.CONFIGURAR_GUIAS`.
- `evidencia_clinica.EvidenceSearchService.search` / `search_for_patient`:
  parámetro opcional `organizations` (filtra y prioriza por organización). Sin
  él, el comportamiento no cambia. Nueva función `organization_matches`.
- Pruebas en `tests/configuracion/`.

## [Sin versionar] — Base de datos real con cBioPortal

### Añadido

- Nuevo componente `cbioportal/`: importa pacientes reales desidentificados
  de cBioPortal (por defecto MSK-CHORD, `msk_chord_2024`) al expediente que
  leen DX, EST, TX, IA y HC-05. Trae tipo de cáncer, estadio AJCC, HER2 y
  receptores hormonales, ECOG, marcadores tumorales, hallazgos de radiología
  (NLP), tratamientos, mutaciones y fusiones de genes clave, MSI y TMB. La
  carga pasa por HC-01 (identidad, todo-o-nada, idempotencia, trazabilidad),
  con reglas fail-closed: no deriva variables que requieren juicio clínico,
  no etiqueta variantes como "positivo" y solo afirma "no detectada" en genes
  del panel. Ver `docs/cbioportal.md`.
- CLI `python -m cbioportal` para cargar `data/copiloto.db` y, con
  `--db-pacientes`, también la base de búsqueda y 360 (PAC-02/PAC-03).
- `historia_clinica.integracion_externa`: `RegistroExterno` e
  `importar_historia` son públicos, y `sincronizar_paciente` acepta fuentes
  con su propio traductor (`traducir`).
- `patients.models.TipoIdentificacion.EXTERNO` para pacientes importados. El
  formulario de registro lo rechaza.
- Pruebas en `tests/cbioportal/` (sin red).
