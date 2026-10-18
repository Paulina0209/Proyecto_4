"""ADM-02 — El tablero HTML (AC1 cifras visibles, AC3 presentación cuidadosa de la aceptación de IA)."""
from __future__ import annotations

import re

import pytest

from administracion import metricas_uso as met
from administracion.metricas_uso import FuentesMetricas, consultar_metricas
from administracion.panel_metricas import renderizar_panel
from tests.administracion.conftest import AHORA
from tests.administracion.test_metricas_uso import EN, EN2


@pytest.fixture()
def equipo(mundo):
    mundo.equipo(5, 5)
    return mundo


def _panel(mundo, **kw):
    fuentes = kw.pop("fuentes", None) or mundo.fuentes()
    return renderizar_panel(consultar_metricas(fuentes, mundo.director, ahora=AHORA, **kw))


def _con_actividad(m):
    for u in m.oncologos[:3]:
        m.acceso(u, EN)
    for i in range(30):
        m.decision(m.oncologos[i % 5], EN, "accept" if i % 3 else "reject", "FOLFOX", "FOLFOX" if i % 3 else None)
    m.alerta(EN)
    m.alerta(EN2)
    m.nota_aprobada(EN, 4)


def test_es_un_documento_completo_en_espanol_con_las_secciones_principales(equipo):
    _con_actividad(equipo)
    html = _panel(equipo)
    assert html.startswith("<!doctype html>") and '<html lang="es">' in html and "<title>Uso del copiloto oncológico</title>" in html
    for texto in ("Usuarios clínicos que usaron el sistema", "Tiempo ahorrado (estimado)", "Alertas generadas", "Pacientes atendidos",
                  "Qué pasa con las recomendaciones de la IA", "Detalle de adopción", "Cómo se estima el tiempo ahorrado"):
        assert texto in html


def test_muestra_las_cifras_calculadas(equipo):
    _con_actividad(equipo)
    html = _panel(equipo)
    assert "30 %" in html          # 3 de 10 usuarios clínicos
    assert "3 de 10 oncólogos y personal de enfermería" in html
    assert re.search(r'Alertas generadas</h2><p class="valor-tile">2<', html)  # 2 alertas


def test_no_carga_nada_de_internet(equipo):
    html = _panel(equipo)
    assert not re.search(r'(?:src|href|action)\s*=\s*"https?://', html)
    assert "<link" not in html and "@import" not in html and "url(http" not in html


def test_los_textos_de_los_datos_se_escapan(equipo, tmp_path):
    ruta = tmp_path / "c.yaml"
    ruta.write_text("coeficientes:\n" + "".join(
        f'  {k}:\n    descripcion: "<img src=x onerror=alert(2)>"\n    minutos_min: 1\n    minutos_max: 2\n    origen: "<script>alert(1)</script>"\n'
        for k in met._CLAVES_COEFICIENTES), encoding="utf-8")
    coef = met.cargar_coeficientes(ruta)
    html = renderizar_panel(consultar_metricas(equipo.fuentes(), equipo.director, ahora=AHORA, coeficientes=coef))
    assert "<script>alert(1)" not in html and "<img src=x" not in html
    assert "&lt;script&gt;alert(1)" in html and "&lt;img src=x" in html


def test_los_tooltips_usan_textContent_nunca_innerHTML(equipo):
    html = _panel(equipo)
    assert "innerHTML" not in html and "textContent" in html


def test_cada_grafico_tiene_su_tabla_equivalente(equipo):
    _con_actividad(equipo)
    html = _panel(equipo)
    assert html.count('<details class="tabla-vista">') == html.count('<svg class="chart') == 3
    for encabezado in ("Usuarios activos", "Alertas generadas", "Horas ahorradas (estimado)"):
        assert encabezado in html


def test_la_zona_de_hover_existe_por_semana_y_es_accesible_con_teclado(equipo):
    html = _panel(equipo)
    assert html.count('class="hit"') == 5 * 3  # 5 semanas × 3 gráficos
    assert 'tabindex="0"' in html and 'aria-label="' in html


def test_modo_oscuro_y_contraste_forzado_estan_cubiertos(equipo):
    html = _panel(equipo)
    assert "prefers-color-scheme:dark" in html and 'data-theme="dark"' in html
    assert "forced-colors:active" in html and 'name="color-scheme"' in html


