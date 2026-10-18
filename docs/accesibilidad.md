# NFR-03 — Accesibilidad (WCAG 2.1 AA)

## Historia de usuario

Como usuario con una discapacidad visual o motriz, quiero que la interfaz cumpla
los estándares de accesibilidad (WCAG 2.1 AA), para poder usarla sin barreras.

Épica No funcional · Should Have · 5 pts · sin dependencias · no es MVP.

El backlog solo trae la frase anterior, sin criterios de aceptación. Estos son los
propuestos (confírmalos o ajústalos):

```
AC1  Dado cualquier pantalla o documento que el sistema genera para una persona
     (hoy: el tablero de métricas y las exportaciones de DOC-02)
     Cuando se audita contra las reglas de WCAG 2.1 AA que se pueden automatizar
     Entonces no tiene errores, y una regresión rompe una prueba (compuerta de CI)

AC2  Dada una persona que usa solo teclado, lector de pantalla, ampliación al 400 %,
     modo oscuro o contraste alto
     Cuando usa el tablero
     Entonces puede leer todas sus cifras y operar todos sus controles sin ratón
     (los gráficos se recorren con flechas; cada gráfico tiene su tabla equivalente)

AC3  Dado un documento exportado a PDF
     Cuando la persona necesita acceder a él con un lector de pantalla
     Entonces dispone de una versión HTML equivalente con estructura real, y el sistema
     dice con honestidad lo que el PDF no puede ofrecer (no es un PDF etiquetado)

AC4  Dado el estado de conformidad del sistema
     Cuando se documenta
     Entonces dice qué se verificó automáticamente, qué falta verificar a mano
     (lector de pantalla, personas usuarias) y qué superficies son de terceros
```

## Alcance: qué "interfaz" hay hoy

Las superficies que una persona ve son estas, y el estado de cada una (la interfaz web clínica, `frontend/`, se
documenta en `docs/frontend.md`):

| Superficie | De quién es | Estado |
|---|---|---|
| Interfaz web clínica (`frontend/`: acceso, pacientes, expediente) | Propia | **Cubierta por pruebas**: estáticas y Chromium con axe-core en cada pantalla, en claro, oscuro y 320 px (`tests/frontend`); sin prueba manual todavía |
| Tablero de métricas (`GET /metricas/panel`, ADM-02) | Propia | **Corregida y cubierta por pruebas** (ver abajo) |
| Página de error del tablero (periodo inválido) | Propia | Nueva, accesible (3.3.1, 3.3.3, 4.1.3) |
| Exportación PDF (DOC-02) | Propia | **Mejorada**; no puede ser PDF etiquetado (límite de reportlab) |
| Exportación HTML (DOC-02) | Propia | **Nueva**: alternativa accesible al PDF |
| Documentación interactiva de FastAPI (`/docs`, `/redoc`) | Tercero | **No cubierta.** Es una herramienta para quien desarrolla, no para el personal clínico |
| Visor de imágenes OHIF (HC-03) | Tercero | **No cubierta.** Su accesibilidad es la del proyecto OHIF; hay que evaluarla antes de ofrecerlo a usuarios finales |
| Demos y herramientas de línea de comandos | Propia | Texto en consola; WCAG no aplica |

Las pantallas que falten del frontend clínico (estadificación, plan de
tratamiento, documentos…) tendrán que pasar por la misma compuerta: ver «Reglas para la futura
interfaz» más abajo. Lo construido aquí es la compuerta y los criterios, no solo el
arreglo de una pantalla.

## Qué se implementó

`accesibilidad/` (paquete nuevo, sin dependencias de los demás módulos):

- `contraste.py` — razón de contraste WCAG (luminancia sRGB), umbrales de 1.4.3 (4.5:1 y 3:1
  para texto grande) y 1.4.11 (3:1), lectura de variables CSS por esquema.
