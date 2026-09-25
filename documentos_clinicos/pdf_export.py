"""Renderizado a PDF de un documento clínico exportable (DOC-02).

Este módulo **no sabe nada** de `ia_clinica`, `dx_clinica` ni
`historia_clinica_mock`: recibe un :class:`DocumentoExportable` genérico
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


def _construir_estilos():
    estilos = getSampleStyleSheet()
    estilos.add(
        ParagraphStyle(
            "SubtituloDocumento",
            parent=estilos["Normal"],
            fontSize=9,
            textColor=colors.HexColor("#555555"),
            spaceAfter=10,
        )
    )
    estilos.add(
        ParagraphStyle(
            "TituloSeccion",
            parent=estilos["Heading2"],
            fontSize=13,
            textColor=colors.HexColor("#1a3a5c"),
            spaceBefore=14,
            spaceAfter=6,
        )
    )
    estilos.add(
        ParagraphStyle(
            "ContenidoSeccion",
            parent=estilos["BodyText"],
            fontSize=10,
            leading=14,
        )
    )
    estilos.add(
        ParagraphStyle(
            "TextoDisclaimer",
            parent=estilos["BodyText"],
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#7a5b00"),
        )
    )
    estilos.add(
        ParagraphStyle(
            "TituloAdvertencias",
            parent=estilos["Heading3"],
            fontSize=11,
            textColor=colors.HexColor("#8a1f11"),
            spaceBefore=14,
            spaceAfter=4,
        )
    )
    estilos.add(
        ParagraphStyle(
            "TextoAdvertencia",
            parent=estilos["BodyText"],
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#8a1f11"),
        )
    )
    return estilos


def _tabla_encabezado_y_pie(canvas, doc, documento: DocumentoExportable) -> None:
    canvas.saveState()
    ancho, alto = doc.pagesize
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#777777"))
    pie = (
        f"Documento generado automáticamente — {documento.paciente_ref} — "
        f"{documento.generado_en.strftime('%Y-%m-%d %H:%M')}"
    )
    canvas.drawString(_MARGEN, 1.2 * cm, pie)
    canvas.drawRightString(ancho - _MARGEN, 1.2 * cm, f"Página {doc.page}")
    canvas.restoreState()


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
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3a5c")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f3f7")]),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c9c9c9")),
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

    doc = BaseDocTemplate(
        ruta_destino,
        pagesize=LETTER,
        title=documento.titulo,
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
    historia.append(Paragraph(escape(documento.titulo), estilos["Title"]))
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
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff6e0")),
                    ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#e0c25a")),
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
        historia.append(Paragraph(escape(seccion.titulo), estilos["TituloSeccion"]))
        for bloque in seccion.bloques:
            historia.append(_bloque_a_flowable(bloque, estilos))
            historia.append(Spacer(1, 4))

    if documento.advertencias:
        historia.append(Paragraph("Avisos de generación", estilos["TituloAdvertencias"]))
        for advertencia in documento.advertencias:
            historia.append(Paragraph(f"• {escape(advertencia)}", estilos["TextoAdvertencia"]))

    doc.build(historia)

    return ResultadoExportacionPDF(
        ruta=ruta_destino,
        bytes_escritos=os.path.getsize(ruta_destino),
        generado_en=documento.generado_en,
    )
