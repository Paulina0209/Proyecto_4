"""ADM-02 — Tablero HTML de las métricas de uso (una sola página, sin dependencias).

``renderizar_panel(metricas)`` devuelve un documento HTML completo con todo
en línea (estilos, gráficos SVG y un script mínimo para el tooltip): no carga
nada de internet, así que sirve igual dentro de una intranet hospitalaria.

Decisiones de presentación (la nota de UX de la historia manda):

    - La aceptación de IA NO tiene un número destacado. Se muestra como una
      distribución (qué pasó con las recomendaciones), siempre acompañada de la
      nota de interpretación, y con colores ordinales neutros de una sola gama
      (nada en verde/rojo: aceptar no es "bueno" ni rechazar "malo").
    - Una cifra no disponible se escribe "—" con su motivo, nunca "0".
    - El tiempo ahorrado se rotula "estimado", se muestra como rango y sus
      supuestos están en la misma página.
    - Cada gráfico tiene su tabla equivalente (``<details>``), y el tooltip
      nunca es la única vía para leer un valor. Modo oscuro y contraste forzado
      incluidos. Los textos de los datos pasan siempre por ``html.escape``.
"""

from __future__ import annotations

import html
import json
from datetime import date, datetime, timedelta
from typing import List, Optional, Sequence, Tuple

from administracion.metricas_uso import AceptacionDominio, MetricasUso, SemanaUso

_MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
_ETIQUETAS_ACCION = {"ver": "Expedientes consultados", "editar": "Expedientes editados", "exportar": "Expedientes exportados"}
_ETIQUETAS_ROL = {"oncologo": "Oncología", "enfermeria": "Enfermería"}

# Gráficos: lienzo común (viewBox) y márgenes.
_W, _H = 360, 190
_ML, _MR, _MT, _MB = 38, 14, 14, 30


def _e(texto: object) -> str:
    return html.escape(str(texto), quote=True)


# --------------------------------------------------------------------------
# Formato
# --------------------------------------------------------------------------


def _fecha(iso: str) -> date:
    return date.fromisoformat(iso[:10])


def _corta(d: date) -> str:
    return f"{d.day} {_MESES[d.month - 1]}"


def _larga(d: date) -> str:
    return f"{d.day} {_MESES[d.month - 1]} {d.year}"


def _rango_fechas(desde: str, hasta: str) -> str:
    a, b = _fecha(desde), _fecha(hasta)
    return f"{_corta(a)} – {_larga(b)}" if a.year == b.year else f"{_larga(a)} – {_larga(b)}"


def _n(valor: Optional[float], decimales: int = 0) -> str:
    return "—" if valor is None else f"{valor:,.{decimales}f}"


def _pct(valor: Optional[float]) -> str:
    return "—" if valor is None else f"{valor * 100:.0f} %"


def _h(valor: Optional[float]) -> str:
    if valor is None:
        return "—"
    return f"{valor:,.0f}" if valor >= 10 else f"{valor:,.1f}"


def _rango_h(minimo: Optional[float], maximo: Optional[float]) -> str:
    if minimo is None or maximo is None:
        return "—"
    return f"{_h(minimo)}–{_h(maximo)} h"


def _delta(actual: Optional[float], anterior: Optional[float], unidad: str = "", escala: float = 1.0, decimales: int = 0) -> str:
    """Cambio contra el periodo anterior, con signo y flecha; en gris: ni más ni menos es 'bueno' por sí solo."""
    if actual is None or anterior is None:
        return '<span class="delta">Sin periodo anterior comparable</span>'
    cambio = (actual - anterior) * escala
    if round(cambio, decimales) == 0:
        return f'<span class="delta">= igual que el periodo anterior</span>'
    flecha = "▲" if cambio > 0 else "▼"
    texto = f"{abs(cambio):,.{decimales}f}{unidad}"
    return f'<span class="delta"><span aria-hidden="true">{flecha}</span> {"+" if cambio > 0 else "−"}{_e(texto)} vs. periodo anterior</span>'


def _nd(motivo: str = "Fuente no disponible") -> str:
    """"—" visible; el lector de pantalla lee "No disponible" y el motivo (un ``title`` no se alcanza con teclado ni táctil)."""
    return f'<span class="nd"><span aria-hidden="true">—</span><span class="vh">No disponible. {_e(motivo)}</span></span>'


# --------------------------------------------------------------------------
# Gráficos SVG
# --------------------------------------------------------------------------


def _techo(maximo: float, entero: bool) -> float:
    """Límite superior 'redondo' del eje (1, 2, 5, 10, 20, 50...)."""
    if maximo <= 0:
        return 1.0
    pot = 10 ** (len(str(int(maximo))) - 1) if maximo >= 1 else 1
    for m in (1, 2, 5, 10):
        if maximo <= m * pot:
            return float(m * pot)
    return float(10 * pot)


def _escalas(n: int, techo: float):
    ancho, alto = _W - _ML - _MR, _H - _MT - _MB

    def x(i: int) -> float:
        return _ML + ancho * (i + 0.5) / max(n, 1)

    def y(v: float) -> float:
        return _MT + alto * (1 - v / techo)

    return x, y, ancho / max(n, 1)


def _ejes(techo: float, y, n: int, etiquetas: Sequence[str], x, entero: bool, fmt) -> str:
    partes = []
    ticks = [0.0, techo / 2, techo]
    if entero:
        ticks = [t for t in ticks if float(t).is_integer()]
    for t in ticks:
        partes.append(f'<line class="grid" x1="{_ML}" x2="{_W - _MR}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>')
        partes.append(f'<text class="tick" x="{_ML - 6}" y="{y(t) + 4:.1f}" text-anchor="end">{_e(fmt(t))}</text>')
    partes.append(f'<line class="base" x1="{_ML}" x2="{_W - _MR}" y1="{y(0):.1f}" y2="{y(0):.1f}"/>')
    paso = 1 if n <= 7 else 2 if n <= 14 else 4
    for i, et in enumerate(etiquetas):
        if i % paso == 0:
            partes.append(f'<text class="tick" x="{x(i):.1f}" y="{_H - 10}" text-anchor="middle">{_e(et)}</text>')
    return "".join(partes)