- `auditoria_html.py` — auditor estático de HTML y CSS (`auditar_html`, `auditar_css`) y
  verificación de pares de color de los tokens de diseño en **tres esquemas**: claro,
  oscuro del sistema y oscuro manual (`verificar_pares`). Un `error` es un incumplimiento
  seguro; un `aviso`, algo a revisar a mano.
- `pdf.py` — `auditar_pdf`: título y `DisplayDocTitle`, idioma, marcadores, texto real,
  contraste de cada texto **contra el fondo que realmente tiene debajo** (interpreta el
  flujo de contenido del PDF con matrices y rectángulos rellenos), tamaño de letra y si
  está etiquetado.
- `navegador.py` — comprobaciones opcionales en Chromium (Playwright): contraste calculado,
  reflujo a 320 px, espaciado de texto, objetivos táctiles, recorrido de tabulación con
  indicador de foco y sin trampas de teclado, y axe-core si hay copia (`AXE_CORE_JS`). Si
  Playwright no está instalado, esas pruebas se omiten.
- `python -m accesibilidad html|pdf|sistema` — línea de comandos; `sistema` audita lo que el
  sistema genera hoy con datos sintéticos y devuelve 1 si hay errores.

Cambios en las superficies:

- **Tablero ADM-02** (`administracion/panel_metricas.py`, `api.py`): ver «Qué se corrigió».
- **DOC-02** (`documentos_clinicos/pdf_export.py`, nuevo `html_export.py`): ver «DOC-02».

## Qué se corrigió en el tablero

El auditor encontró fallos reales; no eran hipotéticos.

| Hallazgo | Criterio | Corrección |
|---|---|---|
| Texto atenuado (`--muted`) a 3.4:1 | 1.4.3 | `#6b6a65`, 5.1:1 (en oscuro ya pasaba) |
| Bordes de botones y campos a 1.75:1 | 1.4.11 | token `--borde`, ≥ 3.5:1 en los dos esquemas |
| Barras apiladas y medidor sin borde, bajo 3:1 contra la tarjeta | 1.4.11 | borde de 1 px en segmentos, muestras de leyenda y medidor; pista del medidor oscura más contrastada |
| 11 tablas sin título | 1.3.1 | `<caption>` por tabla (solo para lectores de pantalla) |
| Una parada de tabulación por semana (15 en total) | 2.1.1 / 2.4.3 | una parada por gráfico; las flechas, Inicio y Fin recorren las semanas |
| Tooltip imposible de descartar o de alcanzar con el puntero | 1.4.13 | `Esc` lo cierra, el puntero puede entrar en él y no desaparece mientras se usa |
| Tooltip como `role="status"` (podía leer todo dos veces) | 4.1.3 | `aria-hidden`; su contenido ya está en el nombre accesible de cada semana y en las tablas |
| "—" con `title` para explicar la falta de datos | 1.1.1 / 1.3.1 | texto para lector de pantalla: «No disponible. <motivo>» (un `title` no se alcanza con teclado ni táctil) |
| Tarjetas de gráficos y columnas de detalle que desbordaban la página a 320 px | 1.4.10 | rejilla `min()`, tablas y gráficos en regiones que se desplazan y reciben foco solo si lo necesitan |
| Texto de 11 px en ejes; porcentajes de 6–7 px dentro de las barras en móvil | 1.4.4 | ejes a 12 y gráfico con ancho mínimo; el porcentaje sale de la barra (está en la tabla de leyenda y en el nombre accesible) |
| Sin salto al contenido; foco sin estilo común | 2.4.1 / 2.4.7 | enlace «Saltar al contenido principal»; contorno de 3 px en todo lo enfocable |
| Controles de ~30 px | motriz | altura mínima de 40 px (WCAG 2.2 pide 24; 2.1 AAA, 44) |
| Un periodo inválido devolvía JSON crudo en el navegador | 3.3.1 / 3.3.3 | página de error con `role="alert"`, qué falló, cómo corregirlo, lo escrito conservado y una salida |

