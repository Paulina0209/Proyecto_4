"""NFR-03 sobre DOC-02: el PDF cumple lo que reportlab permite y la versión HTML cubre el resto.

El PDF no puede ser etiquetado (límite de reportlab): el auditor lo informa como aviso y la
alternativa accesible del mismo contenido es ``html_export``. Estas pruebas fijan ambas cosas.
"""
from __future__ import annotations

import os
from datetime import datetime

import pytest

pytest.importorskip("pypdf")

from pypdf import PdfReader  # noqa: E402

from accesibilidad import contraste as cn  # noqa: E402
from accesibilidad.auditoria_html import ParContraste, auditar_html, verificar_pares  # noqa: E402
from accesibilidad.navegador import Navegador, NavegadorNoDisponible, auditar_en_navegador, ruta_axe  # noqa: E402
from accesibilidad.pdf import auditar_pdf  # noqa: E402
from documentos_clinicos import html_export, pdf_export  # noqa: E402
from documentos_clinicos.html_export import exportar_a_html, renderizar_html  # noqa: E402
from documentos_clinicos.pdf_export import (  # noqa: E402
    BloqueTabla, BloqueTexto, DocumentoExportable, DocumentoInsuficienteError, SeccionDocumento, exportar_a_pdf)


@pytest.fixture
def documento_largo() -> DocumentoExportable:
    """Varias páginas, una tabla de 60 filas, saltos de línea y texto con caracteres peligrosos."""
    return DocumentoExportable(
        titulo="Resumen de caso <oncología>",
        paciente_ref="paciente-1",
        generado_en=datetime(2026, 10, 10, 9, 30),
        secciones=(
            SeccionDocumento("Diagnóstico", (BloqueTexto("Línea uno\nLínea dos <b>no es negrita</b>\n\nSegundo párrafo & más " + "texto " * 300),)),
            SeccionDocumento("Laboratorios", (
                BloqueTabla(("Fecha", "Prueba", "Valor"), tuple(("2026-01-01", "Hemograma", "Normal") for _ in range(60))),
                BloqueTabla(("Marcador",), (("HER2",),)),
            )),
            SeccionDocumento("Sección vacía", ()),
        ),
        disclaimer="Documento generado automáticamente. Verifique antes de compartir.",
        advertencias=("Faltan resultados de patología.", "Estadio sin confirmar."),
    )


# --- PDF ---------------------------------------------------------------------------------


def test_los_colores_del_pdf_cumplen_el_contraste():
    for frente, fondo, tipo in pdf_export.PARES_DE_COLOR:
        razon = cn.razon_de_contraste(cn.parsear_color(frente), cn.parsear_color(fondo))
        minimo = cn.umbral(texto=tipo == "texto")
        assert razon >= minimo, f"{frente} sobre {fondo}: {razon:.2f}:1 < {minimo}:1"


def test_el_pdf_no_tiene_errores_de_accesibilidad_y_su_unico_aviso_es_el_etiquetado(documento_largo, tmp_path):
    ruta = str(tmp_path / "doc.pdf")
    exportar_a_pdf(documento_largo, ruta)
    informe = auditar_pdf(ruta)
    assert informe.aprobado, informe.resumen()
    assert [h.criterio for h in informe.avisos] == ["1.3.1"], informe.resumen()      # límite conocido de reportlab
    assert informe.datos["paginas"] >= 3 and informe.datos["textos_revisados"] > 100


def test_el_pdf_declara_idioma_titulo_visible_y_marcadores_por_seccion(documento_largo, tmp_path):
    ruta = str(tmp_path / "doc.pdf")
    exportar_a_pdf(documento_largo, ruta)
    lector = PdfReader(ruta)
    raiz = lector.trailer["/Root"]
    assert str(raiz["/Lang"]) == pdf_export.IDIOMA
    assert bool(raiz["/ViewerPreferences"]["/DisplayDocTitle"]) is True
    assert lector.metadata.title == documento_largo.titulo
    titulos = [o["/Title"] for o in lector.outline[1]]                 # [titulo, [secciones...]]
    assert lector.outline[0]["/Title"] == documento_largo.titulo
    assert titulos == ["Diagnóstico", "Laboratorios", "Avisos de generación"]       # la sección vacía no aparece


def test_el_texto_del_pdf_sigue_siendo_texto_extraible_y_en_orden(documento_largo, tmp_path):
    ruta = str(tmp_path / "doc.pdf")
    exportar_a_pdf(documento_largo, ruta)
    texto = "\n".join(p.extract_text() for p in PdfReader(ruta).pages)
    for esperado in ("Diagnóstico", "Hemograma", "Faltan resultados de patología", "Verifique antes de compartir"):
        assert esperado in texto
    assert texto.index("Diagnóstico") < texto.index("Laboratorios") < texto.index("Avisos de generación")


def test_ningun_texto_del_pdf_baja_de_9_pt_y_el_cuerpo_es_de_11(documento_largo, tmp_path):
    from accesibilidad.pdf import textos_con_contraste
    ruta = str(tmp_path / "doc.pdf")
    exportar_a_pdf(documento_largo, ruta)
    tamanos = {t["pt"] for p in PdfReader(ruta).pages for t in textos_con_contraste(p)}
    assert min(tamanos) >= 9 and 11 in tamanos