def _capas_hover(n: int, x, banda: float, puntos: List[dict], descripciones: Sequence[str]) -> str:
    """Una zona de impacto por posición (más ancha que la marca): el cursor busca la semana, no la línea.

    Con teclado el gráfico es UNA parada de tabulación (la primera zona tiene tabindex 0, las demás -1) y las
    flechas recorren las semanas (el script mueve el foco); cada zona tiene su descripción completa como nombre."""
    cruz = f'<line class="xh" x1="0" x2="0" y1="{_MT}" y2="{_H - _MB}" visibility="hidden"/>'
    zonas = "".join(
        f'<rect class="hit" data-i="{i}" x="{x(i) - banda / 2:.1f}" y="{_MT}" width="{banda:.1f}" height="{_H - _MT - _MB}" '
        f'tabindex="{0 if i == 0 else -1}" role="img" aria-label="{_e(descripciones[i])}"/>'
        for i in range(n)
    )
    return cruz + zonas


def _svg(clase: str, etiqueta: str, cuerpo: str, puntos: List[dict]) -> str:
    return (
        f'<div class="zona-g"><svg class="chart {clase}" viewBox="0 0 {_W} {_H}" role="group" aria-label="{_e(etiqueta)}" '
        f'data-points="{_e(json.dumps(puntos, ensure_ascii=False))}">{cuerpo}</svg></div>'
    )


def _etiqueta_semana(s: SemanaUso) -> str:
    return _corta(_fecha(s.inicio)) + ("*" if s.parcial else "")


def _tooltip_titulo(s: SemanaUso) -> str:
    base = f"{_corta(_fecha(s.inicio))} – {_corta(_fecha(s.fin))}"
    return base + " (semana parcial)" if s.parcial else base


def _grafico_linea(semanas: Sequence[SemanaUso], etiqueta: str, valores: Sequence[Optional[float]], nombre: str) -> str:
    """Una serie, línea de 2 px con puntos de 8 px y anillo de la superficie."""
    n = len(semanas)
    datos = [v for v in valores if v is not None]
    if not datos:
        return '<p class="vacio">Sin datos disponibles para graficar.</p>'
    techo = _techo(max(datos), True)
    x, y, banda = _escalas(n, techo)
    cuerpo = _ejes(techo, y, n, [_etiqueta_semana(s) for s in semanas], x, True, lambda t: f"{t:,.0f}")
    tramo = [(x(i), y(v)) for i, v in enumerate(valores) if v is not None]
    cuerpo += '<polyline class="linea" points="' + " ".join(f"{a:.1f},{b:.1f}" for a, b in tramo) + '"/>'
    for a, b in tramo:
        cuerpo += f'<circle class="punto" cx="{a:.1f}" cy="{b:.1f}" r="4"/>'
    # Etiqueta directa solo en el último punto.
    ultimo = max(i for i, v in enumerate(valores) if v is not None)
    cuerpo += f'<text class="valor" x="{x(ultimo):.1f}" y="{y(valores[ultimo]) - 10:.1f}" text-anchor="middle">{_e(f"{valores[ultimo]:,.0f}")}</text>'
    puntos = [{"t": _tooltip_titulo(s), "rows": [[nombre, _n(v)]]} for s, v in zip(semanas, valores)]
    desc = [f"{p['t']}: {nombre} {p['rows'][0][1]}" for p in puntos]
    cuerpo += _capas_hover(n, x, banda, puntos, desc)
    return _svg("g-linea", etiqueta, cuerpo, puntos)


def _grafico_columnas(semanas: Sequence[SemanaUso], etiqueta: str, valores: Sequence[Optional[float]], nombre: str) -> str:
    """Columnas de hasta 24 px, con 4 px redondeados en la punta y base recta."""
    n = len(semanas)
    datos = [v for v in valores if v is not None]
    if not datos:
        return '<p class="vacio">Sin datos disponibles para graficar.</p>'
    techo = _techo(max(datos), True)
    x, y, banda = _escalas(n, techo)
    cuerpo = _ejes(techo, y, n, [_etiqueta_semana(s) for s in semanas], x, True, lambda t: f"{t:,.0f}")
    ancho = min(24.0, banda - 4)
    for i, v in enumerate(valores):
        if v is None or v <= 0:
            continue
        x0, x1, yt, yb = x(i) - ancho / 2, x(i) + ancho / 2, y(v), y(0)
        r = min(4.0, (yb - yt) / 2, ancho / 2)
        cuerpo += (
            f'<path class="col" d="M{x0:.1f},{yb:.1f} L{x0:.1f},{yt + r:.1f} Q{x0:.1f},{yt:.1f} {x0 + r:.1f},{yt:.1f} '
            f'L{x1 - r:.1f},{yt:.1f} Q{x1:.1f},{yt:.1f} {x1:.1f},{yt + r:.1f} L{x1:.1f},{yb:.1f} Z"/>'
        )
    mayor = max(range(n), key=lambda i: valores[i] if valores[i] is not None else -1)
    if valores[mayor]:
        cuerpo += f'<text class="valor" x="{x(mayor):.1f}" y="{y(valores[mayor]) - 6:.1f}" text-anchor="middle">{_e(f"{valores[mayor]:,.0f}")}</text>'
    puntos = [{"t": _tooltip_titulo(s), "rows": [[nombre, _n(v)]]} for s, v in zip(semanas, valores)]
    desc = [f"{p['t']}: {nombre} {p['rows'][0][1]}" for p in puntos]
    cuerpo += _capas_hover(n, x, banda, puntos, desc)
    return _svg("g-columnas", etiqueta, cuerpo, puntos)