Decisiones que conviene conocer:

- **Cada gráfico tiene una tabla equivalente** (ya existía) y ahora cada semana es además un
  elemento con nombre completo («18 sep – 24 sep: Usuarios activos 13»). El gráfico es un
  complemento, nunca la única vía a un dato.
- **Los segmentos de aceptación de IA no llevan texto dentro.** Con la barra reducida en un
  teléfono, el texto quedaba ilegible; el dato está justo debajo en la tabla de leyenda.
- **`--grid` y `--axis` no cumplen 3:1 a propósito**: son cuadrícula y eje decorativos; cada
  valor está en etiquetas, tooltip y tabla (la prueba lo declara en `PARES_PANEL`).
- La **página de error** devuelve 400 en HTML solo en `/metricas/panel`; `/metricas` sigue
  devolviendo JSON, porque su cliente es un programa.

## DOC-02

**PDF** (`pdf_export.py`): idioma `es-MX`, título visible en la ventana (`DisplayDocTitle`),
marcadores por sección (el índice navegable), todo texto real, colores verificados contra
`PARES_DE_COLOR` (el pie de página estaba a 4.48:1 y pasa a 7:1), cuerpo de 11 pt (antes 10),
tablas de 10 pt (antes 8.5), nada por debajo de 9 pt, rejilla de tablas con contraste.

**Límite que no se puede arreglar aquí:** reportlab no genera PDF etiquetado (sin árbol de
estructura). Un lector de pantalla tiene que adivinar el orden de lectura y no reconoce las
tablas como tablas. `auditar_pdf` lo informa como **aviso** y las pruebas fijan que ese es el
único aviso: si un día se cambia de biblioteca y el PDF queda etiquetado, el aviso
desaparecerá y la prueba lo señalará. Opciones para ese día: evaluar una biblioteca que
produzca PDF/UA (por ejemplo WeasyPrint) o etiquetar a mano el PDF generado.

**HTML** (`html_export.py`): el mismo `DocumentoExportable`, con estructura real. Un `<h1>`,
una sección con `<h2>` por cada una del documento, tablas con `<caption>` y `scope`, aviso y
advertencias como secciones propias, salto al contenido, claro/oscuro, impresión y reflujo
(las tablas anchas se desplazan en una región con foco). Sin scripts ni recursos externos;
todo se escapa. Misma regla que el PDF: sin contenido real no se genera nada.

```python
from documentos_clinicos import exportar_a_html, exportar_a_pdf
exportar_a_pdf(documento, "resumen.pdf")
exportar_a_html(documento, "resumen.html")     # entrégalo junto al PDF a quien use lector de pantalla
```

Los adaptadores existentes (`resumen_caso_a_documento_exportable`,
`expediente_completo_a_documento_exportable`) producen el mismo modelo, así que ambas
exportaciones salen de cualquiera de los dos documentos sin tocarlos.

## Mapa de criterios WCAG 2.1 (A y AA)

«Auto» = lo comprueba una prueba automática; «Manual» = está en el protocolo de abajo.

