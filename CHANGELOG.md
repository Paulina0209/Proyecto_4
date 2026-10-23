# Changelog

## [Sin versionar] — Rama `NatiMejia`

### Añadido

- **Skill `ruta-recomendacion-guias`** (`skills/ruta-recomendacion-guias/SKILL.md` + `references/registro-de-decision.md`, formato
  [agentskills.io](https://agentskills.io/specification)): el procedimiento para trazar una recomendación de tratamiento a
  partir de las guías (paciente registrado o caso del chat, módulo, variables obligatorias, lectura de cada resultado,
  interacciones, registro de la decisión). Pasa el validador de referencia `skills-ref`. Ver `docs/skills.md`.
- `tx_clinica/skills.py`: descubre y valida las skills contra la especificación y las carga por divulgación progresiva
  (catálogo en el prompt → cuerpo al activar → archivos de apoyo bajo demanda; sin salir de la carpeta de la skill).
- Tool `activar_skill` (solo lectura, sin aprobación humana) y `tx_clinica/middleware/exigir_skill.py`: las tools de la ruta
  (`listar_variables_requeridas`, las tres de recomendación y `chequear_interacciones_tratamiento`) no se ejecutan hasta que la
  skill esté activada en la conversación; el modelo recibe el motivo y reintenta.
- La pantalla del chat del expediente muestra «procedimiento de recomendación por guías (skill)» en «Consultó:».
- Pruebas: `tests/tx_clinica/test_skills.py` y `test_skill_agente.py` (validación, recursos, que no se perdió ninguna
  instrucción del prompt original, control de activación con un agente de LangGraph y un modelo guionado).

### Cambiado

- `tx_clinica/prompts/system_prompt.py`: de ~10 000 a ~4 000 caracteres. Se queda con las reglas de seguridad (decisión del
  oncólogo, no inventar valores, recomendar solo con la tool, comorbilidad e interacciones, aprobación humana); el
  procedimiento pasó a la skill. Las reglas ahora son una lista unida con saltos de línea, lo que evita el bug de M6 (barra
  invertida que fundía dos viñetas).
- `construir_agente` agrega el catálogo de skills al prompt y falla al construirse si falta la skill requerida o está mal formada.
- `tests/tx_clinica/test_system_prompt.py`: las comprobaciones de M6 se adaptaron al nuevo reparto (la regla accept-vs-modify
  se comprueba ahora en la skill); `test_tools_wiring.py` espera 11 tools (`activar_skill` es de solo lectura).

## [Sin versionar] — Rama `timeline`

### Añadido

- **HC-06 — Línea de tiempo del paciente** (`historia_clinica/linea_tiempo.py`, `GET /pacientes/{id}/linea-tiempo`):
  diagnósticos, biopsias, biomarcadores, imágenes, laboratorios (uno por día), tratamientos, procedimientos y consultas
  de las dos bases en orden cronológico, con filtro por tipo y las fechas de solo mes/año o solo año marcadas como
  aproximadas. La pantalla «Línea de tiempo» del expediente se activa sola. Ver `docs/historia_clinica_linea_tiempo.md`.
- **CFG-02 — Notificaciones y alertas** (`configuracion/notificaciones.py`, `/notificaciones...` en `patients.api`):
  cada oncólogo elige qué eventos le avisan (resultado crítico, estudio pendiente, interacción) y por qué canal; bandeja
  con «Marcar como leída». La pantalla «Notificaciones» trae el formulario de preferencias. El único canal es la
  aplicación (no hay correo). El enlace «Notificaciones» del menú muestra cuántas hay sin leer, se actualiza solo (cada 45 s, al
  cambiar de pantalla y al volver a la pestaña) y anuncia a lectores de pantalla cuando llega una nueva. Ver
  `docs/configuracion_notificaciones.md`.
- La demo de la interfaz incluye dos antecedentes externos con fecha aproximada (Lucía Herrera).

## [Sin versionar] — Rama `datos-capas`

### Añadido

- **Capas de datos** (`datos/`, ver `docs/datos.md`):
  - capa base de cBioPortal en `data/cbioportal/`, que nadie modifica: índice de 13.159 pacientes y detalle completo de una cohorte de 60;
  - capa de trabajo armada desde la base más un escenario: usuarios por rol, pacientes repartidos entre oncólogos, consentimientos de IA en todos sus estados, autorizaciones de investigación y consultas de revisión;
  - `python -m datos preparar | reiniciar --confirmar | estado | base`. La primera vez respalda las bases anteriores en `data/respaldo_<fecha>/`.

### Cambiado

- `demo.py`, `patients/demo.py` y `demo_laboratorios_biomarcadores.py` usan `datos.escenario.ONCOLOGO_DEMO_ID` en vez del oncólogo 1. `demo.py` prepara las capas si faltan.
- Con la capa de trabajo nueva, `demo_laboratorios_biomarcadores.py` pasa sus 16 verificaciones de HC-02/HC-04; con la base anterior fallaba porque no había episodios ni biopsias.

## [Sin versionar] — Rama `rendimiento-disponibilidad-escalabilidad`

### Añadido

- **NFR-01 — Rendimiento** (`operacion/latencia.py`, `operacion/presupuesto.py`, `operacion/carga.py`, `operacion/rendimiento.py`):
  - `Server-Timing` en cada respuesta y p50/p95 por ruta en `/salud/metricas`;
  - presupuesto de 8 s para GPT con respaldo por reglas: la nota y el resumen siempre llegan en menos de 10 s;
  - `python -m operacion.carga` (prueba de carga por TLS sobre una copia de la base real) y `python -m operacion.rendimiento`.
  - Ver `docs/rendimiento.md`.
- **NFR-02 — Disponibilidad** (`operacion/salud.py`, `operacion/monitor.py`):
  - sondas `/salud/vivo` y `/salud/listo` (503 si falla algo crítico; dependencias externas como `degradado`) en `patients.api` y la pasarela web;
  - `python -m operacion.monitor vigilar|informe`: disponibilidad contra el SLA del 99,5 %, presupuesto de error e incidentes.
  - Ver `docs/disponibilidad.md`.
- **NFR-05 — Escalabilidad horizontal**:
  - `python -m seguridad.servidor_tls --workers N`;
  - `AlmacenSesionesSQLite` (`COPILOTO_SESIONES_DB`): sesiones compartidas entre réplicas.
  - Ver `docs/escalabilidad.md`.
- `demo_operacion.py`: las tres historias sobre una copia de la base real.

### Corregido

- **La API de pacientes fallaba con peticiones simultáneas** (500 en ~80 % con 10 usuarios: `sqlite3.ProgrammingError`). `patients/db.conectar` y `conectar_expediente` usan ahora `check_same_thread=False` en la API, WAL y `busy_timeout` (`operacion/sqlite.py`).

### Cambiado

- `frontend/servidor.py`: se retiró `_permitir_conexiones_entre_hilos`, que ya no hace falta.
- `patients/db`: la base se puede cambiar con `COPILOTO_PACIENTES_DB`.
- `patients/api.py`: `COPILOTO_DETALLE_BAJO_DEMANDA=0` apaga la descarga de cBioPortal al abrir un paciente.
- `OpenAILLMClient` acepta `max_retries` (por defecto 2, como antes).

## [Sin versionar] — Rama `seguridad-consentimiento-cumplimiento`

### Añadido

- **SEC-02 — Cifrado en tránsito y en reposo** (`seguridad/tls.py`, `seguridad/servidor_tls.py`, `seguridad/cifrado.py`):
  - `python -m seguridad.servidor_tls`: sirve las APIs solo con TLS ≥ 1.2 (suites AEAD) y no arranca sin certificado;
  - `SoloHTTPSMiddleware` en `patients.api` y `administracion.api`: 403 a todo lo que no llega por HTTPS, más HSTS;
  - cBioPortal, PACS y visor solo aceptan `https://` (o loopback, para el Orthanc local);
  - AES-256-GCM ligado al paciente para los documentos de DOC-01, y respaldos cifrados de las bases (`python -m seguridad.cifrado`).
  - Ver `docs/seguridad_cifrado.md`.
- **SEC-03 — Consentimiento informado para el uso de IA** (`privacidad/consentimiento_ia.py`):
  - autorización `asistencia_ia` de NFR-06, con evidencia obligatoria, solo inserción y auditoría;
  - sin consentimiento vigente no corren IA-01, IA-02, IA-04, DX-02, EST-01 ni el agente de TX; al retirarlo se apagan sin borrar la historia;
  - endpoints `GET/POST /pacientes/{id}/consentimiento-ia` y `POST .../retiro`, y la línea de comandos `python -m privacidad.consentimiento_ia`.
  - Ver `docs/consentimiento_ia.md`.
- **NFR-04 — Cumplimiento normativo** (`privacidad/minimizacion.py`, `privacidad/cumplimiento.py`):
  - minimización: el texto que llega al modelo sale sin nombre, documento, teléfono ni correo, y el agente ya no recibe el nombre;
  - permisos `REGISTRAR_CONSENTIMIENTO_IA` y `CONFIGURAR_POLITICA_DATOS`;
  - `eventos_acceso` (AUD-01) protegida con triggers de solo inserción;
  - informe verificable `python -m privacidad.cumplimiento`.
  - Ver `docs/cumplimiento_normativo.md`.
- `demo_seguridad_cumplimiento.py` y la sección `seg` de `demo.py`.

### Cambiado

- `demo.py` registra el consentimiento de IA de sus tres pacientes; `obtener_datos_paciente` (TX) ya no devuelve `nombre`.
- Los `TestClient` de las pruebas usan `https://testserver`.
- `requirements.txt`: `cryptography` y `uvicorn`.

## [Sin versionar] — Rama `NatiMejia`

### Añadido

- **Interfaz web clínica** (`frontend/`): blanca y azul, sobria, sin paso de compilación (HTML + CSS + módulos ES que sirve FastAPI):
  - pantallas: acceso, lista de pacientes con filtros, expediente (resumen, laboratorios con alertas y tendencia, imágenes del PACS con visor, biomarcadores, historia clínica), exportación DOC-02 y, para la dirección médica, el tablero ADM-02 en la misma navegación; tema automático/claro/oscuro;
  - pasarela `frontend/servidor.py`: sesión SEC-01 en el servidor (cookie `__Host-`, `HttpOnly`, `Secure`, `SameSite=Strict`), `patients.api` montada **sin cambios** detrás de permisos por rol, identidad tomada de la sesión (se descartan `oncologo_id`/`usuario_id` del navegador y `revisada_por` se fija con el usuario autenticado), lista cerrada de rutas, defensa CSRF, CSP estricta sin `unsafe-inline`, solo HTTPS;
  - **solo el rol `oncologo` ve expedientes**: enfermería y auditoría tienen `ver_expediente` en SEC-01 pero aún no hay asignación de pacientes por persona, así que se les niega con una explicación (no se adivina);
  - modo demostración con datos sintéticos creados con las mismas funciones del sistema: `python -m frontend.demo`;
  - `tests/frontend/` (135 pruebas): sesiones, pasarela, estáticos y Chromium real con axe-core en cada pantalla (claro, oscuro, 320 px, teclado);
  - **no hay prueba con lectores de pantalla ni con personas usuarias**, el PDF sigue sin etiquetar y las sesiones viven en memoria del proceso; ver `docs/frontend.md`.
  - Al probarla apareció un fallo latente de `patients/api.py::get_conn` (conexión SQLite abierta en un hilo y usada en otro con peticiones paralelas); la pasarela lo evita sin tocar `patients/`. Arreglo de raíz: `check_same_thread=False`.
- **`accesibilidad/navegador.py`**: nueva `auditar_pagina_abierta(page, ...)` (audita el estado actual de una página ya abierta, para aplicaciones de una sola página con sesión) y `Navegador.pagina(..., ignorar_errores_https=True)` para servidores de prueba locales. Dos correcciones a la compuerta descubiertas con la interfaz: con una CSP estricta la prueba de espaciado (1.4.12) inyectaba un `<style>` que el navegador rechazaba y «pasaba» sin aplicarse (ahora usa una hoja construida por script y avisa si no pudo aplicarla), y axe-core se carga con `evaluate` en vez de `add_script_tag`; los campos de fecha nativos ya no se reportan como «sin foco visible» en la parada del botón del calendario.

- **NFR-03 — Accesibilidad (WCAG 2.1 AA)** (`accesibilidad/`, `documentos_clinicos/html_export.py`):
  - cuando se hizo esta historia el proyecto no tenía frontend propio (ahora existe `frontend/`, que pasa por la misma compuerta): se construyó una compuerta reutilizable y se aplicó a lo que existía. `contraste.py` (razones WCAG), `auditoria_html.py` (auditor estático de HTML/CSS y contraste de tokens en claro, oscuro del sistema y oscuro manual), `pdf.py` (`auditar_pdf`: título, idioma, marcadores, texto real, contraste contra el fondo real, tamaño, etiquetado) y `navegador.py` (Chromium opcional: contraste calculado, reflujo a 320 px, espaciado, teclado, axe-core);
  - `python -m accesibilidad html|pdf|sistema [--navegador]`, con código de salida 1 si hay errores;
  - **tablero ADM-02 corregido**: texto atenuado de 3.4:1 a 5.1:1, bordes y segmentos con contraste no textual, tablas con título, una parada de tabulación por gráfico con flechas, tooltip descartable (`Esc`) y alcanzable, «No disponible» legible por lector de pantalla, reflujo a 320 px, salto al contenido, foco visible, controles de 40 px;
  - `GET /metricas/panel` responde con una página HTML que explica el error (y deja corregirlo) cuando el periodo no es válido; `GET /metricas` sigue devolviendo JSON;
  - **DOC-02**: el PDF declara idioma y título visible, tiene marcadores por sección, contraste corregido (pie de 4.48:1 a 7:1) y letra más grande; no puede ser PDF etiquetado (reportlab) y se informa como aviso. Nueva alternativa accesible `exportar_a_html` / `renderizar_html` desde el mismo `DocumentoExportable`;
  - **no hay prueba con lectores de pantalla ni con personas usuarias**: el protocolo manual y la declaración de conformidad (honesta) están en el doc; Swagger UI y OHIF son de terceros y no se auditan.
  - Ver `docs/accesibilidad.md`.
- **ADM-02 — Tablero de métricas de uso** (`administracion/metricas_uso.py`, `panel_metricas.py`):
  - adopción (usuarios clínicos activos, pacientes atendidos, uso de funciones de IA), tiempo ahorrado, alertas generadas y aceptación de las recomendaciones de IA, siempre comparados con el periodo anterior y con serie semanal;
  - solo agregados institucionales: ninguna estructura de salida ni función admite datos o filtros por persona; la aceptación se muestra como distribución con su nota de interpretación y se suprime con menos de 30 decisiones o 5 médicos (también el desglose por rol en grupos pequeños);
  - un dato no disponible es `null`/"—", nunca cero; el tiempo ahorrado es una estimación en rango con supuestos a la vista (`coeficientes_tiempo.yaml`, sin medir: calibrar con un estudio propio);
  - ver el tablero no cuenta como uso del sistema; las bases clínicas se leen en solo-lectura;
  - solo el nuevo rol `director_medico` (`Accion.VER_METRICAS_USO`); cada consulta y cada intento denegado queda en AUD-01 (`TipoAccion.CONSULTAR_METRICAS`), y sin traza no se entregan datos;
  - `GET /metricas` (JSON) y `GET /metricas/panel` (HTML autocontenido: SVG propio, claro/oscuro, tabla equivalente por gráfico, sin recursos externos) en `administracion.api`.
  - Cambios aditivos en `seguridad/` (`Rol.DIRECTOR_MEDICO`, `Accion.VER_METRICAS_USO`) y `auditoria/` (`TipoAccion.CONSULTAR_METRICAS`).
  - Ver `docs/administracion_metricas.md`; demo con datos sintéticos: `python -m administracion.demo_metricas [--pequeno]`.
- **ADM-01 — Gestión de usuarios, roles y permisos** (`administracion/`):
  - alta, consulta, listado con filtros, edición, cambio de rol, baja lógica (desactivar/reactivar) y restablecimiento de contraseña;
  - solo el nuevo rol `administrador` (`Accion.GESTIONAR_USUARIOS`); el actor se relee de la base en cada operación;
  - salvaguardas: nadie cambia su propio rol ni se desactiva, nunca se pierde el último administrador activo, no hay borrado;
  - cada operación y cada intento denegado queda en AUD-01 (`TipoAccion.GESTIONAR_USUARIOS`), sin contraseñas ni hashes; el cambio y su auditoría se confirman juntos;
  - permisos = los del rol (`PERMISOS_POR_ROL`, `matriz_de_permisos`); tabla lateral `perfiles_usuario`;
  - API `uvicorn administracion.api:app` con HTTP Basic sobre el login de SEC-01, y `python -m administracion crear-admin` para el primer administrador.
  - Cambios aditivos en `seguridad/` (`Rol.ADMINISTRADOR`, `permisos_del_rol`, `insertar_usuario`, `establecer_contrasena`) y `auditoria/`.
  - Ver `docs/administracion_usuarios.md`; demo: `python -m administracion.demo`.
- **HC-03 — Integración de imágenes diagnósticas (DICOM/PACS)** (`historia_clinica/imagenes_pacs.py`):
  - cliente DICOMweb (QIDO-RS) con sesión inyectable (`FuenteDICOMweb`) y contrato `FuentePACS`;
  - visor de terceros incrustado por plantilla de URL (`COPILOTO_VISOR_URL`) en vez de un visor propio (evaluación en el doc);
  - cada estudio se enlaza a su informe de `imagenologia` solo cuando el enlace es único;
  - verificación de identidad por estudio (PatientID + nombre); los de otro paciente se descartan;
  - sin PACS o sin conexión: aviso explícito (`503` en el visor), última sincronización y bitácora `consultas_pacs`.
  - Tablas `estudios_pacs` y `consultas_pacs` (aditivas). Endpoints `GET /pacientes/{id}/imagenes`, `.../imagenes/{study_uid}/visor` y `.../imagenes/consultas`.
  - Autenticación Bearer o HTTP Basic hacia el PACS (`COPILOTO_PACS_USUARIO`/`COPILOTO_PACS_PASSWORD`).
  - Ver `docs/historia_clinica_imagenes_pacs.md`; demos: `python -m historia_clinica.demo_imagenes_pacs` (PACS simulado) y `python -m historia_clinica.demo_orthanc` (Orthanc + OHIF reales en Docker).

## [Sin versionar] — Rama `laboratory-integration`

### Añadido

- **HC-02 — Integración de resultados de laboratorio** (`historia_clinica/laboratorios.py`):
  - registro manual con doble validación (identificación + nombre);
  - alertas por valor crítico, con rangos configurables en `rangos_criticos_laboratorio.yaml`;
  - conflictos de mismo marcador y momento, sin sobrescribir ninguno de los resultados;
  - tendencias por marcador, agrupando alias y separando unidades.
  - Ver `docs/historia_clinica_laboratorios.md`.
- **HC-04 — Integración de biopsias y biomarcadores** (`historia_clinica/biopsias_biomarcadores.py`):
  - episodios diagnósticos, y biopsias vinculadas a ellos;
  - registro de biomarcadores con validación estricta contra `catalogo_biomarcadores.yaml` y doble ingreso;
  - biomarcadores accionables destacados como información clave, con su variable escrita en `datos_clinicos_estructurados` para TX-01;
  - los importados quedan pendientes hasta que el oncólogo los confirma.
  - Ver `docs/historia_clinica_biomarcadores.md`.
- `cbioportal.importador.vincular_biopsias`: los pacientes importados quedan con episodio, biopsias por muestra y biomarcadores accionables pendientes de confirmación.
- `patients/expediente.py`: puente entre la base de `patients` y el expediente clínico.
- **Endpoints nuevos:**
  - laboratorios, interfaz HL7, tendencias, alertas y conflictos;
  - episodios, biopsias y biomarcadores.
- **Resumen 360:**
  - alertas de laboratorio crítico, de conflicto y de biomarcadores por confirmar;
  - campo `biomarcadores_clave`;
  - el diagnóstico se toma del episodio cuando no hay otro registrado.
- **Demo** (`python -m patients.demo`): opciones 5 (laboratorios), 6 (alertas y conflictos) y 7 (biopsias y biomarcadores).
- **TX-01:** `obtener_datos_paciente` incluye `biomarcadores_clave`. Los pendientes se marcan como no confirmados y no entran en `facts_clinicos`.

- **TX: el agente puede guardar datos con aprobación del oncólogo.** Tools `registrar_datos_clinicos_paciente` y `registrar_conciliacion_medicamentos` (`tx_clinica/tools/registro_tools.py`):
  - están bajo el middleware de aprobación humana: el grafo se pausa y nada se guarda sin aprobar;
  - validan contra `guidelines/*/variables.yaml` antes de escribir;
  - excluyen los biomarcadores (van por HC-04);
  - firman con el oncólogo de la sesión.

  Con esto, el flujo TX-01 → TX-03 → TX-04 funciona completo desde el chat. Ver `docs/tx_clinica.md`.

- `demo_laboratorios_biomarcadores.py`: demo guiada de HC-02 y HC-04.
  - Ejecuta sola el recorrido, verificando cada criterio de aceptación.
  - Después abre el menú de la demo de pacientes para seguir interactuando.
  - Trabaja sobre una copia de la base, restablecida al estado recién importado (`restablecer_estado_inicial`), y levanta su propia API. Ver `docs/PACIENTES_DEMO.md`.

### Cambiado

- **HC-01:**
  - los laboratorios importados (FHIR, HL7, cBioPortal) pasan por HC-02 en la misma transacción;
  - los mensajes con laboratorios exigen el nombre del paciente (doble validación);
  - la hora de la toma (OBX-14/OBR-7, `effectiveDateTime`) se conserva.
- `privacidad.tratamiento_datos`: las tablas nuevas forman parte de la información del titular.

### Corregido

- `tx_clinica.observability`: la máscara de datos del paciente (`LANGFUSE_MASK_DATOS_PACIENTE`) no se aplicaba cuando el agente se construía sin haber cargado antes el `.env`, porque `construir_agente` inicializaba Langfuse antes de leerlo. En ese caso el nombre del paciente llegaba a Langfuse sin redactar. Ahora `inicializar_langfuse` carga el `.env` primero. Verificado con una traza real.

- `completar_datos_paciente_y_recomendar` (TX-01): la descripción de la herramienta pedía "solo las variables preguntadas", y `gpt-6-luna` la seguía al pie de la letra. Si el oncólogo daba seis datos en un mensaje, el modelo pasaba dos y volvía a preguntar. Ahora pide pasar todas las variables que el oncólogo ya dio, y aclara que los valores no se guardan entre llamadas. Sigue prohibido inventar valores.

- `tx_clinica.conversacion`: con `gpt-6-luna` el contenido del mensaje final es una lista de bloques. Ahora `RespuestaAgente.texto` es siempre un `str` (se usa `.text`), y la traza de Langfuse registra el texto en lugar de la lista. Ver `docs/llm_openai.md`.

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
- Nuevo componente `expediente/`: base de datos SQLite con
  datos sintéticos (pacientes, consultas, laboratorios, imagenología,
  biomarcadores) y un adaptador (`adapters.construir_contexto_clinico`)
  que conecta esos datos con `ia_clinica.notes` para poder generar
  borradores de nota a partir de una consulta guardada, con trazabilidad
  hasta la fila exacta de la base de datos. Ver
  `docs/expediente.md`.
- Pruebas en `tests/expediente/` (esquema, seed, repository,
  adaptador e integración end-to-end con IA-02).
- `expediente`: nuevas consultas a nivel de todo el paciente
  (`laboratorios_de_paciente`, `imagenologia_de_paciente`,
  `biomarcadores_de_paciente`) y `obtener_hallazgos_de_paciente` (modelo
  `HallazgoClinico`), para historias que necesitan combinar todo el
  expediente disponible, no una sola consulta.
- Nuevo componente `dx_clinica/` que implementa **DX-02 — Apoyo al
  diagnóstico diferencial**: lista priorizada de alternativas
  diagnósticas sustentadas en hallazgos reales del expediente
  (`expediente`) y en evidencia trazable leída de
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
- Nuevo adaptador `expediente.adapters.construir_contexto_resumen_caso`,
  que combina `diagnostico_principal`/`estadio` del paciente con los
  mismos hallazgos que ya reúne `obtener_hallazgos_de_paciente` (DX-02)
  en un `CaseSummaryContext` para IA-04.
- Pruebas en `tests/ia_clinica/summary/` (modelos, prompts/cliente de
  referencia, y los dos criterios de aceptación de IA-04 más la regla de
  no-alucinación), y casos añadidos a
  `tests/expediente/test_adapters.py` para el nuevo adaptador.
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
  (`expediente`), usando un catálogo versionado de sistemas de
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
  `expediente`), "vigente" = la confirmación más reciente, y
  ninguna validación de concordancia — `confirmar_estadificacion` nunca
  compara el estadio del médico contra la propuesta de EST-01 para aceptarla o
  rechazarla, solo para calcular `difiere_de_sugerencia` (insumo directo de
  AUD-02) y dejar un snapshot de auditoría de qué sugería el sistema.
  `obtener_estadificacion_vigente` resuelve qué mostrar: la confirmación del
  médico si existe, o la propuesta del sistema rotulada como apoyo si no.
  Pruebas en `tests/estadificacion/test_confirmacion.py`; demo ampliada en
  `estadificacion/demo.py`. Ver `docs/estadificacion.md`.
- `expediente/seed.py`: nuevo paciente sintético 6
  (`Diana Sofía Restrepo`, NSCLC temprano) con hemoglobina en dos consultas
  (para IA-06) y T/N/M clínico completo (para EST-01); variables `clinical_m_status`
  añadidas a María y T/N/M a Roberto. Solo son filas nuevas: no se modificó
  ningún registro sintético existente. Se actualizaron dos aserciones de
  `tests/expediente/test_db_y_seed.py` que fijaban el número exacto de
  pacientes/consultas del seed (ya desactualizadas en `main`) para fijar el
  mínimo y las invariantes en su lugar.

- Nuevo `documentos_clinicos/carga_documentos.py` que implementa
  **DOC-01 — Carga de documentos clínicos**: `cargar_documento_clinico`
  valida que el paciente exista (contra `expediente`, que
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
  paciente directamente desde `expediente`
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
  `expediente`:
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
- Modo índice (`cbioportal/indice.py`, `python -m cbioportal --indice`):
  todos los pacientes de un estudio con datos básicos en segundos (13.159 de
  mama y pulmón en 4 s) y detalle bajo demanda al abrir el paciente en la
  API (`GET /pacientes/{id}` y `/resumen-360`), activado con
  `COPILOTO_EXPEDIENTE_DB`. Si cBioPortal no responde, el 360 muestra los
  datos básicos y el fallo queda registrado.
- `historia_clinica.integracion_externa.registrar_fallo_sincronizacion`.
- Pruebas en `tests/cbioportal/` (sin red).

## [Sin versionar] — Modelo GPT de OpenAI en lugar de Ollama

### Cambiado

- El LLM real del proyecto pasa de un modelo local en Ollama a un modelo GPT
  de OpenAI (por defecto `gpt-6-luna`, configurable con `OPENAI_MODEL`).
  La llave va en `OPENAI_API_KEY` del `.env` de la raíz, que no se versiona.
  Ver `docs/llm_openai.md`.
- `ia_clinica.notes.llm_client.OpenAILLMClient` reemplaza a
  `OllamaLLMClient` (IA-02, IA-03 e IA-04). Mismo contrato `LLMClient`, JSON
  garantizado por la API y `esta_disponible()` sin generar texto.
- `tx_clinica/agent.py` usa `ChatOpenAI` en vez de `ChatOllama`.
- `requirements.txt`: `langchain-openai`, `openai` y `python-dotenv` en vez
  de `langchain-ollama`.

### Añadido

- `core/llm_config.py`: llave, modelo y tiempo de espera compartidos, leídos
  del `.env`.
- Pruebas en `tests/ia_clinica/notes/test_openai_llm_client.py` (sin red).

### Eliminado

- `OllamaLLMClient`, `OllamaConnectionError` y sus pruebas.

## [Sin versionar] — Demo unificada

### Añadido

- `demo.py`: todo lo implementado con un solo comando (`python demo.py`),
  en 12 secciones con pausa entre cada una; `--solo`, `--sin-pausa`,
  `--sin-red` y `--lista`. Reutiliza las demos de cada historia y agrega
  guiones fijos para IA-01/IA-06, TX y NFR-06. Corre en bases en memoria o
  temporales. Ver `docs/DEMO_UNIFICADA.md`.

### Cambiado

- `ia_clinica/summary/demo.py`: con un modelo real, una sección sin citas
  válidas se informa como faltante en vez de detener el demo con `assert`.

## [Sin versionar] — Solo base de datos real (sin datos simulados)

### Cambiado

- La aplicación ya no usa datos inventados: la API de pacientes no carga
  datos de ejemplo al arrancar, el agente de tratamiento abre la base real
  (`data/copiloto.db`, o `COPILOTO_EXPEDIENTE_DB`) y los datos sintéticos
  quedan solo en las pruebas (`tests/datos_sinteticos.py`,
  `tests/patients/datos_prueba.sql`). Las pruebas nunca abren la base real.
- `historia_clinica_mock` pasa a llamarse `expediente` (esquema y lecturas,
  sin datos). `MockSQLiteClinicalRepository` → `SQLiteClinicalRepository`.
- `demo.py` corre sobre pacientes reales de cBioPortal: prepara la base si
  falta y trabaja sobre una copia. `demo_ia01.py` y `demo_tx.py` también usan
  la base real. Se eliminaron las demos por historia que dependían de datos
  sintéticos (sus casos están en `demo.py --solo <sección>`).
- Modelo por defecto `gpt-6-luna`.

### Añadido

- `expediente/registro.py`: el oncólogo registra consultas, variables
  clínicas y comorbilidades (lo que cBioPortal no trae).
- `patients.medicacion_actual.registrar_conciliacion`.
- TX-01: si la guía aplica pero ningún régimen se puede evaluar, se informan
  las variables que faltan (`variables_faltantes_para_candidatos`).
- IA-01 reconoce CEA, CA 15-3, CA 19-9, KRAS, ALK, ROS1, BRAF, MET, RET,
  PIK3CA, TMB, MSI y receptores hormonales.
- Los hallazgos de paciente (DX-02, IA-04, IA-05) incluyen los antecedentes
  importados (tratamientos, cirugías, radioterapia).

### Corregido (encontrado al usar datos reales)

- cBioPortal: HR/HER2 "No" de MSK-CHORD se registraba como negativo y se
  derivaba "triple negativo"; es "sin antecedente de positivo" (hay
  pacientes así tratadas con trastuzumab u hormonoterapia). Ahora queda
  faltante.
- cBioPortal: el texto de imagen empezaba con "no es el texto original", y
  ese "no" hacía que DX-02 nunca detectara una progresión real.
- DX-02: cualquier laboratorio fuera de rango (p. ej. CEA) sustentaba
  "toxicidad hepática"; ahora exige un laboratorio hepático alterado.
- IA-06: la palabra "paciente" (y "cBioPortal") en una pregunta se tomaba
  como mención de otro paciente con los nombres genéricos de cBioPortal.