def _grafico_banda(semanas: Sequence[SemanaUso], etiqueta: str) -> str:
    """El tiempo ahorrado es un rango: una banda (10 % de opacidad) con sus dos bordes de 2 px."""
    n = len(semanas)
    pares = [(s.horas_ahorradas_min, s.horas_ahorradas_max) for s in semanas]
    if all(a is None or b is None for a, b in pares):
        return '<p class="vacio">Sin datos disponibles para graficar.</p>'
    techo = _techo(max(b for a, b in pares if b is not None), False)
    x, y, banda = _escalas(n, techo)
    cuerpo = _ejes(techo, y, n, [_etiqueta_semana(s) for s in semanas], x, False, lambda t: f"{t:,.0f}")
    validos = [(i, a, b) for i, (a, b) in enumerate(pares) if a is not None and b is not None]
    alto = [f"{x(i):.1f},{y(b):.1f}" for i, a, b in validos]
    bajo = [f"{x(i):.1f},{y(a):.1f}" for i, a, b in reversed(validos)]
    cuerpo += f'<polygon class="banda" points="{" ".join(alto + bajo)}"/>'
    cuerpo += f'<polyline class="linea" points="{" ".join(alto)}"/><polyline class="linea" points="{" ".join(reversed(bajo))}"/>'
    for i, a, b in validos:
        cuerpo += f'<circle class="punto" cx="{x(i):.1f}" cy="{y(b):.1f}" r="4"/><circle class="punto" cx="{x(i):.1f}" cy="{y(a):.1f}" r="4"/>'
    puntos = [{"t": _tooltip_titulo(s), "rows": [["Horas ahorradas (estimado)", _rango_h(a, b)]]} for s, (a, b) in zip(semanas, pares)]
    desc = [f"{p['t']}: {p['rows'][0][1]}" for p in puntos]
    cuerpo += _capas_hover(n, x, banda, puntos, desc)
    return _svg("g-banda", etiqueta, cuerpo, puntos)


def _barra_apilada(dominio: AceptacionDominio) -> str:
    """Una barra horizontal de 20 px dividida por categoría (con 2 px de separación); el extremo final, redondeado.

    Sin texto dentro de los segmentos: en pantallas angostas el SVG se reduce y el texto quedaría ilegible; las
    cifras están en la tabla de leyenda que va justo debajo y en el nombre accesible de la barra."""
    ancho_total, alto = 520.0, 20.0
    total = sum(n for _, _, n in dominio.categorias) or 1
    huecos = 2.0 * (len(dominio.categorias) - 1)
    util = ancho_total - huecos
    x = 0.0
    segmentos = []
    puntos = []
    for idx, (clave, etiqueta, n) in enumerate(dominio.categorias):
        w = util * n / total
        if w <= 0:
            puntos.append({"t": etiqueta, "rows": [["Recomendaciones", f"{n:,}"]]})
            continue
        es_ultimo = idx == max(i for i, c in enumerate(dominio.categorias) if c[2] > 0)
        if es_ultimo and w > 4:
            r = 4.0
            d = f"M{x:.1f},0 L{x + w - r:.1f},0 Q{x + w:.1f},0 {x + w:.1f},{r} L{x + w:.1f},{alto - r} Q{x + w:.1f},{alto} {x + w - r:.1f},{alto} L{x:.1f},{alto} Z"
            forma = f'<path class="seg seg-{idx}" d="{d}"/>'
        else:
            forma = f'<rect class="seg seg-{idx}" x="{x:.1f}" y="0" width="{w:.1f}" height="{alto}"/>'
        segmentos.append(forma)
        puntos.append({"t": etiqueta, "rows": [["Recomendaciones", f"{n:,} ({n / total * 100:.0f} %)"]]})
        x += w + 2.0
    zonas = ""
    resumen = "; ".join(f"{etiqueta}: {n:,} ({n / total * 100:.0f} %)" for _, etiqueta, n in dominio.categorias)
    return (
        f'<div class="zona-g"><svg class="barra" viewBox="0 0 {ancho_total:.0f} {alto:.0f}" role="img" '
        f'aria-label="{_e(dominio.etiqueta)}, distribución de las recomendaciones. {_e(resumen)}">{"".join(segmentos)}{zonas}</svg></div>'
    )


# --------------------------------------------------------------------------
# Secciones
# --------------------------------------------------------------------------


def _tabla(titulo: str, encabezados: Sequence[str], filas: Sequence[Sequence[str]], clase: str = "", izquierda: Sequence[int] = ()) -> str:
    """Tabla de datos con su ``<caption>`` (lo lee el lector de pantalla al navegar entre tablas); texto a la
    izquierda en la primera columna y en ``izquierda``; números a la derecha."""
    def cls(i: int) -> str:
        return ' class="izq"' if i == 0 or i in izquierda else ""

    th = "".join(f"<th scope='col'{cls(i)}>{_e(h)}</th>" for i, h in enumerate(encabezados))
    tr = "".join("<tr>" + "".join(f"<td{cls(i)}>{c}</td>" for i, c in enumerate(fila)) + "</tr>" for fila in filas)
    return f'<div class="scroll"><table class="datos {clase}"><caption class="vh">{_e(titulo)}</caption><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'


def _con_tabla(grafico: str, tabla: str) -> str:
    return f'{grafico}<details class="tabla-vista"><summary>Ver como tabla</summary>{tabla}</details>'


def _filtros(m: MetricasUso) -> str:
    hoy = _fecha(m.generado_en)
    actual = (m.periodo.desde, m.periodo.hasta)
    opciones = []
    for etiqueta, dias in (("Últimos 7 días", 7), ("Últimos 30 días", 30), ("Últimos 90 días", 90)):
        desde = (hoy - timedelta(days=dias - 1)).isoformat()
        marcado = (desde, hoy.isoformat()) == actual
        # Sin barras invertidas dentro de las llaves de un f-string: no son válidas antes de Python 3.12.
        clase = "preset sel" if marcado else "preset"
        actual_attr = ' aria-current="true"' if marcado else ""
        marca = '<span class="chk" aria-hidden="true">✓</span>' if marcado else ""
        opciones.append(
            f'<a class="{clase}" href="?desde={desde}&amp;hasta={hoy.isoformat()}"{actual_attr}>{marca}{etiqueta}</a>'
        )
    personalizado = (
        '<details class="personalizado"><summary>Rango personalizado</summary>'
        '<form method="get"><label>Desde <input type="date" name="desde" required value="' + _e(m.periodo.desde) + '"></label> '
        '<label>Hasta <input type="date" name="hasta" required value="' + _e(m.periodo.hasta) + '"></label> '
        '<button type="submit">Aplicar</button></form></details>'
    )
    return f'<nav class="filtros" aria-label="Periodo">{"".join(opciones)}{personalizado}</nav>'