| Criterio | Tablero | PDF | HTML DOC-02 | Verificación |
|---|---|---|---|---|
| 1.1.1 Contenido no textual | SVG con nombre; barra con sus cifras; decorativos `aria-hidden` | sin imágenes | sin imágenes | Auto (estático + axe) |
| 1.2.x Multimedia | N/A | N/A | N/A | — |
| 1.3.1 Información y relaciones | encabezados, regiones, tablas con título y `scope` | **parcial** (sin etiquetar) | sí | Auto + Manual |
| 1.3.2 Secuencia con sentido | orden del DOM = orden visual | orden de lectura no garantizado | sí | Manual |
| 1.3.3 Características sensoriales | instrucciones en texto («con teclado: …») | — | — | Manual |
| 1.3.4 Orientación | sin bloqueo | — | sin bloqueo | Manual |
| 1.3.5 Propósito de los campos | los campos son fechas (no datos personales); el auditor exige `autocomplete` en los personales | — | — | Auto |
| 1.4.1 Uso del color | selección con ✓, delta con ▲▼ y signo, leyenda con texto y muestra | avisos con título | sí | Manual |
| 1.4.3 Contraste mínimo | tokens en 3 esquemas + calculado en Chromium | contra el fondo real de cada texto | tokens en 2 esquemas + Chromium | Auto |
| 1.4.4 Cambio de tamaño | sin alturas fijas; ejes ≥ 12 px | — | rem | Auto (espaciado, zoom) + Manual |
| 1.4.5 Imágenes de texto | ninguna | ninguna (texto real) | ninguna | Auto (PDF) |
| 1.4.10 Reflujo | probado a 320 px; tablas y gráficos se desplazan (excepción permitida) | — | probado a 320 px | Auto |
| 1.4.11 Contraste no textual | bordes, series, foco, medidor | rejilla y borde del aviso | bordes, rejilla, foco | Auto |
| 1.4.12 Espaciado del texto | nada se corta al aumentarlo | — | idem | Auto |
| 1.4.13 Contenido al pasar o enfocar | tooltip descartable, alcanzable y persistente | — | no hay | Auto (Chromium) |
| 2.1.1 Teclado | todo con teclado; gráficos con flechas | — | sí | Auto (recorrido) + Manual |
| 2.1.2 Sin trampas | recorrido termina | — | sí | Auto |
| 2.1.4 Atajos de teclado | no hay | — | no hay | — |
| 2.2.1 / 2.2.2 Tiempo y movimiento | sin límites de tiempo ni animación | — | — | Auto (sin `refresh`/`marquee`) |
| 2.3.1 Destellos | ninguno | — | — | — |
| 2.4.1 Saltar bloques | salto + regiones | marcadores | salto + regiones | Auto |
| 2.4.2 Título de la página | sí | `Title` + `DisplayDocTitle` | sí | Auto |
| 2.4.3 Orden del foco | orden natural, sin `tabindex` positivo | — | sí | Auto |
| 2.4.4 Propósito del enlace | texto descriptivo (el auditor avisa de «aquí») | — | — | Auto |
| 2.4.5 Varias vías | página única | marcadores | página única | Auto (PDF) |
| 2.4.6 Encabezados y etiquetas | sí | títulos de sección | sí | Auto |
| 2.4.7 Foco visible | contorno de 3 px; el auditor prohíbe `outline:none` sin sustituto | — | sí | Auto (recorrido) |
| 2.5.1 / 2.5.2 / 2.5.4 Gestos, cancelación, movimiento | solo clic/toque simple; controles nativos | — | — | Manual |
| 2.5.3 Etiqueta en el nombre | la etiqueta visible es el nombre | — | — | Manual |
| 3.1.1 Idioma | `es` | `es-MX` | `es-MX` | Auto |
| 3.1.2 Idioma de las partes | términos técnicos en el idioma del documento | — | — | Manual |
| 3.2.x Predecible | los filtros son enlaces y un botón; nada cambia al enfocar | — | — | Manual |
| 3.3.1 / 3.3.3 Error y sugerencia | página de error (qué falló y cómo corregirlo) | — | — | Auto |
| 3.3.2 Etiquetas o instrucciones | campos con etiqueta visible | — | — | Auto |
| 3.3.4 Prevención de errores | N/A: solo lectura | — | — | — |
| 4.1.1 Procesamiento | ids únicos y referencias ARIA válidas (criterio retirado en WCAG 2.2) | — | — | Auto |
| 4.1.2 Nombre, función, valor | controles con nombre; roles válidos | — | — | Auto (estático + axe) |
| 4.1.3 Mensajes de estado | el error usa `role="alert"`; el tooltip no se anuncia (su contenido ya está en el nombre) | — | — | Manual |

## Declaración de conformidad

