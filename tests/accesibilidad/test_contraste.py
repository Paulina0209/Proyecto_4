"""NFR-03 — Cálculo de contraste según WCAG 2.1 (1.4.3, 1.4.11)."""
from __future__ import annotations

import pytest

from accesibilidad import contraste as c


def test_blanco_sobre_negro_es_21_a_1_y_mismo_color_es_1_a_1():
    assert c.razon_de_contraste((255, 255, 255), (0, 0, 0)) == pytest.approx(21.0)
    assert c.razon_de_contraste((120, 30, 200), (120, 30, 200)) == pytest.approx(1.0)


def test_la_razon_es_simetrica():
    a, b = (10, 100, 200), (240, 240, 230)
    assert c.razon_de_contraste(a, b) == c.razon_de_contraste(b, a)


@pytest.mark.parametrize("fg,bg,esperado", [
    ("#767676", "#ffffff", 4.54),   # el gris más claro que pasa AA sobre blanco
    ("#777777", "#ffffff", 4.48),   # el de los pies de página de DOC-02: no pasa
    ("#0000ff", "#ffffff", 8.59),
    ("#ff0000", "#ffffff", 4.00),
])
def test_valores_de_referencia_conocidos(fg, bg, esperado):
    assert c.razon_de_contraste(c.parsear_color(fg), c.parsear_color(bg)) == pytest.approx(esperado, abs=0.01)


def test_umbrales_aa():
    assert c.umbral() == 4.5 and c.umbral(grande=True) == 3.0 and c.umbral(texto=False) == 3.0
    assert c.cumple_aa(c.parsear_color("#767676"), (255, 255, 255))
    assert not c.cumple_aa(c.parsear_color("#777777"), (255, 255, 255))
    assert c.cumple_aa(c.parsear_color("#777777"), (255, 255, 255), grande=True)


def test_texto_grande_segun_la_definicion_de_wcag():
    assert c.es_texto_grande(24) and not c.es_texto_grande(23.9)
    assert c.es_texto_grande(18.66, negrita=True) and not c.es_texto_grande(18.66)


@pytest.mark.parametrize("texto,esperado", [
    ("#fff", (255, 255, 255)), ("#0B0B0B", (11, 11, 11)), ("white", (255, 255, 255)),
    ("rgb(10, 20, 30)", (10, 20, 30)), ("rgba(10,20,30,1)", (10, 20, 30)),
])
def test_parsea_formatos(texto, esperado):
    assert c.parsear_color(texto) == esperado


def test_color_translucido_se_compone_sobre_el_fondo_y_sin_fondo_falla():
    assert c.parsear_color("rgba(0,0,0,.5)", (255, 255, 255)) == (128, 128, 128)
    with pytest.raises(ValueError):
        c.parsear_color("rgba(0,0,0,.5)")
    with pytest.raises(ValueError):
        c.parsear_color("azulito")


def test_mejor_tinta_elige_la_de_mas_contraste():
    assert c.mejor_tinta((250, 250, 250)) == (11, 11, 11)
    assert c.mejor_tinta((20, 40, 90)) == (255, 255, 255)


CSS = """
.root{--a:#111;--b:var(--a);--c:#fff}
@media (prefers-color-scheme:dark){:root .root{--a:#eee}}
:root[data-theme="dark"] .root{--c:#000}
"""


def test_extrae_variables_por_alcance_y_resuelve_anidadas():
    bloques = c.extraer_variables_css(CSS)
    assert bloques[".root"] == {"--a": "#111", "--b": "var(--a)", "--c": "#fff"}
    assert any("prefers-color-scheme" in k for k in bloques)
    assert c.resolver("var(--b)", bloques[".root"]) == "#111"
    assert c.resolver("var(--falta, #123)", {}) == "#123"
    with pytest.raises(KeyError):
        c.resolver("var(--falta)", {})