def _hero_adopcion(m: MetricasUso) -> str:
    a = m.adopcion
    if not a.disponible:
        return f'<section class="hero tarjeta"><h2>Adopción</h2><p class="nd-bloque">No disponible: {_e(a.motivo)}</p></section>'
    pct = a.tasa_adopcion
    relleno = 0 if pct is None else max(0.0, min(1.0, pct)) * 100
    cuerpo = (
        f'<p class="etiqueta">Usuarios clínicos que usaron el sistema</p>'
        f'<p class="hero-cifra">{_pct(pct)}</p>'
        f'<div class="meter" aria-hidden="true"><div class="meter-fill" style="width:{relleno:.1f}%"></div></div>'
        f'<p class="detalle">{_n(a.usuarios_activos)} de {_n(a.usuarios_elegibles)} oncólogos y personal de enfermería con cuenta activa '
        f'usaron el sistema al menos una vez en el periodo.</p>'
        f'<p>{_delta(a.tasa_adopcion, a.tasa_adopcion_periodo_anterior, " pts", 100)}</p>'
    )
    return f'<section class="hero tarjeta" aria-labelledby="h-adop"><h2 id="h-adop" class="vh">Adopción</h2>{cuerpo}</section>'


def _tiles(m: MetricasUso) -> str:
    t, al, ad = m.tiempo_ahorrado, m.alertas, m.adopcion
    if t.disponible:
        sub = ('<p class="detalle">Estimación (rango), no medición.' + (" <strong>Subestimada:</strong> faltan fuentes." if t.subestimado else "") + "</p>")
        tiempo = (
            f'<p class="valor-tile">{_rango_h(t.horas_min, t.horas_max)}</p>{sub}'
            f'<p>{_delta(t.horas_max, t.horas_max_periodo_anterior, " h", 1, 0)}</p>'
        )
    else:
        tiempo = f'<p class="valor-tile">{_nd(t.motivo or "")}</p><p class="detalle">{_e(t.motivo or "No disponible")}</p>'
    if al.disponible:
        alertas = (
            f'<p class="valor-tile">{_n(al.generadas)}</p><p class="detalle">Alertas críticas de laboratorio; '
            f'{_n(al.pendientes_actuales)} pendientes de revisión hoy.</p>'
            f'<p>{_delta(al.generadas, al.generadas_periodo_anterior, "", 1, 0)}</p>'
        )
    else:
        alertas = f'<p class="valor-tile">{_nd(al.motivo or "")}</p><p class="detalle">{_e(al.motivo or "No disponible")}</p>'
    if ad.disponible:
        pacientes = (
            f'<p class="valor-tile">{_n(ad.pacientes_atendidos)}</p>'
            f'<p class="detalle">Pacientes cuyo expediente se consultó, editó o exportó con el sistema.</p>'
        )
    else:
        pacientes = f'<p class="valor-tile">{_nd(ad.motivo or "")}</p><p class="detalle">{_e(ad.motivo or "No disponible")}</p>'
    return (
        '<div class="tiles">'
        f'<section class="tarjeta tile"><h2 class="etiqueta">Tiempo ahorrado (estimado)</h2>{tiempo}</section>'
        f'<section class="tarjeta tile"><h2 class="etiqueta">Alertas generadas</h2>{alertas}</section>'
        f'<section class="tarjeta tile"><h2 class="etiqueta">Pacientes atendidos</h2>{pacientes}</section>'
        "</div>"
    )


def _graficos_semanales(m: MetricasUso) -> str:
    sem = m.semanas
    if not sem:
        return ""
    tabla_act = _tabla("Usuarios clínicos activos por semana", ["Semana", "Usuarios activos"], [[_e(_tooltip_titulo(s)), _n(s.usuarios_activos)] for s in sem])
    tabla_ale = _tabla("Alertas generadas por semana", ["Semana", "Alertas generadas"], [[_e(_tooltip_titulo(s)), _n(s.alertas_generadas)] for s in sem])
    tabla_hor = _tabla("Horas ahorradas por semana (estimado)", ["Semana", "Horas ahorradas (estimado)"], [[_e(_tooltip_titulo(s)), _rango_h(s.horas_ahorradas_min, s.horas_ahorradas_max)] for s in sem])
    nota = ""
    if any(s.parcial for s in sem):
        nota = '<p class="pie">* Semana parcial (menos de 7 días): no es comparable con las demás.</p>'
    return (
        '<p class="pie" id="ayuda-graficos">Con teclado: Tab entra a cada gráfico, las flechas izquierda y derecha recorren las semanas y '
        "Escape cierra el detalle. Debajo de cada gráfico hay una tabla con los mismos datos.</p>"
        '<div class="graficos">'
        '<figure class="tarjeta"><figcaption>Usuarios clínicos activos por semana</figcaption>'
        + _con_tabla(_grafico_linea(sem, "Usuarios clínicos activos por semana", [s.usuarios_activos for s in sem], "Usuarios activos"), tabla_act)
        + "</figure>"
        '<figure class="tarjeta"><figcaption>Alertas generadas por semana</figcaption>'
        + _con_tabla(_grafico_columnas(sem, "Alertas generadas por semana", [s.alertas_generadas for s in sem], "Alertas"), tabla_ale)
        + "</figure>"
        '<figure class="tarjeta"><figcaption>Horas ahorradas por semana (estimado)</figcaption>'
        + _con_tabla(_grafico_banda(sem, "Horas ahorradas por semana, estimación en rango"), tabla_hor)
        + "</figure></div>" + nota
    )