**El sistema no está certificado ni se declara conforme con WCAG 2.1 AA.** Lo que sí se puede
afirmar, y con qué respaldo:

- El tablero y la versión HTML de DOC-02 **no tienen errores** en las comprobaciones
  automatizadas descritas arriba (estáticas, de contraste en todos los esquemas y en
  Chromium a 1280 y 320 px, con axe-core). Está respaldado por pruebas que se ejecutan en
  cada corrida.
- El PDF de DOC-02 cumple lo que permite su generador y **declara que no está etiquetado**.
- **No se ha probado con lectores de pantalla ni con personas usuarias.** Las herramientas
  automáticas detectan solo una parte de los problemas reales (orden de lectura confuso,
  nombres que no se entienden, instrucciones ambiguas…). Hasta que se haga el protocolo
  manual, lo correcto es hablar de «sin errores automáticos conocidos», no de «accesible».
- Quedan fuera las superficies de terceros (Swagger de FastAPI, visor OHIF).

## Prueba manual (pendiente; necesaria antes de afirmar conformidad)

Hazla con el tablero real (`python -m administracion.demo_metricas`, o el servidor TLS) y
con un PDF y su HTML de DOC-02. Anota qué lector y qué navegador usaste.

1. **Teclado solo** (desconecta el ratón). Desde el inicio: ¿el primer `Tab` muestra «Saltar al
   contenido»? ¿Se alcanzan los tres periodos, «Rango personalizado» y sus campos? En cada
   gráfico, ¿las flechas, `Inicio` y `Fin` recorren las semanas y `Esc` cierra el detalle?
   ¿El foco se ve siempre? ¿Se puede salir de todo con `Tab`/`Mayús+Tab`?
2. **Lector de pantalla en Windows: NVDA (gratuito) con Edge o Chrome**, y si es posible JAWS.
   En el tablero: navega por encabezados (`H`), regiones (`D`) y tablas (`T`); comprueba que
   cada cifra se entiende **sin ver** («No disponible. Fuente no disponible», no «raya»);
   que cada semana de un gráfico se lee completa; que la barra de aceptación dice sus cifras
   y que el error de periodo se anuncia solo. En macOS/iOS repite con VoiceOver.
3. **PDF con NVDA y Acrobat Reader**: ¿se lee en orden? ¿las tablas se anuncian como tablas?
   (esperado: no del todo, es el límite conocido). Compara con el HTML: debe ser claramente
   mejor. Verifica que los marcadores aparecen y llevan a cada sección.
4. **Baja visión**: ampliación del navegador al 200 % y al 400 % (¿hay desplazamiento horizontal
   de la página? solo se admite dentro de tablas y gráficos); Lupa de Windows; modo oscuro;
   **temas de contraste de Windows** (Configuración → Accesibilidad → Temas de contraste):
   ¿se ve todo, incluidos gráficos, bordes y foco?; tamaño de texto del sistema al máximo;
   espaciado de texto con una extensión (p. ej. «Text Spacing Bookmarklet»).
5. **Motriz**: control por voz (Acceso por voz de Windows o Dragon: «clic en Últimos 7 días»);
   ¿los nombres que se ven son los que se dicen (2.5.3)? Toque en un teléfono: ¿se acierta con
   los controles sin ampliar?
6. **Cognitiva** (revisión rápida): ¿el texto de ayuda se entiende?, ¿los términos técnicos son los
   que usa el personal?, ¿el mensaje de error dice qué hacer?

Resultado: registra fecha, versión, herramienta, hallazgos y la corrección; actualiza la
«Declaración de conformidad» solo con lo comprobado.

## Reglas para la interfaz

Quien amplíe el frontend clínico debe cumplir esto y añadir su pantalla a la compuerta:

1. **HTML semántico antes que ARIA**: `button`, `a`, `label`, `table`, `h1…h6`, `main`, `nav`. ARIA
   solo cuando no hay elemento nativo.
