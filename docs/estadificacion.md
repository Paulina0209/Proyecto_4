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

## EST-03 — Manejo de la estadificación incompleta

`estadificacion/incompleta.py` es una **capa de lectura** sobre la
`PropuestaEstadificacion` de EST-01 (mismo patrón que `dx_clinica/incertidumbre.py`
respecto a DX-02): no la modifica ni asume valores.

`analizar_estadificacion_incompleta(propuesta)` devuelve un
`AnalisisEstadificacionIncompleta` con:

- `componentes_determinados` / `componentes_indeterminados` — cada
  `ComponenteIndeterminado` identifica explícitamente el componente (T/N/M), su
  variable, el motivo (sin dato vs. valor no interpretable) y la
  `informacion_requerida` para poder determinarlo (texto que vive en
  `ComponenteDef`, por lo que depende del sistema/versión).
- `estadios_posibles` — se obtiene con `estadios_candidatos`, que explora los
  valores que podrían tomar los componentes pendientes y recoge los grupos
  distintos que resultan. **Nunca asume un valor**: si la información conocida ya
  fija un único grupo (p. ej. `M1` → IV por comodín), la tupla trae un elemento.
- `rango_legible` — "entre X y Y (alternativas: …)" cuando hay más de un estadio
  posible; se comunica el rango sin elegir uno.
- `estadio_confirmado` — `True` solo si hay un único estadio posible **y** ningún
  componente pendiente. Si falta información, nunca se presenta un estadio
  definitivo como confirmado.

Regla de negocio: el sistema no asume valores de T/N/M cuando faltan; los
componentes indeterminados quedan marcados como tales.

## Datos de prueba (EST-03)

- Laura (melanoma): `pT3 N0` documentados, `clinical_m_status` pendiente →
  estadios posibles `II` (M0) o `IV` (M1), rango comunicado, sin estadio
  confirmado.
- Patricia (RCC): sin ningún T/N/M → los tres componentes indeterminados.

## Pruebas y demo

- `tests/estadificacion/test_staging_systems.py`, `test_builder.py` y
  `test_incompleta.py`: cubren los criterios de aceptación de EST-01 y EST-03 y
  la regla de "solo criterios del sistema seleccionado".
- `python -m estadificacion.demo`.