def _detalle_adopcion(m: MetricasUso) -> str:
    a = m.adopcion
    if not a.disponible:
        return ""
    roles = []
    for r in a.por_rol:
        nombre = _ETIQUETAS_ROL.get(r.rol, r.rol)
        if r.suprimido:
            roles.append([_e(nombre), '<span class="nd">Grupo pequeño: no se muestra</span>', "", ""])
        else:
            roles.append([_e(nombre), _n(r.usuarios_activos), _n(r.usuarios_elegibles), _pct(r.tasa_adopcion)])
    acciones = [[_e(_ETIQUETAS_ACCION.get(k, k)), _n(v)] for k, v in a.acciones_por_tipo]
    ia = [
        [_e(f.etiqueta), _n(f.total) if f.total is not None else _nd("La fuente de este dato no está disponible"),
         _n(f.total_periodo_anterior) if f.total_periodo_anterior is not None else _nd()]
        for f in a.uso_funciones_ia
    ]
    nota_no_atrib = ""
    if a.eventos_no_atribuibles:
        nota_no_atrib = (f'<p class="pie">{_n(a.eventos_no_atribuibles)} accesos de cuentas que no son personal clínico activo '
                         "(auditoría, cuentas dadas de baja, cuentas de sistema) no cuentan como adopción.</p>")
    return (
        '<section class="tarjeta"><h2>Detalle de adopción</h2><div class="dos-col">'
        f'<div><h3>Por rol</h3>{_tabla("Adopción por rol", ["Rol", "Activos", "Con cuenta", "Adopción"], roles)}'
        '<p class="pie">Los grupos pequeños no se desglosan, para que una cifra no pueda atribuirse a una persona.</p></div>'
        f'<div><h3>Tipo de uso</h3>{_tabla("Adopción por tipo de uso", ["Acción", "Veces"], acciones)}</div>'
        f'<div><h3>Funciones de IA usadas</h3>{_tabla("Funciones de IA usadas", ["Función", "Periodo", "Anterior"], ia)}</div>'
        f"</div>{nota_no_atrib}</section>"
    )


def _detalle_alertas(m: MetricasUso) -> str:
    a = m.alertas
    if not a.disponible:
        return f'<section class="tarjeta"><h2>Alertas</h2><p class="nd-bloque">No disponible: {_e(a.motivo)}</p></section>'
    sev = [[_e(s), _n(n)] for s, n in a.por_severidad] or [["—", "—"]]
    resumen = [
        ["Alertas generadas", _n(a.generadas)],
        ["Alertas revisadas (de las generadas)", _n(a.revisadas)],
        ["Alertas pendientes de revisión (hoy)", _n(a.pendientes_actuales)],
        ["Conflictos de resultados detectados", _n(a.conflictos_detectados)],
        ["Conflictos pendientes (hoy)", _n(a.conflictos_pendientes_actuales)],
        ["Sincronizaciones externas exitosas", _n(a.sincronizaciones_exitosas)],
        ["Sincronizaciones externas fallidas", _n(a.sincronizaciones_fallidas)],
    ]
    return (
        '<section class="tarjeta"><h2>Alertas y sincronizaciones</h2><div class="dos-col">'
        f'<div>{_tabla("Alertas y sincronizaciones", ["Concepto", "Cantidad"], [[_e(a), b] for a, b in resumen])}</div>'
        f'<div><h3>Por severidad</h3>{_tabla("Alertas por severidad", ["Severidad", "Alertas"], sev)}</div></div></section>'
    )


def _detalle_tiempo(m: MetricasUso) -> str:
    t = m.tiempo_ahorrado
    filas = []
    for c in t.componentes:
        filas.append([
            _e(c.descripcion),
            _n(c.eventos) if c.disponible else _nd("Fuente no disponible"),
            f"{c.minutos_min_por_evento:g}–{c.minutos_max_por_evento:g} min",
            _rango_h(c.horas_min, c.horas_max),
            _e(c.origen_supuesto),
        ])
    aviso = ""
    if t.subestimado:
        aviso = '<p class="aviso"><span aria-hidden="true">⚠</span> Falta alguna fuente: el total mostrado es una <strong>subestimación</strong>.</p>'
    return (
        '<section class="tarjeta"><h2>Cómo se estima el tiempo ahorrado</h2>'
        f'<p>{_e(t.nota)}</p>{aviso}'
        f'{_tabla("Supuestos del tiempo ahorrado", ["Evento contado", "Eventos", "Minutos supuestos", "Horas", "Origen del supuesto"], filas, izquierda=(4,))}'
        '<p class="pie">Los minutos son supuestos por defecto, no mediciones; la institución puede reemplazarlos con su propio estudio '
        "de tiempos (variable COPILOTO_COEFICIENTES_TIEMPO).</p></section>"
    )


def _aceptacion(m: MetricasUso) -> str:
    ac = m.aceptacion_ia
    bloques = []
    for d in ac.dominios:
        if not d.disponible:
            bloques.append(f'<div class="dominio"><h3>{_e(d.etiqueta)}</h3><p class="nd-bloque">No disponible: {_e(d.motivo)}</p></div>')
        elif d.suprimida:
            bloques.append(
                f'<div class="dominio"><h3>{_e(d.etiqueta)}</h3>'
                f'<p class="suprimida"><span aria-hidden="true">ⓘ</span> {_e(d.motivo)}</p></div>'
            )
        else:
            filas = []
            for idx, (clave, etiqueta, n) in enumerate(d.categorias):
                pct = n / d.total * 100 if d.total else 0
                filas.append([f'<span class="sw sw-{idx}" aria-hidden="true"></span>{_e(etiqueta)}', _n(n), f"{pct:.0f} %"])
            bloques.append(
                f'<div class="dominio"><h3>{_e(d.etiqueta)}</h3>'
                f'<p class="detalle">{_n(d.total)} recomendaciones en el periodo</p>'
                f'{_barra_apilada(d)}'
                f'{_tabla("Aceptación de recomendaciones: " + d.etiqueta, ["Qué se hizo con la recomendación", "Casos", "Parte"], filas, "leyenda")}</div>'
            )
    sin_comp = "".join(f"<li>{_e(x)}</li>" for x in ac.dominios_sin_comparacion)
    return (
        '<section class="tarjeta aceptacion" aria-labelledby="h-acep"><h2 id="h-acep">Qué pasa con las recomendaciones de la IA</h2>'
        f'<p class="nota-uso"><strong>Cómo leer esto.</strong> {_e(ac.nota_interpretacion)}</p>'
        f'{"".join(bloques)}'
        f'<p class="pie">Sin comparación disponible:</p><ul class="pie">{sin_comp}</ul></section>'
    )