2. **Color con tokens y pares verificados**: define los colores como variables CSS por esquema
   (claro, oscuro) y declara los pares en una prueba con `verificar_pares`. Nunca el color como
   única señal (añade texto, icono o forma).
3. **Todo con teclado, con foco visible**. Sin `outline:none` sin sustituto; un `Tab` por
   componente complejo (flechas dentro de él); sin `tabindex` positivo.
4. **Reflujo a 320 px**: `min()` en las rejillas, tablas y gráficos en regiones que se desplazan.
5. **Cada gráfico, una tabla equivalente**; el tooltip nunca es la única vía a un dato (y es
   descartable con `Esc`, alcanzable y persistente).
6. **Errores**: dilo con texto, di cómo corregirlo, conserva lo escrito, anúncialo (`role="alert"`).
7. **Un dato que falta se dice**: «No disponible» con su motivo, nunca vacío ni 0.
8. **Objetivos de al menos 40 px** de alto en controles.
9. **En una aplicación de una sola página, el foco y el enrutador cuentan.** Al cambiar de pantalla el foco va
   al título y se anuncia; al abrir o recargar la página queda al principio (el primer `Tab` llega al salto
   al contenido). Si el enrutador usa el hash de la URL, el enlace «Saltar al contenido» (`#contenido`) hay
   que interceptarlo: si no, el enrutador lo toma por una ruta (lo descubrió `tests/frontend`).
10. **Con una CSP estricta, las auditorías no pueden inyectar estilos ni scripts en línea.** `navegador.py` usa
    una hoja construida por script y `evaluate` para axe-core, y avisa si el espaciado de prueba no se aplicó.
11. **La pantalla nueva entra a la compuerta**: una prueba que renderice la pantalla en cada estado y
   llame a `auditar_html` (cero hallazgos) y, si hay Chromium, `auditar_en_navegador` (o
    `auditar_pagina_abierta` si hace falta iniciar sesión). Modelos: `tests/administracion/test_panel_accesibilidad.py`
    y `tests/frontend/`.

## Cómo probarlo

```
python -m pytest tests/accesibilidad tests/administracion/test_panel_accesibilidad.py tests/documentos_clinicos tests/frontend -q

python -m accesibilidad sistema                # tablero, PDF y HTML de DOC-02 con datos sintéticos
python -m accesibilidad sistema --navegador    # añade Chromium (y axe-core si AXE_CORE_JS está definida)
python -m accesibilidad html mi_pagina.html
python -m accesibilidad pdf  mi_documento.pdf
```

Para las pruebas de navegador: `pip install playwright pypdf` y `playwright install chromium`
(sin ellas se omiten, no fallan). Para axe-core: `npm install axe-core` y
`set AXE_CORE_JS=C:\ruta\node_modules\axe-core\axe.min.js`.

## Límites conocidos

- **Falta la prueba manual con lector de pantalla y con personas usuarias** (arriba).
- **El PDF no está etiquetado** (reportlab). La alternativa es el HTML.
- **Superficies de terceros** (Swagger UI, OHIF) no se auditan aquí.
- El auditor estático revisa el documento tal como se escribe, no los estilos computados por el
  navegador; por eso hay una segunda capa en Chromium. Ninguna de las dos sustituye a una persona.
- El contraste del PDF se calcula con colores RGB/gris/CMYK ingenuo y rectángulos rellenos; no
  entiende degradados ni imágenes de fondo (no los hay hoy).
- El criterio 4.1.1 se retiró en WCAG 2.2; se conserva porque los ids duplicados rompen
  etiquetas y referencias ARIA.
- Objetivos táctiles de 24 px (WCAG 2.2, 2.5.8) se miden como aviso; el tablero ya usa 40 px.
- Los textos de los datos clínicos que lleguen a las exportaciones se muestran tal cual: si un
  texto es ininteligible o está en otro idioma, la accesibilidad de ese contenido es la de su origen.
