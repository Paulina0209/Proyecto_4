"""NFR-03 — El auditor estático detecta cada incumplimiento y deja pasar el HTML correcto."""
from __future__ import annotations

import pytest

from accesibilidad.auditoria_html import (ERROR, AVISO, ParContraste, auditar_css, auditar_html, esquemas_de_color, verificar_pares)

BUENA = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Resumen</title></head>
<body><main><h1>Resumen</h1><h2>Datos</h2>
<nav aria-label="Periodo"><a href="?d=7">Últimos 7 días</a></nav>
<form><label for="d">Desde</label><input id="d" type="date" name="desde"><button type="submit">Aplicar</button></form>
<table><caption>Pacientes</caption><thead><tr><th scope="col">Nombre</th></tr></thead><tbody><tr><td>Ana</td></tr></tbody></table>
<svg role="img" aria-label="Gráfico de uso"><line x1="0" x2="1" y1="0" y2="1"/></svg>
<details><summary>Ver como tabla</summary><p>x</p></details>
<img src="a.png" alt="Logotipo del hospital"></main></body></html>"""


def _crit(html, sev=ERROR):
    return auditar_html(html).criterios(sev)


def test_un_documento_correcto_no_tiene_hallazgos():
    inf = auditar_html(BUENA)
    assert inf.aprobado and not inf.hallazgos, inf.resumen()
    assert inf.resumen().startswith("Sin hallazgos")


def _sin(html, quitar, poner=""):
    assert quitar in html
    return html.replace(quitar, poner)


def test_311_idioma():
    assert "3.1.1" in _crit(_sin(BUENA, ' lang="es"'))
    assert "3.1.1" in _crit(_sin(BUENA, 'lang="es"', 'lang="español bonito"'))


def test_242_titulo():
    assert "2.4.2" in _crit(_sin(BUENA, "<title>Resumen</title>"))
    assert "2.4.2" in _crit(_sin(BUENA, "<title>Resumen</title>", "<title> </title>"))


def test_144_zoom_bloqueado():
    assert "1.4.4" in _crit(_sin(BUENA, "initial-scale=1", "initial-scale=1, user-scalable=no"))
    assert "1.4.4" in _crit(_sin(BUENA, "initial-scale=1", "initial-scale=1, maximum-scale=1.0"))
    assert "1.4.4" not in _crit(_sin(BUENA, "initial-scale=1", "initial-scale=1, maximum-scale=5"))


def test_221_refresco_automatico():
    assert "2.2.1" in _crit(_sin(BUENA, "<title>", '<meta http-equiv="refresh" content="30"><title>'))


def test_241_y_131_main():
    assert "2.4.1" in _crit(BUENA.replace("<main>", "<div>").replace("</main>", "</div>"))
    assert "1.3.1" in _crit(_sin(BUENA, "</main>", "</main><main>otro</main>"))


def test_131_encabezados():
    assert "1.3.1" in _crit(_sin(BUENA, "<h1>Resumen</h1>", ""))                 # sin h1
    assert "1.3.1" in _crit(_sin(BUENA, "<h2>Datos</h2>", "<h3>Datos</h3>"))      # salto h1 → h3
    assert "2.4.6" in _crit(_sin(BUENA, "<h2>Datos</h2>", "<h2> </h2>"))          # vacío
    assert "1.3.1" in auditar_html(_sin(BUENA, "<h2>Datos</h2>", "<h1>Otro</h1>")).criterios(AVISO)
    assert auditar_html(_sin(BUENA, "<h2>Datos</h2>", "<h2>A</h2><h3>B</h3><h2>C</h2>")).aprobado   # bajar de nivel no es salto


def test_111_imagenes_y_svg():
    assert "1.1.1" in _crit(_sin(BUENA, ' alt="Logotipo del hospital"'))
    assert auditar_html(_sin(BUENA, 'alt="Logotipo del hospital"', 'alt=""')).aprobado     # decorativa: correcto
    assert "1.1.1" in _crit(_sin(BUENA, ' role="img" aria-label="Gráfico de uso"'))
    assert auditar_html(_sin(BUENA, ' role="img" aria-label="Gráfico de uso"', ' aria-hidden="true"')).aprobado
    assert "1.1.1" in auditar_html(_sin(BUENA, 'alt="Logotipo del hospital"', 'alt="foto.png"')).criterios(AVISO)


def test_412_nombre_de_controles():
    assert "4.1.2" in _crit(_sin(BUENA, ">Últimos 7 días</a>", "></a>"))
    assert "4.1.2" in _crit(_sin(BUENA, ">Aplicar</button>", "></button>"))
    assert "4.1.2" in _crit(_sin(BUENA, "<summary>Ver como tabla</summary>", "<summary></summary>"))
    assert "4.1.2" in _crit(_sin(BUENA, "</main>", '<div role="button" tabindex="0"></div></main>'))
    # el nombre puede venir de aria-label o de una imagen con alt
    assert auditar_html(_sin(BUENA, ">Últimos 7 días</a>", '><img src="x.png" alt="Siete días"></a>')).aprobado


def test_332_campos_sin_etiqueta():
    assert "3.3.2" in _crit(_sin(BUENA, '<label for="d">Desde</label>'))
    assert auditar_html(_sin(BUENA, '<label for="d">Desde</label><input id="d"', '<label>Desde <input id="d"').replace(
        'name="desde"><button', 'name="desde"></label><button')).aprobado           # etiqueta envolvente
    solo_placeholder = _sin(BUENA, '<label for="d">Desde</label>', "").replace('id="d"', 'id="d" placeholder="Desde"')
    assert "3.3.2" not in _crit(solo_placeholder) and "3.3.2" in auditar_html(solo_placeholder).criterios(AVISO)


def test_135_autocomplete_en_datos_personales():
    campo = '<label for="c">Correo</label><input id="c" type="email" name="email">'
    assert "1.3.5" in _crit(_sin(BUENA, "</form>", campo + "</form>"))
    assert auditar_html(_sin(BUENA, "</form>", campo.replace('name="email"', 'name="email" autocomplete="email"') + "</form>")).aprobado


def test_131_referencias_aria_y_for_rotas():
    assert "1.3.1" in _crit(_sin(BUENA, 'aria-label="Periodo"', 'aria-labelledby="no-existe"'))
    assert "1.3.1" in _crit(_sin(BUENA, 'for="d"', 'for="otro"'))


def test_411_ids_duplicados():
    assert "4.1.1" in _crit(_sin(BUENA, "<p>x</p>", '<p id="d">x</p>'))


def test_412_rol_invalido_y_foco_en_aria_hidden():
    assert "4.1.2" in _crit(_sin(BUENA, "</main>", '<div role="boton">x</div></main>'))
    assert "4.1.2" in _crit(_sin(BUENA, "</main>", '<div aria-hidden="true"><a href="/x">ir</a></div></main>'))


def test_243_tabindex_positivo():
    assert "2.4.3" in _crit(_sin(BUENA, "</main>", '<a href="/x" tabindex="3">ir</a></main>'))
    assert auditar_html(_sin(BUENA, "</main>", '<a href="/x" tabindex="0">ir</a></main>')).aprobado


def test_131_tablas():
    assert "1.3.1" in _crit(_sin(BUENA, '<th scope="col">', "<th>"))
    assert "1.3.1" in _crit(_sin(BUENA, "<thead><tr><th scope=\"col\">Nombre</th></tr></thead>", ""))
    assert "1.3.1" in auditar_html(_sin(BUENA, "<caption>Pacientes</caption>", "")).criterios(AVISO)


def test_244_enlace_vago_es_aviso():
    inf = auditar_html(_sin(BUENA, "</main>", '<a href="/x">haz clic aquí</a></main>'))
    assert inf.aprobado and "2.4.4" in inf.criterios(AVISO)


def test_contenido_oculto_no_se_audita_como_visible():
    oculto = _sin(BUENA, "</main>", '<div hidden><a href="/x"></a><img src="a.png"></div></main>')
    assert auditar_html(oculto).aprobado


def test_un_fragmento_sin_html_no_exige_idioma_ni_titulo():
    assert auditar_html('<section><h2>Algo</h2><p>texto</p></section>').aprobado


# --- CSS ------------------------------------------------------------------------------


def test_247_outline_none_sin_sustituto_es_error():
    assert any(h.criterio == "2.4.7" for h in auditar_css("a{outline:none}"))
    assert any(h.criterio == "2.4.7" for h in auditar_css("button:focus{outline:0}"))
    assert any(h.criterio == "2.4.7" for h in auditar_css(".hit{outline:none}.hit:focus-visible{color:red}"))


def test_247_outline_none_con_sustituto_es_correcto():
    assert not auditar_css(".hit{outline:none}.hit:focus-visible{stroke:#00f;stroke-width:2}")
    assert not auditar_css("a{outline:none}a:focus-visible{outline:2px solid #00f}")
    assert not auditar_css("a{color:red}")


def test_144_texto_menor_de_12_px_es_aviso():
    hall = auditar_css(".t{font-size:10px}.u{font-size:8pt}.v{font-size:12px}.w{font-size:1rem}")
    assert [h.severidad for h in hall] == [AVISO, AVISO] and {h.criterio for h in hall} == {"1.4.4"}


def test_el_auditor_revisa_el_style_incrustado():
    html = BUENA.replace("</head>", "<style>a{outline:none}</style></head>")
    assert "2.4.7" in _crit(html)


# --- Contraste de tokens ---------------------------------------------------------------

CSS_TOKENS = """
.r{--fondo:#ffffff;--texto:#767676;--tenue:#999999;--marca:#2a78d6;--velo:rgba(0,0,0,.5)}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])) .r{--fondo:#111111;--texto:#aaaaaa;--tenue:#444444}}
:root[data-theme="dark"] .r{--fondo:#111111;--texto:#aaaaaa;--tenue:#444444}
"""


def test_los_tres_esquemas_se_leen_del_css():
    esq = esquemas_de_color(CSS_TOKENS)
    assert set(esq) == {"claro", "oscuro (sistema)", "oscuro (manual)"}
    assert esq["oscuro (sistema)"]["--marca"] == "#2a78d6" and esq["oscuro (manual)"]["--fondo"] == "#111111"


def test_pares_que_cumplen_no_dan_hallazgos():
    pares = [ParContraste("var(--texto)", "var(--fondo)", "texto", "texto principal"),
             ParContraste("var(--marca)", "var(--fondo)", "grafico", "línea del gráfico")]
    # en oscuro --marca (#2a78d6) sobre #111 también pasa 3:1
    assert verificar_pares(CSS_TOKENS, pares) == []


def test_un_par_que_falla_se_reporta_por_esquema_con_la_razon():
    hall = verificar_pares(CSS_TOKENS, [ParContraste("var(--tenue)", "var(--fondo)", "texto", "texto tenue")])
    assert len(hall) == 3 and all(h.criterio == "1.4.3" and h.severidad == ERROR for h in hall)
    assert any("[claro]" in h.mensaje and "texto tenue" in h.mensaje and ":1" in h.mensaje for h in hall)


def test_el_mismo_color_pasa_como_texto_grande_pero_no_como_texto_normal():
    css = ".r{--f:#fff;--t:#777777}"
    assert verificar_pares(css, [ParContraste("var(--t)", "var(--f)", "texto")])
    assert not verificar_pares(css, [ParContraste("var(--t)", "var(--f)", "texto_grande")])


def test_grafico_usa_el_criterio_1411_y_translucidos_se_componen_sobre_el_fondo():
    css = ".r{--f:#ffffff;--g:#cccccc;--velo:rgba(0,0,0,.5)}"
    assert verificar_pares(css, [ParContraste("var(--g)", "var(--f)", "grafico")])[0].criterio == "1.4.11"
    assert not verificar_pares(css, [ParContraste("var(--velo)", "var(--f)", "grafico")])   # 50 % negro sobre blanco = #808080 → 3.95


def test_un_token_inexistente_es_un_error_no_un_silencio():
    hall = verificar_pares(".r{--f:#fff}", [ParContraste("var(--no-existe)", "var(--f)", "texto", "algo")])
    assert hall and hall[0].severidad == ERROR and "no se pudo resolver" in hall[0].mensaje