def _pie(m: MetricasUso) -> str:
    faltan = ""
    if m.fuentes_no_disponibles:
        faltan = ('<p class="pie">Fuentes de datos sin conectar (sus cifras aparecen como "—", no como cero): '
                  + ", ".join(_e(f) for f in m.fuentes_no_disponibles) + ".</p>")
    return (
        f'<footer>{faltan}<p class="pie">Periodo anterior: {_e(_rango_fechas(m.periodo.desde_anterior, m.periodo.hasta_anterior))}. '
        f'Fechas en UTC. Generado {_e(m.generado_en[:16].replace("T", " "))} UTC. '
        "Todo lo que se muestra es agregado de la institución; esta consulta queda registrada en la auditoría.</p></footer>"
    )


# --------------------------------------------------------------------------
# Documento
# --------------------------------------------------------------------------

_CSS = """
:root{color-scheme:light}
.viz-root{--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#6b6a65;--grid:#e1e0d9;--axis:#c3c2b7;--borde:#85847e;--foco:#2a78d6;
 --ring:rgba(11,11,11,.10);--s1:#2a78d6;--o1:#86b6ef;--o2:#3987e5;--o3:#184f95;--track:#cde2fb;--link:#256abf;--warn:#8a5a00}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])) .viz-root{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;
 --ink:#f0efec;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;--borde:#85847e;--foco:#3987e5;--ring:rgba(255,255,255,.10);--s1:#3987e5;
 --o1:#86b6ef;--o2:#3987e5;--o3:#184f95;--track:#0c3566;--link:#86b6ef;--warn:#fab219}}
:root[data-theme="dark"] .viz-root{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#898781;
 --grid:#2c2c2a;--axis:#383835;--borde:#85847e;--foco:#3987e5;--ring:rgba(255,255,255,.10);--s1:#3987e5;--o1:#86b6ef;--o2:#3987e5;--o3:#184f95;--track:#0c3566;--link:#86b6ef;--warn:#fab219}
*{box-sizing:border-box}
body{margin:0;background:var(--page,#f9f9f7)}
.viz-root{background:var(--page);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;min-height:100vh;padding:24px 16px 48px}
main{max-width:1280px;margin:0 auto}
h1{font-size:24px;margin:0 0 4px;font-weight:600}
h2{font-size:16px;margin:0 0 12px;font-weight:600}
h3{font-size:14px;margin:0 0 8px;font-weight:600;color:var(--ink2)}
.vh{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
:focus-visible{outline:3px solid var(--foco);outline-offset:2px}
.saltar{position:absolute;left:8px;top:-60px;z-index:20;background:var(--surface);color:var(--ink);padding:10px 14px;border:2px solid var(--foco);border-radius:8px}
.saltar:focus{top:8px}
.sub{color:var(--ink2);margin:0 0 16px}
.tarjeta{background:var(--surface);border:1px solid var(--ring);border-radius:12px;padding:20px;margin:0 0 16px}
.privacidad{border-left:3px solid var(--s1);background:var(--surface);padding:10px 14px;border-radius:0 8px 8px 0;margin:0 0 16px;color:var(--ink2);font-size:14px}
.filtros{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 16px}
.preset{display:inline-flex;align-items:center;min-height:40px;padding:6px 14px;border-radius:8px;color:var(--ink);text-decoration:none;border:1px solid var(--borde);background:var(--surface);font-size:14px}
.preset:hover{background:var(--grid)}.preset.sel{border-color:var(--s1);font-weight:600}.chk{font-weight:700;margin-right:6px;font-size:16px}
.personalizado{font-size:14px;color:var(--ink2)}.personalizado summary{cursor:pointer;padding:10px 4px;min-height:40px}
.personalizado form{display:flex;flex-wrap:wrap;gap:8px;padding:8px 0}
input,button{font:inherit;color:var(--ink);background:var(--surface);border:1px solid var(--borde);border-radius:6px;padding:6px 10px;min-height:40px}
button{cursor:pointer}
.arriba{display:grid;grid-template-columns:minmax(260px,1fr) 2fr;gap:16px;align-items:stretch}
.arriba>*{margin:0 0 16px}
.hero-cifra{font-size:56px;line-height:1.05;margin:4px 0 12px;font-weight:600}
.etiqueta{font-size:14px;color:var(--ink2);margin:0;font-weight:500}
.meter{height:10px;border-radius:5px;background:var(--track);border:1px solid var(--borde);overflow:hidden;margin:0 0 12px}
.meter-fill{height:100%;background:var(--s1);border-radius:4px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(190px,100%),1fr));gap:16px}
.tiles .tile{margin:0}
.valor-tile{font-size:32px;line-height:1.15;margin:6px 0 8px;font-weight:600}
.detalle{color:var(--ink2);font-size:14px;margin:0 0 8px}
.delta{color:var(--ink2);font-size:13px}
.nd{color:var(--muted)}.nd-bloque{color:var(--ink2)}
.graficos{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(400px,100%),1fr));gap:16px}
.graficos figure,.graficos .tarjeta{min-width:0}
div.zona-g{overflow-x:auto}
.graficos figure{margin:0}.graficos figcaption{font-weight:600;margin:0 0 8px}
svg.chart{width:100%;min-width:360px;height:auto;display:block;overflow:visible}svg.barra{width:100%;height:auto;display:block;overflow:visible}
.grid{stroke:var(--grid);stroke-width:1}.base{stroke:var(--axis);stroke-width:1}
.tick{fill:var(--muted);font-size:12px;font-family:inherit}
.valor{fill:var(--ink);font-size:12px;font-weight:600;font-family:inherit}
.linea{fill:none;stroke:var(--s1);stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.punto{fill:var(--s1);stroke:var(--surface);stroke-width:2}
.banda{fill:var(--s1);fill-opacity:.15;stroke:none}
.col{fill:var(--s1)}
.xh{stroke:var(--axis);stroke-width:1}
.hit{fill:transparent;outline:none}.hit:focus-visible{stroke:var(--foco);stroke-width:3;fill:var(--grid);fill-opacity:.4}
.hit:hover{fill:var(--grid);fill-opacity:.35}
.seg{stroke:var(--borde);stroke-width:1}.seg-0{fill:var(--o1)}.seg-1{fill:var(--o2)}.seg-2{fill:var(--o3)}
.sw{display:inline-block;width:14px;height:14px;border-radius:3px;margin-right:8px;vertical-align:-2px;border:1px solid var(--borde)}
.sw-0{background:var(--o1)}.sw-1{background:var(--o2)}.sw-2{background:var(--o3)}
div.scroll{overflow-x:auto}table.datos{width:100%;border-collapse:collapse;font-size:14px;margin:4px 0}
.datos th{text-align:left;color:var(--ink2);font-weight:500;border-bottom:1px solid var(--axis);padding:6px 8px 6px 0}
.datos td{border-bottom:1px solid var(--grid);padding:6px 8px 6px 0;vertical-align:top;font-variant-numeric:tabular-nums}
.datos td,.datos th{text-align:right}.datos td.izq,.datos th.izq{text-align:left}
.datos td{white-space:normal}.datos td:nth-child(n+2):not(.izq){white-space:nowrap}
.tabla-vista{margin-top:8px;font-size:14px}.tabla-vista summary{cursor:pointer;color:var(--link);padding:10px 0;min-height:40px}
.dos-col{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(260px,100%),1fr));gap:20px}.dos-col>*{min-width:0}
.nota-uso{background:var(--page);border:1px solid var(--ring);border-radius:8px;padding:12px 14px;margin:0 0 16px}
.dominio{margin:0 0 20px}.suprimida{color:var(--ink2);margin:0}
.pie{color:var(--muted);font-size:13px;margin:8px 0 0}ul.pie{margin:4px 0 0 18px;padding:0}
.aviso{color:var(--warn);margin:8px 0}
.vacio{color:var(--muted)}
footer{margin-top:24px}
#tip{position:absolute;z-index:10;background:var(--surface);color:var(--ink);border:1px solid var(--axis);border-radius:8px;
 padding:8px 10px;font-size:13px;box-shadow:0 4px 14px rgba(0,0,0,.18);display:none;max-width:260px}
#tip .t{color:var(--ink2);margin-bottom:4px}#tip .r{display:flex;align-items:center;gap:8px}
#tip .k{display:inline-block;width:14px;height:2px;background:var(--s1);flex:none}#tip .v{font-weight:600}
@media (max-width:760px){.arriba{grid-template-columns:1fr}.hero-cifra{font-size:48px}}
@media print,(forced-colors:active){
 .seg-0{fill:Canvas;stroke:CanvasText;stroke-width:1}.seg-1{fill:url(#p45);stroke:CanvasText;stroke-width:1}.seg-2{fill:url(#p135);stroke:CanvasText;stroke-width:1}
 .sw-0{background:Canvas;border:1px solid CanvasText}.sw-1{background:repeating-linear-gradient(45deg,CanvasText 0 1px,Canvas 1px 4px);border:1px solid CanvasText}
 .sw-2{background:repeating-linear-gradient(135deg,CanvasText 0 1px,Canvas 1px 4px);border:1px solid CanvasText}}
@media (forced-colors:active){.linea,.punto,.col,.meter-fill,.banda{forced-color-adjust:none}.linea{stroke:Highlight}.punto,.col,.meter-fill{fill:Highlight;background:Highlight}.banda{fill:Highlight}}
"""

