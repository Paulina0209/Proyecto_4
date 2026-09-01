# EST-01 — Estadificación automática asistida

## Historia

Como oncólogo, quiero que el sistema proponga un estadio clínico con base en los
datos disponibles del paciente y el sistema de estadificación aplicable, para
agilizar esta etapa y facilitar la verificación del estadio.

## Componente

Nuevo componente `estadificacion/`, en el mismo estilo que `dx_clinica/` y
`tx_clinica/`:

- `estadificacion/staging_systems.py`: **catálogo versionado** de sistemas de
  estadificación. Cada `SistemaEstadificacion` declara `id` (p. ej. `AJCC`),
  `version` (p. ej. `8`), `fuente`, los `cancer_types` a los que aplica, los
  `componentes` (T/N/M) con la variable del expediente de la que sale cada uno,
  y una `tabla_grupos` `((T, N, M) -> grupo)` con comodín `"*"`. `sistema_para_cancer`
  resuelve el sistema aplicable mediante una tabla explícita (nunca por
  emparejamiento difuso); devuelve `None` si no hay uno registrado.
- `estadificacion/models.py`: `ComponenteEstadio` y `PropuestaEstadificacion`
  (más el `DISCLAIMER` fijo).
- `estadificacion/builder.py`: `proponer_estadificacion(conn, paciente_id)` —
  punto de entrada.

## Cómo construye la propuesta

1. Lee la variable estructurada `cancer_type` del expediente
   (`historia_clinica_mock`). Sin ella → propuesta vacía con `cancer_type` como
   dato faltante.
2. Selecciona el sistema con `sistema_para_cancer`. Sin sistema → propuesta vacía
   explicando por qué (no se aplican criterios que no corresponden).
3. **Solo** recorre las variables que ese sistema/versión define. Para cada
   componente toma el registro estructurado más reciente de esa variable y
   construye un `ComponenteEstadio` con `criterio_aplicado` (la descripción del
   sistema), `fundamento` (de qué `dato-<id>`, consulta y fecha salió) y
   `fuente_ids` trazables. Variable ausente → a `datos_faltantes`, sin inventar
   un valor.
4. Normaliza cada valor a su familia (`cT2` → `T2`, `pT4b` → `T4`) y aplica
   `tabla_grupos` para el estadio global. Si falta un componente o la
   combinación no está en la tabla → `estadio_global = None` con el motivo en
   `fundamento_global` (el manejo fino de estadificación incompleta es EST-03).

## Reglas de negocio

- La estadificación es **una propuesta de apoyo a la decisión** y debe validarla
  el profesional (`DISCLAIMER`, `es_apoyo_a_decision`).
- Solo se usan criterios del sistema y versión seleccionados para el tipo de
  cáncer correspondiente. Cada resultado conserva `sistema_id` + `sistema_version`
  + `sistema_fuente` + `nota_alcance`.

## Nota de alcance

Las `tabla_grupos` son un **subconjunto ilustrativo mínimo** de AJCC 8ª, suficiente
para probar EST-01 de punta a punta contra los pacientes sintéticos. No reproducen
la edición completa y **no están validadas clínicamente** — mismo criterio de
honestidad que `dx_clinica/knowledge_base.py`.

## Datos de prueba

- María (mama): `cT2 N0 cM0` → estadio `IIA`.
- Diana (NSCLC temprano, paciente 6): `cT1 N0 cM0` → estadio `I`.
- Roberto (NSCLC): `cT2 N1 cM1` → estadio `IV` (comodín de `M1`).
- Patricia (RCC): sin T/N/M estructurado → propuesta con los tres componentes
  como datos faltantes, sin estadio global.

## Pruebas y demo

- `tests/estadificacion/test_staging_systems.py` y `test_builder.py`: cubren los
  cinco criterios de aceptación y la regla de "solo criterios del sistema
  seleccionado".
- `python -m estadificacion.demo`.
