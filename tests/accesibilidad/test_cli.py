"""NFR-03 — La línea de comandos devuelve 0 sin errores y 1 con errores (sirve como compuerta de CI)."""
from __future__ import annotations

import pytest

pytest.importorskip("pypdf")

from accesibilidad.__main__ import main  # noqa: E402


def test_html_limpio_devuelve_0_y_html_con_errores_devuelve_1(tmp_path, capsys):
    bueno = tmp_path / "bueno.html"
    bueno.write_text('<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Hola</title></head>'
                     '<body><main><h1>Hola</h1></main></body></html>', encoding="utf-8")
    malo = tmp_path / "malo.html"
    malo.write_text("<html><body><img src='x.png'></body></html>", encoding="utf-8")
    assert main(["html", str(bueno)]) == 0
    assert main(["html", str(malo)]) == 1
    salida = capsys.readouterr().out
    assert "SIN ERRORES" in salida and "WCAG 1.1.1" in salida and "WCAG 3.1.1" in salida and "lector de pantalla" in salida


def test_pdf_con_errores_devuelve_1(tmp_path):
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(tmp_path / "x.pdf"), pagesize=LETTER)
    c.drawString(50, 50, "sin idioma")
    c.save()
    assert main(["pdf", str(tmp_path / "x.pdf")]) == 1


def test_el_sistema_completo_audita_limpio(capsys):
    """Compuerta de regresión: lo que el sistema genera hoy (tablero, PDF y HTML de DOC-02) no tiene errores."""
    assert main(["sistema"]) == 0
    salida = capsys.readouterr().out
    assert salida.count("SIN ERRORES") == 3 and "ERROR(ES)" not in salida