_JS = """
(function(){
 var tip=document.getElementById('tip'),espera=null;
 function cancelar(){if(espera){clearTimeout(espera);espera=null;}}
 function esconder(){cancelar();tip.style.display='none';
  document.querySelectorAll('svg.chart .xh').forEach(function(x){x.setAttribute('visibility','hidden');});}
 function programar(e){if(e&&e.pointerType==='touch')return;cancelar();espera=setTimeout(esconder,250);}
 tip.addEventListener('pointerenter',cancelar);tip.addEventListener('pointerleave',programar);
 document.addEventListener('keydown',function(e){if(e.key==='Escape')esconder();});
 document.addEventListener('pointerdown',function(e){if(!e.target.closest||(!e.target.closest('.hit')&&!e.target.closest('#tip')))esconder();});
 // Una región que se desplaza en horizontal (tabla o gráfico en pantalla angosta) debe poder recorrerse con el teclado.
 function regiones(){
  document.querySelectorAll('div.scroll,div.zona-g').forEach(function(z){
   if(z.scrollWidth>z.clientWidth+1){
    var t=z.querySelector('caption'),g=z.querySelector('svg[aria-label]');
    z.setAttribute('tabindex','0');z.setAttribute('role','region');
    z.setAttribute('aria-label',(t?t.textContent:g?g.getAttribute('aria-label'):'Contenido')+' (se desplaza horizontalmente)');
   }else{z.removeAttribute('tabindex');z.removeAttribute('role');z.removeAttribute('aria-label');}
  });
 }
 regiones();window.addEventListener('resize',regiones);
 document.querySelectorAll('svg.chart').forEach(function(svg){
  var pts;try{pts=JSON.parse(svg.getAttribute('data-points'));}catch(e){return;}
  var xh=svg.querySelector('.xh'),hits=[].slice.call(svg.querySelectorAll('.hit'));
  function mostrar(r){
   cancelar();var d=pts[+r.getAttribute('data-i')];if(!d)return;
   tip.textContent='';
   var t=document.createElement('div');t.className='t';t.textContent=d.t;tip.appendChild(t);
   d.rows.forEach(function(f){var row=document.createElement('div');row.className='r';
    var k=document.createElement('span');k.className='k';var v=document.createElement('span');v.className='v';v.textContent=f[1];
    var n=document.createElement('span');n.textContent=f[0];row.appendChild(k);row.appendChild(v);row.appendChild(n);tip.appendChild(row);});
   var b=r.getBoundingClientRect();tip.style.display='block';
   var w=tip.offsetWidth,h=tip.offsetHeight,left=b.left+b.width/2-w/2+window.scrollX;
   left=Math.max(8+window.scrollX,Math.min(left,window.scrollX+document.documentElement.clientWidth-w-8));
   tip.style.left=left+'px';tip.style.top=Math.max(window.scrollY+4,b.top+window.scrollY-h-4)+'px';
   if(xh){var cx=+r.getAttribute('x')+(+r.getAttribute('width'))/2;xh.setAttribute('x1',cx);xh.setAttribute('x2',cx);xh.setAttribute('visibility','visible');}
  }
  function ir(j){j=Math.max(0,Math.min(hits.length-1,j));hits.forEach(function(h,i){h.setAttribute('tabindex',i===j?'0':'-1');});hits[j].focus();}
  hits.forEach(function(r,i){
   r.addEventListener('pointerenter',function(){mostrar(r)});r.addEventListener('pointermove',function(){mostrar(r)});
   r.addEventListener('focus',function(){mostrar(r)});
   r.addEventListener('pointerleave',programar);r.addEventListener('blur',esconder);
   r.addEventListener('keydown',function(e){
    var k=e.key,j=-1;
    if(k==='ArrowRight'||k==='ArrowDown')j=i+1;else if(k==='ArrowLeft'||k==='ArrowUp')j=i-1;else if(k==='Home')j=0;else if(k==='End')j=hits.length-1;
    if(j>=0){e.preventDefault();ir(j);}
   });
  });
 });
})();
"""

