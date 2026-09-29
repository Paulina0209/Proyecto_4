# DOC-02 — Exportación de expediente médico a PDF

## Alcance de esta implementación

Este documento describe el diseño de `documentos_clinicos.pdf_export` y
`documentos_clinicos.adaptadores`, que implementan la historia de
usuario **DOC-02** del backlog (épica Gestión Documental):

> As an oncologist, I want to export a summary or clinical record as a
> PDF, so that I can share it with the patient, another specialist, or
> the insurance provider.

Descripción: exportar el resumen del caso o el expediente clínico
completo como PDF para compartirlo externamente.

Criterio de aceptación:

> Dado un expediente clínico con información suficiente, cuando
> solicito exportar el resumen, entonces recibo un PDF con formato
> profesional listo para compartirse.

Datos de planeación: Épica Gestión Documental, Should Have, 5 story
points, dependencias **HC-06** y **TX-04**, no MVP.

Nota sobre las dependencias formales: HC-06 (expediente clínico
integrado) ya está cubierto, en el alcance de este repositorio, por
`expediente`. TX-04 (una historia de tratamientos que
todavía no se ha implementado en este repositorio) no es una
dependencia dura del código de esta historia: el renderizador y los dos
adaptadores no leen absolutamente nada de `tx_clinica`. La dependencia
declarada en el backlog es más bien conceptual (un plan de tratamiento
sería, con el tiempo, contenido más que exportar), no algo que el código
de DOC-02 necesite en tiempo de ejecución.

## Por qué la historia se separa en dos capas independientes

La historia permite exportar "**el resumen del caso o** el expediente
completo" — dos fuentes de contenido completamente distintas, que además
ya existen en el repositorio en formas muy distintas entre sí: `CaseSummary`
(IA-04, con secciones redactadas por un LLM y trazabilidad a fragmentos
fuente) y las tablas normalizadas de `expediente` (sin ningún
LLM involucrado). En vez de escribir dos funciones "exportar X a PDF"
que dupliquen todo el código de maquetado, el diseño separa:

- `pdf_export.py`: el **renderizador**, con un modelo genérico
  (`DocumentoExportable` → `SeccionDocumento` → `BloqueTexto` /
  `BloqueTabla`) que no sabe nada de dónde vino el contenido. Es el
  único archivo que importa `reportlab`.
- `adaptadores.py`: dos funciones puras, cada una traduciendo **una**
  fuente real del repositorio a ese modelo genérico. No comparten
  código entre sí (más allá de los tipos del modelo genérico) porque no
  hay nada real que compartir: una traduce cuatro secciones ya
  redactadas, la otra construye tablas directamente desde filas SQL.

`pdf_export.py` no importa nada de `adaptadores.py` ni de
`ia_clinica`/`expediente`; la dependencia va siempre en un
solo sentido. Esto permite que el renderizador sirva, sin cambios, para
cualquier documento clínico exportable que se agregue en el futuro (no
solo los dos que cubre esta historia), y que cada adaptador se pueda
probar sin tener que generar un PDF real.

## El modelo genérico: por qué existen `BloqueTexto` y `BloqueTabla`

El resumen de caso es, en esencia, texto corrido por sección. El
expediente completo tiene secciones donde una tabla es claramente más
legible que un párrafo (laboratorios, imagenología, biomarcadores,
comorbilidades: listas de filas con las mismas columnas). En vez de
forzar todo a texto (perdiendo legibilidad) o todo a tablas (raro para
una nota de consulta en texto libre), `SeccionDocumento.bloques` acepta
una mezcla de `BloqueTexto` y `BloqueTabla`, y cada adaptador elige el
tipo de bloque que tiene más sentido para cada sección que construye.

`BloqueTabla` valida en `__post_init__` que cada fila tenga exactamente
el mismo número de columnas que los encabezados — un error de
programación en un adaptador (una fila con una columna de más o de
menos) falla inmediatamente con un mensaje claro, en vez de producir un
PDF con una tabla corrida o silenciosamente incompleta.

## Nunca se produce un PDF "profesional" a partir de información insuficiente

El criterio de aceptación exige explícitamente un expediente "**con
información suficiente**". `DocumentoExportable.tiene_contenido()`
devuelve `True` solo si al menos una de sus secciones tiene al menos un
bloque; `SeccionDocumento.tiene_contenido()` hace la misma verificación
a nivel de sección (así que una sección con título pero sin bloques no
cuenta como contenido). `exportar_a_pdf()` verifica esto **antes** de
tocar el disco o invocar a `reportlab`, y lanza
`DocumentoInsuficienteError` en caso contrario — nunca se llega a
escribir un archivo `.pdf` vacío disfrazado de completo. Es el mismo
principio que ya aplican, cada uno en su propio dominio, `DX-01`
(`SOSPECHA_NO_RECONOCIDA` en vez de una lista genérica), `DX-02`
(`SIN_SUSTENTO_SUFICIENTE`) e `IA-04` (secciones marcadas como
`MISSING_INFO_MARKER` en vez de inventadas).

