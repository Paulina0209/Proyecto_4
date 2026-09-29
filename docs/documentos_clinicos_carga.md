# DOC-01 — Carga de documentos clínicos

## Alcance de esta implementación

Este documento describe el diseño de `documentos_clinicos.carga_documentos`,
que implementa la historia de usuario **DOC-01** del backlog (épica
Gestión Documental):

> As an oncologist, I want to upload clinical documents (PDF, images,
> DICOM) to the patient's clinical record, so that I can centralize all
> documentation.

Criterios de aceptación:

> Given a clinical document in a supported format, when I upload it to a
> patient's clinical record, then it is correctly associated with the
> patient and visible in their document history.
>
> Given an unsupported file format, when I attempt to upload it, then
> the system rejects the file and displays a clear message indicating
> the expected format.

Datos de planeación: Épica Gestión Documental, Must Have, 5 story
points, dependencia **PAC-01**, MVP: Sí.

Nota sobre la dependencia formal: PAC-01 ("registrar un nuevo paciente")
no está implementada como un componente propio en este repositorio; el
registro de pacientes lo cumple, en la práctica, la tabla `pacientes` de
`expediente` — la misma que ya usan como referencia todas las
historias anteriores (DX-01, DX-02, IA-04, DOC-02). Por eso
`cargar_documento_clinico` recibe una conexión a `expediente`
y valida ahí que el paciente exista antes de aceptar cualquier
documento, exactamente igual que
`documentos_clinicos.adaptadores.expediente_completo_a_documento_exportable`
(DOC-02) en el mismo paquete.

## Por qué es una tabla propia, de solo-inserción

`documentos_clinicos_cargados` vive en su propia base SQLite
(`carga_documentos.crear_conexion`), separada de `expediente`
— mismo patrón que ya usa `dx_clinica/juicio_clinico.py` para DX-03: una
tabla de solo-inserción (append-only), donde un documento cargado nunca
se sobreescribe ni se reemplaza en su lugar. Esto hace que "el historial
de documentos del paciente" (AC1) sea, literalmente, listar todas las
filas de ese paciente en orden — no existe ninguna noción de "versión
actual" que oculte una carga anterior, ni ninguna operación de "editar"
o "eliminar" un documento ya cargado.

El contenido binario real (los bytes del PDF/imagen/DICOM) se guarda en
disco, no en la base de datos: SQLite puede almacenar blobs, pero
guardar archivos potencialmente grandes (sobre todo DICOM) como filas de
una tabla no es el mismo patrón de almacenamiento que ya usa el resto
del proyecto para datos clínicos, y complica innecesariamente cualquier
lectura/visualización futura del archivo. La tabla solo guarda la
`ruta_almacenamiento` resultante, junto con los metadatos necesarios
para el historial.

## Por qué el nombre de archivo en disco nunca es el nombre original

`cargar_documento_clinico` guarda cada archivo con un nombre generado
(`uuid4().hex` + extensión), nunca con `nombre_archivo` tal como lo
entregó quien lo cargó. Dos razones concretas:

- **Colisiones**: dos documentos distintos (de pacientes distintos, o
  del mismo paciente en momentos distintos) perfectamente pueden
  llamarse igual (`informe.pdf`); un nombre generado nunca choca.
- **Seguridade de la ruta**: el nombre original nunca se usa para
  construir una ruta de archivo real, así que no hay ningún vector de
  "path traversal" (`../../etc/passwd`) a través de un nombre de archivo
  malicioso o mal formado. El nombre original se conserva tal cual, pero
  solo como un dato de texto (`nombre_archivo_original`) para mostrarse
  en el historial — nunca se interpreta como una ruta.

Cada paciente tiene su propio subdirectorio
(`<directorio_almacenamiento>/paciente_<id>/`), para que el
almacenamiento en disco quede organizado de la misma forma en que se
consulta (por paciente), aunque la tabla SQLite ya sea la fuente de
verdad real para localizar cualquier archivo.

`directorio_almacenamiento` es siempre un parámetro explícito, nunca una
ruta fija en el código — permite que las pruebas usen un directorio
temporal (`tmp_path`) sin tocar disco real fuera de eso, y que un
despliegue real decida dónde vivir sin cambiar código.

## Cómo se decide si un formato es soportado

`FORMATOS_SOPORTADOS` es un catálogo explícito de extensión → 
(tipo de documento, validador de firma binaria): `.pdf` → PDF, `.jpg` /
`.jpeg` / `.png` → Imagen, `.dcm` → DICOM. Igual que los catálogos
curados de `dx_clinica` (perfiles de sospecha diagnóstica, catálogo de
estudios), ampliar los formatos soportados es agregar una entrada aquí,
no tocar la lógica de `cargar_documento_clinico`.

## Por qué no basta con la extensión: verificación de la firma binaria real