_PATRONES = (
    '<svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false"><defs>'
    '<pattern id="p45" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6" stroke="CanvasText" stroke-width="1.5"/></pattern>'
    '<pattern id="p135" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(135)"><line x1="0" y1="0" x2="0" y2="6" stroke="CanvasText" stroke-width="1.5"/></pattern>'
    "</defs></svg>"
)


def renderizar_panel(m: MetricasUso, *, titulo: str = "Uso del copiloto oncológico") -> str:
    """Documento HTML completo del tablero para un ``MetricasUso``."""
    p = m.periodo
    cuerpo = (
        f"<h1>{_e(titulo)}</h1>"
        f'<p class="sub">{_e(_rango_fechas(p.desde, p.hasta))} · {p.dias} días · comparado con el periodo anterior de igual duración</p>'
        '<p class="privacidad">Cifras agregadas de toda la institución. El tablero no contiene datos por médico y no sirve para evaluar '
        "a personas.</p>"
        f"{_filtros(m)}"
        f'<div class="arriba">{_hero_adopcion(m)}{_tiles(m)}</div>'
        f"{_graficos_semanales(m)}"
        f"{_aceptacion(m)}"
        f"{_detalle_adopcion(m)}{_detalle_alertas(m)}{_detalle_tiempo(m)}"
        f"{_pie(m)}"
    )
    return (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="color-scheme" content="light dark">'
        f"<title>{_e(titulo)}</title><style>{_CSS}</style></head>"
        f'<body><div class="viz-root"><a class="saltar" href="#contenido">Saltar al contenido principal</a>{_PATRONES}'
        f'<main id="contenido" tabindex="-1">{cuerpo}</main></div><div id="tip" aria-hidden="true"></div>'
        f"<script>{_JS}</script></body></html>"
    )


def renderizar_error(mensajes: Sequence[str], *, desde: str = "", hasta: str = "", titulo: str = "Uso del copiloto oncológico") -> str:
    """Página de error del tablero para un periodo no válido (WCAG 3.3.1 y 3.3.3).

    Dice QUÉ falló con texto (no solo con color), cómo corregirlo, conserva lo que la persona escribió y
    ofrece una salida (volver a los últimos 30 días). El mensaje va en ``role="alert"`` para que el lector
    de pantalla lo anuncie al cargar."""
    items = "".join(
        f"<li>{_e(m.replace(chr(39) + 'desde' + chr(39), 'La fecha «Desde»').replace(chr(39) + 'hasta' + chr(39), 'La fecha «Hasta»'))}</li>"
        for m in mensajes
    ) or "<li>El periodo indicado no es válido.</li>"
    cuerpo = (
        f"<h1>No se pudo mostrar el tablero</h1>"
        f'<div class="tarjeta" role="alert" id="errores"><h2>Revisa el periodo</h2><ul>{items}</ul>'
        "<p>Cómo corregirlo: elige las dos fechas con el selector o escríbelas como AAAA-MM-DD; la fecha «Desde» no puede ser "
        "posterior a «Hasta», «Hasta» no puede ser futura y el periodo no puede pasar de 400 días.</p></div>"
        '<form method="get" class="tarjeta" aria-describedby="errores"><h2>Elige otro periodo</h2>'
        f'<p><label>Desde <input type="date" name="desde" required aria-invalid="true" aria-describedby="errores" value="{_e(desde)}"></label></p>'
        f'<p><label>Hasta <input type="date" name="hasta" required aria-invalid="true" aria-describedby="errores" value="{_e(hasta)}"></label></p>'
        '<button type="submit">Mostrar el tablero</button> <a class="preset" href="?">Ver los últimos 30 días</a></form>'
    )
    return (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="color-scheme" content="light dark">'
        f"<title>Periodo no válido — {_e(titulo)}</title><style>{_CSS}</style></head>"
        f'<body><div class="viz-root"><main id="contenido">{cuerpo}</main></div></body></html>'
    )
