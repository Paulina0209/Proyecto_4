"""NFR-03 — El tablero ADM-02 cumple WCAG 2.1 AA en lo que se puede comprobar automáticamente.

Tres capas: (1) auditor estático del HTML y contraste de los tokens de color, (2) estructura y
comportamiento por teclado que el diseño promete, (3) Chromium real con axe-core (se omite si no
hay Playwright). Nada de esto sustituye la prueba manual con lector de pantalla (docs/accesibilidad.md).
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from accesibilidad.auditoria_html import ParContraste, auditar_html, verificar_pares
from accesibilidad.navegador import Navegador, NavegadorNoDisponible, auditar_en_navegador, ruta_axe
from administracion import api as api_module
from administracion.metricas_uso import consultar_metricas
from administracion.panel_metricas import _CSS, renderizar_error, renderizar_panel
from tests.administracion.conftest import AHORA, CLAVE
from tests.administracion.test_api_metricas import DIRECTOR, mundo_api, client  # noqa: F401  (fixtures)
from tests.administracion.test_panel_metricas import _con_actividad, equipo  # noqa: F401  (fixtures)

#: Pares de color que el tablero usa de verdad. Quedan fuera, a propósito: --grid y --axis (líneas de
#: cuadrícula y eje: decorativas, cada valor está en las etiquetas, el tooltip y la tabla equivalente) y
#: --ring (borde sutil de las tarjetas, que no delimita ningún control).
PARES_PANEL = [
    ParContraste("var(--ink)", "var(--page)", "texto", "texto principal sobre la página"),
    ParContraste("var(--ink)", "var(--surface)", "texto", "texto principal sobre tarjetas"),
    ParContraste("var(--ink2)", "var(--page)", "texto", "texto secundario sobre la página"),
    ParContraste("var(--ink2)", "var(--surface)", "texto", "texto secundario sobre tarjetas"),
    ParContraste("var(--muted)", "var(--page)", "texto", "texto atenuado sobre la página"),
    ParContraste("var(--muted)", "var(--surface)", "texto", "texto atenuado sobre tarjetas"),
    ParContraste("var(--link)", "var(--surface)", "texto", "enlace sobre tarjetas"),
    ParContraste("var(--warn)", "var(--surface)", "texto", "aviso sobre tarjetas"),
    ParContraste("var(--ink)", "var(--grid)", "texto", "texto sobre el fondo de :hover"),
    # 1.4.11: lo que define una forma o un control
    ParContraste("var(--s1)", "var(--surface)", "grafico", "línea, puntos y columnas"),
    ParContraste("var(--s1)", "var(--track)", "grafico", "relleno del medidor sobre su pista"),
    ParContraste("var(--borde)", "var(--surface)", "grafico", "borde de controles, medidor y segmentos"),
    ParContraste("var(--borde)", "var(--page)", "grafico", "borde de controles sobre la página"),
    ParContraste("var(--foco)", "var(--surface)", "grafico", "indicador de foco sobre tarjetas"),
    ParContraste("var(--foco)", "var(--page)", "grafico", "indicador de foco sobre la página"),
]


def _paginas(mundo):
    """Los estados del tablero que la persona puede ver."""
    mundo.equipo(5, 5)
    sin_datos = renderizar_panel(consultar_metricas(mundo.fuentes(con_expediente=False), mundo.director, ahora=AHORA))
    _con_actividad(mundo)
    con_datos = renderizar_panel(consultar_metricas(mundo.fuentes(), mundo.director, ahora=AHORA))
    return {"con datos": con_datos, "sin fuentes": sin_datos}


# --- (1) Estático -----------------------------------------------------------------------


def test_el_tablero_no_tiene_hallazgos_en_ningun_estado(mundo):
    for nombre, html in _paginas(mundo).items():
        informe = auditar_html(html)
        assert not informe.hallazgos, f"{nombre}:\n{informe.resumen()}"


def test_el_tablero_con_grupos_pequenos_tampoco(mundo):
    mundo.equipo(2, 2)
    mundo.acceso(mundo.oncologos[0], "2026-10-10")
    html = renderizar_panel(consultar_metricas(mundo.fuentes(), mundo.director, ahora=AHORA))
    assert not auditar_html(html).hallazgos


def test_los_colores_del_tablero_cumplen_el_contraste_en_los_tres_esquemas():
    assert verificar_pares(_CSS, PARES_PANEL) == []


def test_la_pagina_de_error_no_tiene_hallazgos():
    html = renderizar_error(["'desde' no puede ser posterior a 'hasta'."], desde="2026-10-10", hasta="2026-10-01")
    assert not auditar_html(html).hallazgos


# --- (2) Estructura y comportamiento prometidos -------------------------------------------


def test_hay_salto_al_contenido_y_el_main_es_su_destino(equipo):
    _con_actividad(equipo)
    html = renderizar_panel(consultar_metricas(equipo.fuentes(), equipo.director, ahora=AHORA))
    assert re.search(r'<a class="saltar" href="#contenido">Saltar al contenido principal</a>', html)
    assert '<main id="contenido" tabindex="-1">' in html


def test_cada_grafico_es_una_sola_parada_de_tabulacion(equipo):
    _con_actividad(equipo)
    html = renderizar_panel(consultar_metricas(equipo.fuentes(), equipo.director, ahora=AHORA))
    for svg in re.findall(r'<svg class="chart.*?</svg>', html, flags=re.S):
        assert len(re.findall(r'class="hit"[^>]*tabindex="0"', svg)) == 1
        assert len(re.findall(r'class="hit"[^>]*tabindex="-1"', svg)) == 4


def test_todas_las_tablas_tienen_titulo_y_encabezados_con_scope(equipo):
    _con_actividad(equipo)
    html = renderizar_panel(consultar_metricas(equipo.fuentes(), equipo.director, ahora=AHORA))
    tablas = re.findall(r"<table.*?</table>", html, flags=re.S)
    assert len(tablas) >= 10
    for t in tablas:
        assert re.search(r'<caption class="vh">[^<]+</caption>', t) and "<th>" not in t


def test_nada_depende_de_title_ni_del_tooltip_para_leer_un_valor(equipo):
    html = renderizar_panel(consultar_metricas(equipo.fuentes(con_expediente=False), equipo.director, ahora=AHORA))
    assert " title=" not in html                                  # un title no se alcanza con teclado ni táctil
    assert 'class="vh">No disponible.' in html                      # el lector dice "No disponible" + el motivo, no "raya"
    assert '<div id="tip" aria-hidden="true">' in html             # el contenido del tooltip ya está en aria-label y tablas


def test_la_barra_de_aceptacion_dice_sus_cifras_y_no_lleva_texto_dentro(equipo):
    _con_actividad(equipo)
    html = renderizar_panel(consultar_metricas(equipo.fuentes(), equipo.director, ahora=AHORA))
    barra = re.search(r'<svg class="barra"[^>]*aria-label="([^"]+)"', html).group(1)
    assert "Aceptadas tal cual: 20 (67 %)" in barra and "No aceptadas" in barra
    assert "<text" not in re.search(r'<svg class="barra".*?</svg>', html, flags=re.S).group(0)


def test_el_estado_seleccionado_no_depende_solo_del_color(equipo):
    html = renderizar_panel(consultar_metricas(equipo.fuentes(), equipo.director, ahora=AHORA))
    sel = re.search(r'<a class="preset sel"[^>]*aria-current="true"><span class="chk" aria-hidden="true">✓</span>', html)
    assert sel


# --- Error de periodo en el navegador: HTML que se entiende (3.3.1, 3.3.3) ---------------------


@pytest.mark.parametrize("params", [{"desde": "2026-10-10", "hasta": "2026-10-01"}, {"desde": "ayer"}])
def test_un_periodo_invalido_en_el_panel_es_una_pagina_que_explica_y_deja_corregir(client, params):
    r = client.get("/metricas/panel", auth=DIRECTOR, params=params)
    assert r.status_code == 400 and r.headers["content-type"].startswith("text/html")
    assert "content-security-policy" in r.headers and r.headers["cache-control"] == "no-store"
    assert 'role="alert"' in r.text and "Cómo corregirlo" in r.text and "AAAA-MM-DD" in r.text
    assert 'aria-invalid="true"' in r.text and 'href="?"' in r.text          # conserva lo escrito y ofrece una salida
    assert not auditar_html(r.text).hallazgos
    if "desde" in params:
        assert f'value="{params["desde"]}"' in r.text


def test_el_json_sigue_siendo_json_en_el_mismo_error(client):
    r = client.get("/metricas", auth=DIRECTOR, params={"desde": "2026-10-10", "hasta": "2026-10-01"})
    assert r.status_code == 400 and r.json()["errores"]


def test_el_error_de_la_pagina_escapa_lo_que_escribio_la_persona(client):
    r = client.get("/metricas/panel", auth=DIRECTOR, params={"desde": '"><script>alert(1)</script>'})
    assert r.status_code == 400 and "<script>alert(1)" not in r.text


# --- (3) Navegador real -------------------------------------------------------------------


@pytest.fixture(scope="module")
def nav():
    try:
        with Navegador() as n:
            yield n
    except NavegadorNoDisponible as exc:
        pytest.skip(str(exc))


@pytest.fixture()
def html_navegador(mundo):
    return _paginas(mundo)["con datos"]


def test_en_chromium_no_hay_errores_en_claro_oscuro_1280_y_320(nav, html_navegador):
    informe = auditar_en_navegador(html_navegador, navegador=nav, axe_js=ruta_axe())
    assert informe.aprobado, informe.resumen()
    assert not informe.avisos, informe.resumen()
    assert all(v["revisados"] > 100 for k, v in informe.datos.items() if k.startswith("contraste"))   # sí revisó texto


def test_el_recorrido_de_tabulacion_es_corto_y_cada_parada_muestra_foco(nav, html_navegador):
    informe = auditar_en_navegador(html_navegador, navegador=nav, anchos=(1280,), esquemas=("light",))
    paradas = informe.datos["paradas_de_tabulacion"]
    assert 8 <= len(paradas) <= 16 and all(p["indicador"] for p in paradas)   # salto + 3 periodos + rango + 3 gráficos + 3 tablas


def test_con_flechas_se_recorre_un_grafico_y_escape_cierra_el_detalle(nav, html_navegador):
    with nav.pagina(html_navegador) as p:
        for _ in range(6):                      # salto, 3 periodos, "Rango personalizado", primer gráfico
            p.keyboard.press("Tab")
        primero = p.evaluate("document.activeElement.getAttribute('aria-label')")
        assert "Usuarios activos" in primero
        assert p.evaluate("getComputedStyle(document.getElementById('tip')).display") == "block"
        p.keyboard.press("ArrowRight")
        segundo = p.evaluate("document.activeElement.getAttribute('aria-label')")
        assert segundo != primero and "Usuarios activos" in segundo
        p.keyboard.press("End")
        assert p.evaluate("document.activeElement.getAttribute('data-i')") == "4"
        p.keyboard.press("Home")
        assert p.evaluate("document.activeElement.getAttribute('data-i')") == "0"
        p.keyboard.press("Escape")
        assert p.evaluate("getComputedStyle(document.getElementById('tip')).display") == "none"
        p.keyboard.press("Tab")                 # una sola parada por gráfico: sigue "Ver como tabla"
        assert p.evaluate("document.activeElement.tagName") == "SUMMARY"


def test_el_tooltip_se_puede_alcanzar_con_el_puntero_sin_que_desaparezca(nav, html_navegador):
    """WCAG 1.4.13: descartable (Esc), alcanzable con el puntero y persistente mientras se use."""
    with nav.pagina(html_navegador) as p:
        x, y = p.evaluate("(()=>{var r=document.querySelectorAll('.hit')[2].getBoundingClientRect();return [r.left+r.width/2,r.top+40]})()")
        p.mouse.move(x, y)
        assert p.evaluate("getComputedStyle(document.getElementById('tip')).display") == "block"
        tx, ty = p.evaluate("(()=>{var r=document.getElementById('tip').getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]})()")
        p.mouse.move(tx, ty, steps=6)
        p.wait_for_timeout(500)
        assert p.evaluate("getComputedStyle(document.getElementById('tip')).display") == "block"
        p.mouse.move(2, 2)
        p.wait_for_timeout(500)
        assert p.evaluate("getComputedStyle(document.getElementById('tip')).display") == "none"


def test_en_320_px_las_tablas_anchas_se_desplazan_y_se_alcanzan_con_teclado(nav, html_navegador):
    with nav.pagina(html_navegador, ancho=320) as p:
        regiones = p.evaluate("[].map.call(document.querySelectorAll('[role=region][tabindex=\"0\"]'), e => e.getAttribute('aria-label'))")
        assert regiones and all("se desplaza horizontalmente" in r for r in regiones)
    with nav.pagina(html_navegador, ancho=1280) as p:
        assert p.evaluate("document.querySelectorAll('[role=region][tabindex]').length") == 0   # en pantalla ancha no hay paradas de más


def test_la_pagina_de_error_pasa_en_el_navegador(nav):
    html = renderizar_error(["'desde' no puede ser posterior a 'hasta'."], desde="2026-10-10", hasta="2026-10-01")
    informe = auditar_en_navegador(html, navegador=nav, axe_js=ruta_axe())
    assert informe.aprobado and not informe.avisos, informe.resumen()
