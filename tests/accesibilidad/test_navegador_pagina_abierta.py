"""``auditar_pagina_abierta`` y las correcciones de la compuerta que salieron al auditar la interfaz web.

Las que no necesitan navegador corren siempre; las de Chromium se omiten si no hay Playwright.
"""
from __future__ import annotations

import base64
import hashlib

import pytest

from accesibilidad.navegador import Navegador, NavegadorNoDisponible, _aro_del_navegador, auditar_pagina_abierta


def _parada(sel="input#f", indicador=True, tipo="date"):
    return {"sel": sel, "nombre": "", "indicador": indicador, "tipo": tipo}


def test_un_campo_de_fecha_nativo_acepta_la_parada_del_boton_del_calendario_si_las_anteriores_tenian_aro():
    assert _aro_del_navegador(_parada(indicador=False), [_parada(), _parada()])


def test_pero_no_si_el_autor_quito_el_foco_en_las_paradas_anteriores():
    assert not _aro_del_navegador(_parada(indicador=False), [_parada(indicador=False)])


def test_ni_en_un_campo_que_no_es_de_fecha_ni_si_es_otro_elemento():
    assert not _aro_del_navegador(_parada(indicador=False, tipo="text"), [_parada(tipo="text")])
    assert not _aro_del_navegador(_parada(indicador=False), [_parada(sel="input#otro")])
    assert not _aro_del_navegador(_parada(indicador=False), [])


@pytest.fixture(scope="module")
def nav():
    try:
        with Navegador() as n:
            yield n
    except NavegadorNoDisponible as exc:
        pytest.skip(str(exc))


# Un texto recortado por un contenedor de alto fijo: con más espaciado entre letras y líneas deja de caber (1.4.12).
ESTILO = "#c{height:1.6em;overflow:hidden;width:12em}"
RECORTADO = '<div id="c">Texto que apenas cabe en una línea justa</div>'
#: La política solo admite el estilo de la propia página (por su hash): un <style> inyectado por la prueba se rechazaría.
HASH_ESTILO = base64.b64encode(hashlib.sha256(ESTILO.encode()).digest()).decode()
CSP = f'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'sha256-{HASH_ESTILO}\'">'


def _pagina(cuerpo: str, con_csp: bool, estilo: str = ESTILO) -> str:
    return (f'<!doctype html><html lang="es"><head><meta charset="utf-8">{CSP if con_csp else ""}<title>t</title>'
            f'<style>{estilo}</style></head><body><main>{cuerpo}</main></body></html>')


@pytest.mark.parametrize("con_csp", [False, True], ids=["sin CSP", "con CSP estricta"])
def test_el_espaciado_se_aplica_tambien_cuando_la_pagina_tiene_csp(nav, con_csp):
    with nav.pagina(_pagina(RECORTADO, con_csp)) as page:
        informe = auditar_pagina_abierta(page, etiqueta="[prueba]")
    errores = [h for h in informe.hallazgos if h.criterio == "1.4.12" and h.severidad == "error"]
    avisos_de_no_aplicado = [h for h in informe.hallazgos if "no se pudo aplicar" in h.mensaje]
    assert not avisos_de_no_aplicado
    assert errores, informe.resumen()                          # detecta el recorte: la hoja de prueba sí se aplicó


def test_auditar_pagina_abierta_usa_el_ancho_de_la_ventana_y_no_cierra_la_pagina(nav):
    html = _pagina('<p>Hola</p><div id="ancho"></div>', False, estilo="#ancho{width:600px;height:10px}")
    with nav.pagina(html, ancho=320) as page:
        informe = auditar_pagina_abierta(page)
        assert any(h.criterio == "1.4.10" for h in informe.hallazgos)      # 600 px en una ventana de 320: se desplaza
        assert page.evaluate("document.title") == "t"                       # la página sigue abierta y usable