## Cómo se traduce cada fuente

### Resumen de caso (`resumen_caso_a_documento_exportable`)

Cada una de las cuatro secciones del `CaseSummary` de IA-04
(diagnóstico, estadio, tratamientos previos, estado actual) se convierte
en una `SeccionDocumento` con un único `BloqueTexto`. El disclaimer de
IA (`CaseSummary.disclaimer`) se conserva tal cual en
`DocumentoExportable.disclaimer`, y se renderiza como un recuadro
visible al inicio del PDF — exportar el resumen a PDF **no** debe hacer
que ese aviso de "requiere revisión del oncólogo tratante" se pierda de
vista, precisamente porque un PDF es lo que se comparte fuera del
sistema (con el paciente, otro especialista o la aseguradora, según la
propia historia), donde ya no hay ninguna otra pantalla o interfaz que
lo repita.

Si el resumen tiene secciones marcadas como faltantes
(`secciones_faltantes()`, criterio AC2 de IA-04), esto se agrega como la
primera advertencia visible del documento exportado, en vez de
desaparecer silenciosamente al convertirlo a PDF: quien reciba el PDF
debe poder ver, sin abrir el sistema original, qué partes del resumen no
tienen sustento suficiente todavía.

### Expediente completo (`expediente_completo_a_documento_exportable`)

A diferencia del resumen de caso, aquí no hay nada que "redactar": cada
sección es una copia directa de filas reales de `expediente`
(datos del paciente, consultas, laboratorios, imagenología,
biomarcadores, comorbilidades), en el mismo espíritu de trazabilidad que
el resto del proyecto — no hay ningún paso intermedio donde un LLM
pudiera introducir una afirmación no verificable.

Cada sección de datos tabulares (laboratorios, imagenología,
biomarcadores, comorbilidades) solo se agrega al documento si el
paciente tiene al menos una fila real de ese tipo; un expediente sin
imágenes registradas, por ejemplo, no muestra una sección "Imagenología"
vacía. Las comorbilidades reciben un tratamiento adicional: el valor
centinela `"ninguna_registrada"` que usa `expediente` para
"se preguntó explícitamente y no tiene ninguna" se filtra antes de
decidir si la sección se incluye — no es una comorbilidad real que deba
aparecer en un PDF exportado, es la ausencia documentada de una.

Lanza `PacienteNoEncontradoError` (la misma excepción que ya usan los
otros adaptadores de `expediente.adapters`) si el paciente no
existe.

## Cómo se satisface el criterio de aceptación

| Criterio de aceptación | Mecanismo en el código |
|---|---|
| Con información suficiente, se recibe un PDF con formato profesional listo para compartirse | `exportar_a_pdf()` verifica `documento.tiene_contenido()`, construye un `BaseDocTemplate` de `reportlab` con encabezado/pie de página paginado, callout de disclaimer, títulos de sección estilizados y tablas con encabezado resaltado, y devuelve un `ResultadoExportacionPDF` con la ruta y el tamaño real del archivo escrito. |

## Fuera de alcance de esta historia

- **Firma digital o watermarking del PDF:** el criterio de aceptación
  pide un documento "profesional listo para compartir", no un mecanismo
  de verificación de autenticidad. `reportlab` no aplica ninguna firma
  ni marca de agua.
- **Envío del PDF** (por correo, portal del paciente, etc.): este módulo
  solo produce el archivo en disco; no existe ningún flujo de entrega en
  este repositorio.
- **Plantillas configurables por institución:** los estilos (colores,
  tipografía, disposición) están fijos en `pdf_export._construir_estilos()`;
  no hay ningún mecanismo de tema o plantilla institucional todavía.
- **Exportar cualquier otra vista del sistema** (por ejemplo, la
  recomendación de estudios de DX-01 o el diferencial de DX-02): la
  historia, tal como se recibió, solo pide el resumen de caso o el
  expediente completo. El renderizador genérico no impide agregar más
  adaptadores después, pero ninguno se implementó en esta historia.

## Componentes

- `pdf_export.py`: `BloqueTexto`, `BloqueTabla`, `SeccionDocumento`,
  `DocumentoExportable`, `DocumentoInsuficienteError`,
  `ResultadoExportacionPDF`, `exportar_a_pdf(...)` — el renderizador
  genérico.
- `adaptadores.py`: `resumen_caso_a_documento_exportable(...)`,
  `expediente_completo_a_documento_exportable(...)`.
- Demo: `python demo.py --solo doc` (demo unificada sobre pacientes reales de cBioPortal; ver `docs/DEMO_UNIFICADA.md`): exporta el resumen de caso y
  el expediente completo de un paciente real a PDF (en `%TEMP%\copiloto_demo\pdf`).

## Cómo probarlo

```
python demo.py --solo doc
```

Y las pruebas automatizadas:

```
pytest tests/documentos_clinicos/ -v
```

## Requisito de instalación

Esta historia introduce una dependencia nueva en el proyecto:
`reportlab` (biblioteca pura de Python, sin dependencias de sistema).

```
pip install reportlab --break-system-packages
```
