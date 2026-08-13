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

### Notas

- No se modificó ni se movió ningún archivo existente de `guidelines/`,
  `docs/guidelines/` ni `tests/guidelines/`.
- Se detectó (pero no se modificó) que las pruebas existentes en
  `tests/guidelines/` importan `cdss.core.engine`, un paquete que todavía
  no existe en este repositorio (no hay carpeta `src/cdss` ni `core/`).
  Esas pruebas ya fallaban en `main` antes de esta rama por este motivo;
  queda fuera del alcance de IA-02 resolverlo.