def test_el_pdf_viejo_habria_fallado_la_auditoria(tmp_path):
    """Regresión de la regla misma: el estilo anterior (pie #777 a 8 pt, sin idioma) se detecta."""
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(tmp_path / "viejo.pdf"), pagesize=LETTER, pageCompression=0)
    c.setTitle("Viejo")
    c.setFillColor("#777777")
    c.setFont("Helvetica", 8)
    c.drawString(60, 40, "Documento generado automáticamente")
    c.showPage()
    c.save()
    informe = auditar_pdf(str(tmp_path / "viejo.pdf"))
    assert {"1.4.3", "3.1.1", "2.4.2"} <= informe.criterios("error")


# --- HTML --------------------------------------------------------------------------------


def test_el_html_no_tiene_hallazgos(documento_largo):
    informe = auditar_html(renderizar_html(documento_largo))
    assert not informe.hallazgos, informe.resumen()


def test_el_html_tiene_la_estructura_real_del_documento(documento_largo):
    h = renderizar_html(documento_largo)
    assert h.startswith("<!doctype html>") and '<html lang="es-MX">' in h
    assert "<title>Resumen de caso &lt;oncología&gt; — paciente-1</title>" in h
    assert h.count("<h1>") == 1 and h.count("<h2") == 4              # aviso, 2 secciones con contenido, avisos de generación
    assert "Sección vacía" not in h
    assert h.count('<th scope="col">') == 4                           # 3 + 1
    assert "Laboratorios (tabla 1 de 2)" in h and "Laboratorios (tabla 2 de 2)" in h
    assert '<time datetime="2026-10-10T09:30:00">' in h
    assert "<script" not in h and "http://" not in h and "https://" not in h


def test_el_html_escapa_todo_lo_que_viene_de_los_datos(documento_largo):
    h = renderizar_html(documento_largo)
    assert "<b>no es negrita</b>" not in h and "&lt;b&gt;no es negrita&lt;/b&gt;" in h
    assert "<oncología>" not in h and "&amp; más" in h
    assert "Línea uno<br>Línea dos" in h and h.count("<p>Segundo párrafo") == 1


def test_sin_contenido_no_hay_html_ni_archivo(tmp_path):
    vacio = DocumentoExportable("Vacío", "p", datetime(2026, 1, 1), ())
    ruta = str(tmp_path / "no.html")
    with pytest.raises(DocumentoInsuficienteError):
        exportar_a_html(vacio, ruta)
    assert not os.path.exists(ruta)


def test_exportar_a_html_escribe_utf8_y_crea_directorios(documento_largo, tmp_path):
    ruta = str(tmp_path / "a" / "b" / "doc.html")
    r = exportar_a_html(documento_largo, ruta)
    assert r.ruta == ruta and r.bytes_escritos == os.path.getsize(ruta) and r.generado_en == documento_largo.generado_en
    assert "Diagnóstico" in open(ruta, encoding="utf-8").read()


PARES_HTML = [
    ParContraste("var(--tinta)", "var(--fondo)", "texto", "texto"),
    ParContraste("var(--tinta2)", "var(--fondo)", "texto", "texto secundario"),
    ParContraste("var(--tinta)", "var(--alterna)", "texto", "texto en filas alternas"),
    ParContraste("var(--sobre-encabezado)", "var(--encabezado-tabla)", "texto", "encabezado de tabla"),
    ParContraste("var(--aviso-tinta)", "var(--aviso-fondo)", "texto", "aviso importante"),
    ParContraste("var(--adv)", "var(--fondo)", "texto", "avisos de generación"),
    ParContraste("var(--borde)", "var(--fondo)", "grafico", "borde"),
    ParContraste("var(--rejilla)", "var(--fondo)", "grafico", "rejilla de tabla"),
    ParContraste("var(--rejilla)", "var(--alterna)", "grafico", "rejilla sobre fila alterna"),
    ParContraste("var(--aviso-borde)", "var(--aviso-fondo)", "grafico", "borde del aviso"),
    ParContraste("var(--foco)", "var(--fondo)", "grafico", "indicador de foco"),
]


def test_los_colores_del_html_cumplen_el_contraste_en_claro_y_oscuro():
    assert verificar_pares(html_export._CSS, PARES_HTML) == []


@pytest.fixture(scope="module")
def nav():
    try:
        with Navegador() as n:
            yield n
    except NavegadorNoDisponible as exc:
        pytest.skip(str(exc))


def test_el_html_pasa_en_chromium_con_axe_en_claro_oscuro_1280_y_320(nav, documento_largo):
    informe = auditar_en_navegador(renderizar_html(documento_largo), navegador=nav, axe_js=ruta_axe())
    assert informe.aprobado and not informe.avisos, informe.resumen()
    assert [p["sel"] for p in informe.datos["paradas_de_tabulacion"]][0] == "a.saltar"
    assert all(p["indicador"] for p in informe.datos["paradas_de_tabulacion"])
