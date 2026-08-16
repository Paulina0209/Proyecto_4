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

### Notas

- No se modificó ni se movió ningún archivo existente de `guidelines/`,
  `docs/guidelines/` ni `tests/guidelines/`.
- Se detectó (pero no se modificó) que las pruebas existentes en
  `tests/guidelines/` importan `cdss.core.engine`, un paquete que todavía
  no existe en este repositorio (no hay carpeta `src/cdss` ni `core/`).
  Esas pruebas ya fallaban en `main` antes de esta rama por este motivo;
  queda fuera del alcance de IA-02 resolverlo.
