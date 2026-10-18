"""NFR-03 — El auditor de PDF detecta cada incumplimiento y no se deja engañar por fondos de color."""
from __future__ import annotations

import pytest

pytest.importorskip("pypdf")
pytest.importorskip("reportlab")

from reportlab.lib.pagesizes import LETTER  # noqa: E402
from reportlab.pdfgen import canvas as rl_canvas  # noqa: E402

from accesibilidad.auditoria_html import AVISO, ERROR  # noqa: E402
from accesibilidad.pdf import auditar_pdf, textos_con_contraste  # noqa: E402


def _pdf(ruta, *, titulo="Informe", idioma="es-MX", mostrar_titulo=True, paginas=1, marcadores=True, color="#000000", pt=11,
         fondo=None, texto="Texto de prueba legible"):
    c = rl_canvas.Canvas(str(ruta), pagesize=LETTER, lang=idioma or None, pageCompression=0)
    if titulo:
        c.setTitle(titulo)
    if mostrar_titulo:
        c.setViewerPreference("DisplayDocTitle", "true")
    for n in range(paginas):
        if marcadores:
            c.bookmarkPage(f"p{n}")
            c.addOutlineEntry(f"Página {n + 1}", f"p{n}", level=0)
        if fondo:
            c.setFillColor(fondo)
            c.rect(50, 680, 300, 40, fill=1, stroke=0)
        c.setFillColor(color)
        c.setFont("Helvetica", pt)
        c.drawString(60, 695, texto)
        c.showPage()
    c.save()
    return str(ruta)


def _crit(informe, sev=ERROR):
    return informe.criterios(sev)


def test_un_pdf_correcto_solo_tiene_el_aviso_de_no_etiquetado(tmp_path):
    inf = auditar_pdf(_pdf(tmp_path / "ok.pdf"))
    assert inf.aprobado, inf.resumen()
    assert [h.criterio for h in inf.avisos] == ["1.3.1"] and "etiquetado" in inf.avisos[0].mensaje
    assert inf.datos["textos_revisados"] >= 1


def test_242_titulo_ausente_o_no_visible(tmp_path):
    assert "2.4.2" in _crit(auditar_pdf(_pdf(tmp_path / "a.pdf", titulo="")))
    assert "2.4.2" in _crit(auditar_pdf(_pdf(tmp_path / "b.pdf", mostrar_titulo=False)))


def test_311_idioma_ausente(tmp_path):
    assert "3.1.1" in _crit(auditar_pdf(_pdf(tmp_path / "a.pdf", idioma="")))


def test_245_varias_paginas_sin_marcadores(tmp_path):
    assert "2.4.5" in _crit(auditar_pdf(_pdf(tmp_path / "a.pdf", paginas=3, marcadores=False)))
    assert "2.4.5" not in _crit(auditar_pdf(_pdf(tmp_path / "b.pdf", paginas=3, marcadores=True)))
    assert "2.4.5" not in _crit(auditar_pdf(_pdf(tmp_path / "c.pdf", paginas=1, marcadores=False)))   # una página no lo necesita


def test_143_gris_claro_sobre_blanco_falla_y_el_limite_pasa(tmp_path):
    inf = auditar_pdf(_pdf(tmp_path / "a.pdf", color="#aaaaaa"))
    assert "1.4.3" in _crit(inf) and "#aaaaaa sobre #ffffff" in inf.errores[0].mensaje
    assert "1.4.3" in _crit(auditar_pdf(_pdf(tmp_path / "b.pdf", color="#777777")))        # 4.48:1
    assert "1.4.3" not in _crit(auditar_pdf(_pdf(tmp_path / "c.pdf", color="#767676")))    # 4.54:1


def test_143_el_fondo_de_color_debajo_del_texto_cuenta(tmp_path):
    # blanco sobre amarillo claro: falla aunque el blanco "sobre la página" sería 21:1 contra negro
    assert "1.4.3" in _crit(auditar_pdf(_pdf(tmp_path / "a.pdf", color="#ffffff", fondo="#fff6e0")))
    # blanco sobre azul marino: pasa
    assert "1.4.3" not in _crit(auditar_pdf(_pdf(tmp_path / "b.pdf", color="#ffffff", fondo="#1a3a5c")))
    # negro sobre azul marino: falla
    assert "1.4.3" in _crit(auditar_pdf(_pdf(tmp_path / "c.pdf", color="#000000", fondo="#1a3a5c")))


def test_143_texto_grande_admite_3_a_1(tmp_path):
    assert "1.4.3" not in _crit(auditar_pdf(_pdf(tmp_path / "a.pdf", color="#777777", pt=20)))   # 4.48:1 con 20 pt (>= 18 pt)
    assert "1.4.3" in _crit(auditar_pdf(_pdf(tmp_path / "b.pdf", color="#999999", pt=20)))       # 2.85:1


def test_144_texto_diminuto_es_aviso(tmp_path):
    inf = auditar_pdf(_pdf(tmp_path / "a.pdf", pt=7))
    assert "1.4.4" in _crit(inf, AVISO) and inf.aprobado


def test_145_pdf_sin_texto_real_es_error(tmp_path):
    c = rl_canvas.Canvas(str(tmp_path / "img.pdf"), pagesize=LETTER, lang="es")
    c.setTitle("Escaneo")
    c.setViewerPreference("DisplayDocTitle", "true")
    c.rect(50, 50, 200, 200, fill=1)       # solo gráficos, ningún texto
    c.showPage()
    c.save()
    assert "1.4.5" in _crit(auditar_pdf(str(tmp_path / "img.pdf")))


def test_el_interprete_respeta_las_matrices_de_transformacion(tmp_path):
    ruta = tmp_path / "t.pdf"
    c = rl_canvas.Canvas(str(ruta), pagesize=LETTER, pageCompression=0)
    c.setFillColor("#1a3a5c")
    c.rect(300, 300, 100, 30, fill=1, stroke=0)
    c.saveState()
    c.translate(310, 310)                  # el texto se dibuja en (0,0) local = dentro del rectángulo
    c.setFillColor("#ffffff")
    c.setFont("Helvetica", 12)
    c.drawString(0, 0, "Dentro")
    c.restoreState()
    c.setFillColor("#000000")
    c.drawString(50, 50, "Fuera")
    c.showPage()
    c.save()
    from pypdf import PdfReader
    t = {x["texto"]: x for x in textos_con_contraste(PdfReader(str(ruta)).pages[0])}
    assert t["Dentro"]["fondo"] == (26, 58, 92) and t["Dentro"]["color"] == (255, 255, 255)
    assert t["Fuera"]["fondo"] == (255, 255, 255)