def test_tiene_filtros_de_periodo_y_marca_el_activo(equipo):
    html = _panel(equipo)
    assert "Últimos 7 días" in html and "Últimos 90 días" in html and "Rango personalizado" in html
    assert re.search(r'class="preset sel" href="\?desde=2026-09-18&amp;hasta=2026-10-17" aria-current="true"', html)


# --- AC1: sin datos no es cero -------------------------------------------------


def test_una_fuente_no_disponible_se_ve_como_no_disponible_y_no_como_cero(equipo):
    html = _panel(equipo, fuentes=equipo.fuentes(con_expediente=False))
    assert "No disponible" in html and "Sin datos disponibles para graficar" in html
    for etiqueta in ("Tiempo ahorrado (estimado)", "Alertas generadas"):  # sin fuente: "—", no "0"
        assert re.search(re.escape(etiqueta) + r'</h2><p class="valor-tile"><span class="nd"', html)
    assert 'class="nd"' in html and "Fuentes de datos sin conectar" in html and "alertas_laboratorio" in html


def test_un_cero_real_se_muestra_como_cero(equipo):
    assert re.search(r'class="valor-tile">0<', _panel(equipo))


def test_el_tiempo_se_rotula_como_estimacion_con_sus_supuestos_a_la_vista(equipo):
    _con_actividad(equipo)
    html = _panel(equipo)
    assert "Estimación (rango), no medición" in html
    assert "Supuesto por defecto (sin medir)" in html and "COPILOTO_COEFICIENTES_TIEMPO" in html
    assert "Subestimada" not in html


def test_avisa_si_la_estimacion_es_una_subestimacion(equipo):
    import sqlite3
    from tests.administracion.conftest import RAIZ
    solo_notas = sqlite3.connect(":memory:")
    solo_notas.executescript((RAIZ / "ia_clinica/review/schema.sql").read_text(encoding="utf-8"))
    html = _panel(equipo, fuentes=FuentesMetricas(equipo.usuarios, [solo_notas]))
    assert "Subestimada" in html and "subestimación" in html


# --- AC3: presentación cuidadosa de la aceptación de IA --------------------------


def test_la_aceptacion_siempre_va_con_su_nota_y_sin_cifra_destacada(equipo):
    _con_actividad(equipo)
    html = _panel(equipo)
    assert "Cómo leer esto" in html and "tasa baja no es negativa" in html
    assert html.count('class="hero-cifra"') == 1  # la única cifra grande es la adopción


def test_la_aceptacion_se_dibuja_como_distribucion_con_leyenda_y_conteos(equipo):
    _con_actividad(equipo)
    html = _panel(equipo)
    assert html.count('class="seg seg-') >= 2
    assert "Aceptadas tal cual" in html and "Aceptadas con cambios" in html and "No aceptadas" in html
    assert "30 recomendaciones en el periodo" in html


def test_los_colores_de_la_aceptacion_no_son_de_estado(equipo):
    """Aceptar no es 'bueno' ni rechazar 'malo': una sola gama ordinal, nada de verde/rojo."""
    html = _panel(equipo)
    estilos = html[html.index("<style>"):html.index("</style>")]
    for clase in ("seg-0", "seg-1", "seg-2"):
        regla = re.search(r"\." + clase + r"\{fill:([^}]+)\}", estilos).group(1)
        assert regla in ("var(--o1)", "var(--o2)", "var(--o3)")
    for hex_estado in ("#0ca30c", "#d03b3b", "#ec835a", "#fab219"):
        assert not re.search(r"\.(seg|sw)-[012]\{[^}]*" + hex_estado, estilos)


def test_si_se_suprime_no_hay_barras_ni_porcentajes_de_esa_aceptacion(equipo):
    for i in range(10):
        equipo.decision(equipo.oncologos[0], EN)
    html = _panel(equipo)
    assert "personas concretas" in html
    assert 'class="seg seg-' not in html and "Aceptadas tal cual" not in html


def test_el_desglose_de_grupos_pequenos_se_oculta(mundo):
    mundo.equipo(2, 2)
    mundo.acceso(mundo.oncologos[0], EN)
    html = renderizar_panel(consultar_metricas(mundo.fuentes(), mundo.director, ahora=AHORA))
    assert html.count("Grupo pequeño: no se muestra") == 2


def test_declara_que_no_hay_datos_por_persona_ni_sirve_para_evaluar_personas(equipo):
    html = _panel(equipo)
    assert "no contiene datos por médico" in html and "no sirve para evaluar a personas" in html