Confiar únicamente en la extensión del nombre de archivo para decidir
"esto es un PDF" es aceptar una afirmación sin verificarla — exactamente
lo que el resto del proyecto rechaza sistemáticamente (trazabilidad de
`ia_clinica`, evidencia citable de `dx_clinica`, disclaimers explícitos
en cada salida generada). Un archivo de texto renombrado por error (o a
propósito) a `informe.pdf` tiene la extensión correcta, pero no es
genuinamente un PDF.

Por eso, además de la extensión, `cargar_documento_clinico` verifica la
**firma binaria real** de los primeros bytes del contenido:

| Formato | Firma verificada |
|---|---|
| PDF | los primeros bytes son literalmente `%PDF-` |
| JPEG | los primeros 3 bytes son `\xFF\xD8\xFF` |
| PNG | los primeros 8 bytes son la firma estándar de PNG |
| DICOM | el preámbulo de 128 bytes está seguido literalmente de `DICM` (offset 128-132), como exige el estándar DICOM "Parte 10" |

Si la extensión es reconocida pero la firma no coincide, se lanza
`ContenidoNoCoincideConFormatoError` — un error explícitamente distinto
de `FormatoNoSoportadoError`, porque la causa del rechazo es diferente
(el formato declarado sí es válido; el problema es que el contenido no
es genuinamente de ese tipo) y quien recibe el mensaje se beneficia de
saber cuál de las dos cosas pasó.

## Cómo se satisface cada criterio de aceptación

| Criterio de aceptación | Mecanismo en el código |
|---|---|
| Con un formato soportado, el documento queda asociado al paciente y visible en su historial | `cargar_documento_clinico` valida que el paciente exista (`PacienteNoEncontradoError` si no), guarda el archivo en disco e inserta una fila con `paciente_id`; `listar_documentos_de_paciente` devuelve exactamente las filas de ese paciente, del más reciente al más antiguo. |
| Con un formato no soportado, se rechaza con un mensaje claro que indica el formato esperado | Si la extensión no está en `FORMATOS_SOPORTADOS`, se lanza `FormatoNoSoportadoError` con un mensaje que enumera explícitamente los formatos aceptados (`PDF (.pdf), Imagen (.jpeg/.jpg/.png), DICOM (.dcm)`), generado a partir del catálogo real — nunca un mensaje genérico ("formato inválido") que obligue a adivinar qué sí se acepta. |

## Validaciones básicas de forma (no negociables, aunque no estén en el AC)

Igual que el resto del proyecto (`autor` en `dx_clinica.juicio_clinico`,
identificador de médico en la aprobación de `ia_clinica.review`),
`cargado_por` no puede estar vacío: cargar un documento a un expediente
clínico es una acción con autoría, no una operación anónima. Tampoco se
acepta un `contenido` vacío (`DocumentoInvalidoError` en ambos casos) —
nunca se llega siquiera a revisar el formato de un archivo sin
contenido real.

## Fuera de alcance de esta historia

- **Visualización del documento** (renderizar el PDF, ver la imagen,
  abrir el estudio DICOM en un visor): esta historia solo cubre la carga
  y el historial; `leer_contenido_documento` devuelve los bytes crudos,
  pero no hay ningún visor en este repositorio.
- **Validación clínica del contenido de un DICOM** (por ejemplo, que los
  metadatos DICOM correspondan al paciente correcto): la verificación de
  formato de esta historia es puramente estructural (¿es un DICOM real?),
  no clínica.
- **Cuotas de almacenamiento, compresión o límites de tamaño de archivo**:
  no se mencionan en el criterio de aceptación; no hay ningún límite de
  tamaño implementado.
- **Eliminar o reemplazar un documento ya cargado**: por diseño (tabla
  de solo-inserción), no existe esa operación — un documento incorrecto
  se corrige cargando uno nuevo, conservando el historial completo.

## Componentes

- `carga_documentos.py`: `FORMATOS_SOPORTADOS`, `DocumentoClinicoCargado`,
  `DocumentoInvalidoError`, `FormatoNoSoportadoError`,
  `ContenidoNoCoincideConFormatoError`, `cargar_documento_clinico(...)`,
  `listar_documentos_de_paciente(...)`, `leer_contenido_documento(...)`.
- `schema_documentos_clinicos.sql`: esquema de la tabla de solo-inserción
  `documentos_clinicos_cargados`.
- Demo: `python demo.py --solo doc` (demo unificada sobre pacientes reales de cBioPortal; ver `docs/DEMO_UNIFICADA.md`): carga el PDF exportado de un
  paciente real y rechaza un `.txt`.

## Cómo probarlo

```
python demo.py --solo doc
```

Y las pruebas automatizadas:

```
pytest tests/documentos_clinicos/test_carga_documentos.py -v
```
