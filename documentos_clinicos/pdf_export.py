"""Renderizado a PDF de un documento clínico exportable (DOC-02).

Este módulo **no sabe nada** de `ia_clinica`, `dx_clinica` ni
`expediente`: recibe un :class:`DocumentoExportable` genérico
(título, referencia de paciente, fecha de generación, secciones con
bloques de texto o de tabla, disclaimer y advertencias opcionales) y
produce un PDF con formato profesional. Quién construye ese
``DocumentoExportable`` a partir de un resumen de caso o de un
expediente completo es responsabilidad de `adaptadores.py` — separación
deliberada para que este renderizador sirva para cualquier documento
clínico exportable presente o futuro, no solo para los dos casos que
cubre esta historia.

Usa `reportlab` (biblioteca pura de Python, sin dependencias de sistema)
para el PDF en sí.

**Accesibilidad (NFR-03, WCAG 2.1 AA).** El PDF declara su idioma y muestra su
título en la barra de la ventana, tiene marcadores (un índice navegable por
sección), todo el texto es texto real (no imágenes), los colores cumplen el
contraste (``PARES_DE_COLOR``, verificado en las pruebas) y los tamaños son
legibles (cuerpo 11 pt, nada por debajo de 9 pt). **Limitación conocida:**
reportlab no genera PDF etiquetado (sin árbol de estructura), así que un lector
de pantalla debe adivinar el orden de lectura; la alternativa accesible del mismo
contenido es ``html_export.exportar_a_html`` (encabezados, tablas y regiones
reales). ``accesibilidad.pdf.auditar_pdf`` informa esta limitación como aviso.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Tuple, Union
from xml.sax.saxutils import escape

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        BaseDocTemplate,
        Frame,
        PageTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
    )
except ImportError as exc:  # pragma: no cover - depende de instalación externa
    raise ImportError(
        "El paquete 'reportlab' no está instalado. Instálalo con "
        "'pip install reportlab --break-system-packages' para poder exportar a PDF."
    ) from exc


class DocumentoInsuficienteError(Exception):
    """Se lanza cuando el documento no tiene ninguna sección con contenido real.

    Nunca se produce un PDF "profesional" vacío disfrazado de completo:
    el criterio de aceptación de DOC-02 exige explícitamente un
    expediente/resumen "con información suficiente".
    """


@dataclass(frozen=True)
class BloqueTexto:
    """Un párrafo de texto dentro de una sección del documento."""

    texto: str


@dataclass(frozen=True)
class BloqueTabla:
    """Una tabla dentro de una sección del documento (p. ej. una lista de laboratorios)."""

    encabezados: Tuple[str, ...]
    filas: Tuple[Tuple[str, ...], ...]

    def __post_init__(self) -> None:
        for fila in self.filas:
            if len(fila) != len(self.encabezados):
                raise ValueError(
                    "Cada fila de una BloqueTabla debe tener el mismo número de "
                    "columnas que sus encabezados."
                )


Bloque = Union[BloqueTexto, BloqueTabla]


@dataclass(frozen=True)
class SeccionDocumento:
    """Una sección con título del documento exportable, con uno o más bloques."""

    titulo: str
    bloques: Tuple[Bloque, ...] = ()

    def tiene_contenido(self) -> bool:
        return len(self.bloques) > 0


@dataclass(frozen=True)
class DocumentoExportable:
    """Modelo genérico de un documento clínico listo para exportarse a PDF.

    Independiente de qué historia de usuario lo produjo — ver
    `adaptadores.py` para las traducciones concretas de esta historia
    (resumen de caso, expediente completo).
    """

    titulo: str
    paciente_ref: str
    generado_en: datetime
    secciones: Tuple[SeccionDocumento, ...]
    disclaimer: Optional[str] = None
    advertencias: Tuple[str, ...] = field(default_factory=tuple)

    def tiene_contenido(self) -> bool:
        return any(seccion.tiene_contenido() for seccion in self.secciones)


@dataclass(frozen=True)
class ResultadoExportacionPDF:
    """Resultado de una exportación exitosa."""

    ruta: str
    bytes_escritos: int
    generado_en: datetime


_MARGEN = 2 * cm

#: Colores del documento. Todo par (texto, fondo) está en ``PARES_DE_COLOR`` y una prueba exige 4.5:1
#: (3:1 para lo que no es texto, WCAG 1.4.3 y 1.4.11).
COLOR_TEXTO = "#000000"
COLOR_SUBTITULO = "#555555"
COLOR_TITULO_SECCION = "#1a3a5c"
COLOR_ENCABEZADO_TABLA = "#1a3a5c"
COLOR_FILA_ALTERNA = "#f0f3f7"
COLOR_REJILLA = "#858585"
COLOR_FONDO_DISCLAIMER = "#fff6e0"
COLOR_TEXTO_DISCLAIMER = "#7a5b00"
COLOR_BORDE_DISCLAIMER = "#8a6d00"
COLOR_ADVERTENCIA = "#8a1f11"
COLOR_PIE = "#595959"

#: (frente, fondo, tipo) con tipo "texto" o "grafico".
PARES_DE_COLOR = (
    (COLOR_TEXTO, "#ffffff", "texto"),
    (COLOR_TEXTO, COLOR_FILA_ALTERNA, "texto"),
    (COLOR_SUBTITULO, "#ffffff", "texto"),
    (COLOR_TITULO_SECCION, "#ffffff", "texto"),
    ("#ffffff", COLOR_ENCABEZADO_TABLA, "texto"),
    (COLOR_TEXTO_DISCLAIMER, COLOR_FONDO_DISCLAIMER, "texto"),
    (COLOR_ADVERTENCIA, "#ffffff", "texto"),
    (COLOR_PIE, "#ffffff", "texto"),
    (COLOR_REJILLA, "#ffffff", "grafico"),
    (COLOR_REJILLA, COLOR_FILA_ALTERNA, "grafico"),
    (COLOR_BORDE_DISCLAIMER, COLOR_FONDO_DISCLAIMER, "grafico"),
)

#: Idioma del documento (PDF /Lang): los lectores de pantalla eligen la voz con él.
IDIOMA = "es-MX"


def _construir_estilos():
    estilos = getSampleStyleSheet()
    estilos.add(
        ParagraphStyle(
            "SubtituloDocumento",
            parent=estilos["Normal"],
            fontSize=10,
            leading=13,
            textColor=colors.HexColor(COLOR_SUBTITULO),
            spaceAfter=10,
        )
    )
    estilos.add(
        ParagraphStyle(
            "TituloSeccion",
            parent=estilos["Heading2"],
            fontSize=14,
            textColor=colors.HexColor(COLOR_TITULO_SECCION),
            spaceBefore=14,
            spaceAfter=6,
        )
    )
    estilos.add(
        ParagraphStyle(
            "ContenidoSeccion",
            parent=estilos["BodyText"],
            fontSize=11,
            leading=15,
        )
    )
    estilos.add(
        ParagraphStyle(
            "TextoDisclaimer",
            parent=estilos["BodyText"],
            fontSize=10.5,
            leading=14,
            textColor=colors.HexColor(COLOR_TEXTO_DISCLAIMER),
        )
    )
    estilos.add(
        ParagraphStyle(
            "TituloAdvertencias",
            parent=estilos["Heading3"],
            fontSize=12,
            textColor=colors.HexColor(COLOR_ADVERTENCIA),
            spaceBefore=14,
            spaceAfter=4,
        )
    )
    estilos.add(
        ParagraphStyle(
            "TextoAdvertencia",
            parent=estilos["BodyText"],
            fontSize=10.5,
            leading=14,
            textColor=colors.HexColor(COLOR_ADVERTENCIA),
        )
    )
    return estilos


def _tabla_encabezado_y_pie(canvas, doc, documento: DocumentoExportable) -> None:
    canvas.saveState()
    ancho, alto = doc.pagesize
    canvas.setFont("Helvetica", 9)
    canvas.setFillColor(colors.HexColor(COLOR_PIE))
    pie = (
        f"Documento generado automáticamente — {documento.paciente_ref} — "
        f"{documento.generado_en.strftime('%Y-%m-%d %H:%M')}"
    )
    canvas.drawString(_MARGEN, 1.2 * cm, pie)
    canvas.drawRightString(ancho - _MARGEN, 1.2 * cm, f"Página {doc.page}")
    canvas.restoreState()


class _Encabezado(Paragraph):
    """Párrafo que además registra un marcador (entrada del índice del PDF) cuando se dibuja."""

    def __init__(self, texto: str, estilo, nivel: int, titulo_plano: str) -> None:
        super().__init__(texto, estilo)
        self.nivel_marcador = nivel
        self.titulo_plano = titulo_plano


class _Documento(BaseDocTemplate):
    """``BaseDocTemplate`` que convierte los ``_Encabezado`` en marcadores (WCAG 2.4.1 / 2.4.5 en PDF)."""

    def afterFlowable(self, flowable) -> None:  # noqa: N802 (nombre fijado por reportlab)
        if isinstance(flowable, _Encabezado):
            self._n_marcadores = getattr(self, "_n_marcadores", 0) + 1
            clave = f"encabezado-{self._n_marcadores}"
            self.canv.bookmarkPage(clave)
            self.canv.addOutlineEntry(flowable.titulo_plano, clave, level=flowable.nivel_marcador, closed=0)


def _bloque_a_flowable(bloque: Bloque, estilos):
    if isinstance(bloque, BloqueTexto):
        return Paragraph(escape(bloque.texto).replace("\n", "<br/>"), estilos["ContenidoSeccion"])

    if isinstance(bloque, BloqueTabla):
        datos = [[escape(str(celda)) for celda in bloque.encabezados]]
        for fila in bloque.filas:
            datos.append([escape(str(celda)) for celda in fila])
        tabla = Table(datos, repeatRows=1, hAlign="LEFT")
        tabla.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(COLOR_ENCABEZADO_TABLA)),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor(COLOR_TEXTO)),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("LEADING", (0, 0), (-1, -1), 13),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(COLOR_FILA_ALTERNA)]),
                    ("GRID", (0, 0), (-1, -1), 0.75, colors.HexColor(COLOR_REJILLA)),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        return tabla

    raise TypeError(f"Tipo de bloque no soportado: {type(bloque)!r}")  # pragma: no cover


def exportar_a_pdf(documento: DocumentoExportable, ruta_destino: str) -> ResultadoExportacionPDF:
    """Renderiza ``documento`` como un PDF con formato profesional en ``ruta_destino``.

    Lanza ``DocumentoInsuficienteError`` si ``documento`` no tiene ninguna
    sección con contenido real — nunca se genera un PDF vacío disfrazado
    de "listo para compartir".
    """

    if not documento.tiene_contenido():
        raise DocumentoInsuficienteError(
            "El documento no tiene ninguna sección con contenido; no se genera un "
            "PDF a partir de información insuficiente."
        )

    os.makedirs(os.path.dirname(os.path.abspath(ruta_destino)), exist_ok=True)
    estilos = _construir_estilos()

    doc = _Documento(
        ruta_destino,
        pagesize=LETTER,
        title=documento.titulo,
        subject=f"Documento clínico de {documento.paciente_ref}",
        creator="Copiloto oncológico",
        lang=IDIOMA,
        displayDocTitle=1,
        leftMargin=_MARGEN,
        rightMargin=_MARGEN,
        topMargin=_MARGEN,
        bottomMargin=_MARGEN,
    )
    marco = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        doc.width,
        doc.height,
        id="marco_principal",
    )
    plantilla = PageTemplate(
        id="plantilla_principal",
        frames=[marco],
        onPage=lambda canvas, doc_: _tabla_encabezado_y_pie(canvas, doc_, documento),
    )
    doc.addPageTemplates([plantilla])

    historia = []
    historia.append(_Encabezado(escape(documento.titulo), estilos["Title"], 0, documento.titulo))
    historia.append(
        Paragraph(
            f"Paciente: {escape(documento.paciente_ref)} &nbsp;|&nbsp; "
            f"Generado: {documento.generado_en.strftime('%Y-%m-%d %H:%M')}",
            estilos["SubtituloDocumento"],
        )
    )

    if documento.disclaimer:
        tabla_disclaimer = Table(
            [[Paragraph(escape(documento.disclaimer), estilos["TextoDisclaimer"])]],
            colWidths=[doc.width],
        )
        tabla_disclaimer.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(COLOR_FONDO_DISCLAIMER)),
                    ("BOX", (0, 0), (-1, -1), 1, colors.HexColor(COLOR_BORDE_DISCLAIMER)),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        historia.append(Spacer(1, 6))
        historia.append(tabla_disclaimer)

    for seccion in documento.secciones:
        if not seccion.tiene_contenido():
            continue
        historia.append(_Encabezado(escape(seccion.titulo), estilos["TituloSeccion"], 1, seccion.titulo))
        for bloque in seccion.bloques:
            historia.append(_bloque_a_flowable(bloque, estilos))
            historia.append(Spacer(1, 4))

    if documento.advertencias:
        historia.append(_Encabezado("Avisos de generación", estilos["TituloAdvertencias"], 1, "Avisos de generación"))
        for advertencia in documento.advertencias:
            historia.append(Paragraph(f"• {escape(advertencia)}", estilos["TextoAdvertencia"]))

    doc.build(historia)

    return ResultadoExportacionPDF(
        ruta=ruta_destino,
        bytes_escritos=os.path.getsize(ruta_destino),
        generado_en=documento.generado_en,
    )
