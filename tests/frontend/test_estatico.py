"""NFR-03 sobre los archivos de la interfaz (sin navegador): HTML, colores y reglas del JavaScript.

Lo que se puede decidir leyendo los archivos se decide aquí, en cualquier máquina. Lo que depende del
navegador (contraste calculado, reflujo a 320 px, teclado, axe-core) está en ``test_navegador.py``.
Nada de esto sustituye la prueba manual con lector de pantalla (docs/accesibilidad.md).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from accesibilidad.auditoria_html import ParContraste, auditar_css, auditar_html, esquemas_de_color, verificar_pares
from frontend.servidor import CARPETA_ESTATICA

ESTATICOS = sorted(p for p in CARPETA_ESTATICA.iterdir() if p.is_file())
JS = [p for p in ESTATICOS if p.suffix == ".js"]
CSS = (CARPETA_ESTATICA / "app.css").read_text(encoding="utf-8")
INDEX = (CARPETA_ESTATICA / "index.html").read_text(encoding="utf-8")


def _texto(ruta: Path) -> str:
    return ruta.read_text(encoding="utf-8")


# --- HTML ------------------------------------------------------------------------------------------


def test_la_pagina_base_no_tiene_hallazgos():
    informe = auditar_html(INDEX)
    assert not informe.hallazgos, informe.resumen()


def test_la_pagina_base_tiene_idioma_titulo_salto_y_marcas_de_pagina():
    assert re.search(r'<html lang="es(-[A-Z]{2})?">', INDEX) and re.search(r"<title>[^<]+</title>", INDEX)
    assert '<a class="saltar" href="#contenido">' in INDEX and '<main id="contenido" tabindex="-1">' in INDEX
    assert INDEX.count("<h1>") == 1                                                    # siempre hay un h1 desde el primer pintado
    assert '<nav class="nav-principal"' in INDEX and 'aria-label="Principal"' in INDEX and "<header" in INDEX
    assert 'id="anuncios"' in INDEX and 'role="status"' in INDEX and 'aria-live="polite"' in INDEX
    assert "<noscript>" in INDEX                                                       # sin JavaScript se explica, no se queda en blanco
    assert "user-scalable=no" not in INDEX and "maximum-scale" not in INDEX            # 1.4.4: no se bloquea el zoom


def test_la_pagina_base_cumple_la_csp_estricta_no_hay_nada_en_linea():
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", INDEX), "script en línea"
    assert "<style" not in INDEX and not re.search(r"\sstyle\s*=", INDEX), "estilo en línea"
    assert not re.search(r"\son[a-z]+\s*=", INDEX, flags=re.I), "manejador de evento en línea"
    assert not re.search(r"(src|href)=\"https?://", INDEX), "recurso externo"


# --- Colores -------------------------------------------------------------------------------------------

#: Pares de color que la interfaz usa de verdad (ver ``app.css``), en su único esquema claro.
PARES = [
    # texto, 4.5:1 (1.4.3)
    ParContraste("var(--ink)", "var(--page)", "texto", "texto principal sobre la página"),
    ParContraste("var(--ink)", "var(--surface)", "texto", "texto principal sobre tarjetas"),
    ParContraste("var(--ink)", "var(--suave)", "texto", "encabezados de tabla y pestaña en :hover"),
    ParContraste("var(--ink)", "var(--crit-bg)", "texto", "mensaje de error"),
    ParContraste("var(--ink)", "var(--aviso-bg)", "texto", "mensaje de aviso"),
    ParContraste("var(--ink)", "var(--info-bg)", "texto", "mensaje informativo"),
    ParContraste("var(--ink)", "var(--ok-bg)", "texto", "mensaje de éxito"),
    ParContraste("var(--ink2)", "var(--page)", "texto", "texto secundario y pestañas sobre la página"),
    ParContraste("var(--ink2)", "var(--surface)", "texto", "texto secundario sobre tarjetas"),
    ParContraste("var(--ink2)", "var(--line)", "texto", "botón desactivado"),
    ParContraste("var(--muted)", "var(--page)", "texto", "texto atenuado sobre la página"),
    ParContraste("var(--muted)", "var(--surface)", "texto", "texto atenuado y ayudas sobre tarjetas"),
    ParContraste("var(--link)", "var(--surface)", "texto", "enlace y botón secundario sobre tarjetas"),
    ParContraste("var(--link)", "var(--page)", "texto", "enlace sobre la página"),
    ParContraste("var(--link)", "var(--suave)", "texto", "botón secundario y pestaña activa en :hover"),
    ParContraste("var(--sobre-primario)", "var(--primario)", "texto", "botón principal"),
    ParContraste("var(--sobre-primario)", "var(--primario-hover)", "texto", "botón principal en :hover"),
    ParContraste("var(--sobre-nav)", "var(--nav)", "texto", "cabecera"),
    ParContraste("var(--sobre-nav)", "var(--nav-hover)", "texto", "cabecera en :hover y enlace actual"),
    ParContraste("var(--aviso)", "var(--aviso-bg)", "texto", "insignia y franja de aviso"),
    ParContraste("var(--ok)", "var(--ok-bg)", "texto", "insignia de éxito"),
    ParContraste("var(--crit)", "var(--crit-bg)", "texto", "insignia crítica"),
    ParContraste("var(--info)", "var(--info-bg)", "texto", "insignia informativa"),
    ParContraste("var(--crit)", "var(--surface)", "texto", "error de campo"),
    ParContraste("var(--ink2)", "var(--page)", "texto", "insignia neutra"),
    # lo que define un control o una forma, 3:1 (1.4.11)
    ParContraste("var(--borde)", "var(--surface)", "grafico", "borde de campos y botones secundarios"),
    ParContraste("var(--borde)", "var(--page)", "grafico", "borde de campos sobre la página"),
    ParContraste("var(--foco)", "var(--surface)", "grafico", "indicador de foco sobre tarjetas"),
    ParContraste("var(--foco)", "var(--page)", "grafico", "indicador de foco sobre la página"),
    ParContraste("var(--foco-nav)", "var(--nav)", "grafico", "indicador de foco en la cabecera"),
    ParContraste("var(--sobre-nav)", "var(--nav)", "grafico", "borde de los botones de la cabecera"),
    ParContraste("var(--linea)", "var(--surface)", "grafico", "línea de la tendencia"),
    ParContraste("var(--punto-alto)", "var(--surface)", "grafico", "punto crítico de la tendencia"),
    ParContraste("var(--aviso)", "var(--surface)", "grafico", "punto fuera de rango de la tendencia"),
    ParContraste("var(--crit)", "var(--surface)", "grafico", "borde de un campo con error"),
    ParContraste("var(--primario)", "var(--surface)", "grafico", "subrayado de la pestaña actual"),
    # IA: borradores y respuestas del asistente
    ParContraste("var(--ia)", "var(--ia-bg)", "texto", "insignia de contenido generado por IA"),
    ParContraste("var(--ink)", "var(--ia-bg)", "texto", "mensaje de IA"),
    ParContraste("var(--ia)", "var(--surface)", "grafico", "borde de tarjetas y burbujas de IA"),
    ParContraste("var(--primario)", "var(--suave)", "grafico", "borde de la burbuja del médico"),
]


def test_los_colores_cumplen_el_contraste_en_el_esquema_claro():
    """La interfaz es solo clara (blancos y azules, contexto clínico): un único esquema, AA verificado."""
    assert set(esquemas_de_color(CSS)) == {"claro"}
    assert verificar_pares(CSS, PARES) == []


def test_no_hay_tema_oscuro_ni_boton_de_tema():
    assert "prefers-color-scheme:dark" not in CSS.replace(" ", "") and 'data-theme="dark"' not in CSS
    assert "btn-tema" not in INDEX and 'content="light"' in INDEX


def test_el_css_no_tiene_hallazgos_de_accesibilidad():
    hallazgos = auditar_css(CSS)
    assert not hallazgos, "\n".join(str(h) for h in hallazgos)


def test_se_respeta_la_preferencia_de_movimiento_reducido_y_el_foco_visible():
    assert "prefers-reduced-motion:reduce" in CSS.replace(" ", "")
    assert re.search(r":focus-visible\{outline:3px solid var\(--foco\)", CSS)
    assert not re.search(r"outline\s*:\s*(none|0)\b", CSS)


def test_los_objetivos_tactiles_miden_al_menos_2_5_rem():
    for selector in (".btn{", ".btn-barra{", ".nav-principal a{", ".secciones a{", ".marca{"):
        bloque = CSS[CSS.index(selector):].split("}")[0]
        assert re.search(r"min-height:(2\.[5-9]\d*|[3-9])rem", bloque), selector
    assert re.search(r"input,select,textarea\{[^}]*min-height:2\.75rem", CSS)


def test_ningun_texto_se_fija_en_pixeles_salvo_el_de_las_graficas():
    for linea in CSS.splitlines():
        if re.search(r"font-size:\s*[\d.]+px", linea):
            assert ".grafica" in linea, linea       # el texto de un SVG escala con el SVG; el resto con rem


# --- JavaScript ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("ruta", JS, ids=lambda p: p.name)
def test_el_js_no_escribe_html_ni_ejecuta_texto(ruta):
    texto = _texto(ruta)
    for prohibido in (r"\.innerHTML", r"\.outerHTML", r"insertAdjacentHTML", r"document\.write", r"\beval\s*\(", r"new\s+Function\s*\(",
                      r"setTimeout\s*\(\s*['\"]", r"setInterval\s*\(\s*['\"]", r"\.srcdoc", r"javascript:"):
        assert not re.search(prohibido, texto), f"{ruta.name}: {prohibido}"


@pytest.mark.parametrize("ruta", JS, ids=lambda p: p.name)
def test_el_js_no_llama_a_otros_sitios_ni_usa_cookies_ni_guarda_datos_clinicos(ruta):
    texto = _texto(ruta)
    sin_comentarios = re.sub(r"//[^\n]*|/\*.*?\*/", "", texto, flags=re.S)
    assert not re.search(r"https?://", sin_comentarios.replace("http://www.w3.org/2000/svg", "")), ruta.name
    assert "document.cookie" not in texto and "sessionStorage" not in texto and "indexedDB" not in texto
    for uso in re.findall(r"localStorage\.\w+\(([^)]*)\)", texto):
        assert uso.strip().startswith(('"copiloto-tema"', "'copiloto-tema'")), f"{ruta.name}: localStorage con {uso!r}"   # solo el tema


def test_solo_api_js_habla_con_el_servidor():
    for ruta in JS:
        if ruta.name == "api.js":
            continue
        assert not re.search(r"\bfetch\s*\(|XMLHttpRequest|navigator\.sendBeacon|WebSocket|EventSource", _texto(ruta)), ruta.name


def test_toda_peticion_que_cambia_algo_lleva_la_cabecera_propia():
    api = _texto(CARPETA_ESTATICA / "api.js")
    assert "X-Copiloto-Solicitud" in api and 'credentials: "same-origin"' in api


def test_los_modulos_importados_existen_y_estan_todos_alcanzados():
    existentes = {p.name for p in JS}
    importados = set()
    for ruta in JS:
        for destino in re.findall(r"""(?:import[^;]*?from|import)\s*\(?\s*["']\.?/?([\w./-]+\.js)["']""", _texto(ruta)):
            assert Path(destino).name in existentes, f"{ruta.name} importa {destino}, que no existe"
            importados.add(Path(destino).name)
    huerfanos = existentes - importados - {"app.js", "tema.js"}          # app.js y tema.js los carga index.html
    assert not huerfanos, f"módulos que nadie importa: {huerfanos}"


def test_index_solo_carga_archivos_que_existen():
    for ref in re.findall(r'(?:src|href)="/ui/([^"]+)"', INDEX):
        assert (CARPETA_ESTATICA / ref).is_file(), ref


def test_los_textos_dinamicos_se_insertan_como_texto():
    dom = _texto(CARPETA_ESTATICA / "dom.js")
    assert "createTextNode" in dom or "textContent" in dom
    assert "createElementNS" in dom                       # los SVG se construyen por DOM, no por texto
