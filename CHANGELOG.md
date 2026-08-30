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

### Notas

- No se modificó ni se movió ningún archivo existente de `guidelines/`,
  `docs/guidelines/` ni `tests/guidelines/`.
- Se detectó (pero no se modificó) que las pruebas existentes en
  `tests/guidelines/` importan `cdss.core.engine`, un paquete que todavía
  no existe en este repositorio (no hay carpeta `src/cdss` ni `core/`).
  Esas pruebas ya fallaban en `main` antes de esta rama por este motivo;
  queda fuera del alcance de IA-02 resolverlo.
