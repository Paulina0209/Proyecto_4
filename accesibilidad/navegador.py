"""Comprobaciones de accesibilidad en un navegador real (Chromium vía Playwright). OPCIONAL.

Lo que un auditor estático no puede saber, el navegador sí: el contraste *calculado* (con
herencia, transparencias y modo oscuro), si la página se desborda a 320 px (1.4.10), si el
texto se corta al aumentar el espaciado (1.4.12), si cada parada de tabulación muestra un
indicador de foco (2.4.7) y si el teclado puede salir de todo (2.1.2). Si hay una copia de
axe-core (``AXE_CORE_JS`` o el parámetro ``axe_js``) se ejecuta también.

Si Playwright o Chromium no están instalados, ``navegador_disponible()`` es ``False`` y las
pruebas que lo usan se omiten: nada del sistema depende de este módulo.

    pip install playwright && playwright install chromium
    set AXE_CORE_JS=C:\\ruta\\a\\node_modules\\axe-core\\axe.min.js   (opcional)
"""
from __future__ import annotations

import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence

from accesibilidad.auditoria_html import AVISO, ERROR, Hallazgo, Informe

_RUTAS_CHROMIUM = (os.environ.get("COPILOTO_CHROMIUM_PATH", ""), "/opt/pw-browsers/chromium")
_ETIQUETAS_AXE = ("wcag2a", "wcag2aa", "wcag21a", "wcag21aa")


class NavegadorNoDisponible(RuntimeError):
    """Playwright o Chromium no están instalados."""


class Navegador:
    """Un Chromium sin interfaz. Úsalo con ``with``; ``pagina()`` abre una pestaña ya configurada."""

    def __init__(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - depende del entorno
            raise NavegadorNoDisponible("Playwright no está instalado (pip install playwright).") from exc
        self._pw = sync_playwright().start()
        self._browser = None
        errores = []
        intentos: List[Dict[str, Any]] = [{}] + [{"executable_path": r} for r in _RUTAS_CHROMIUM if r and Path(r).exists()]
        for kw in intentos:
            try:
                self._browser = self._pw.chromium.launch(**kw)
                break
            except Exception as exc:  # noqa: BLE001
                errores.append(str(exc).splitlines()[0])
        if self._browser is None:
            self._pw.stop()
            raise NavegadorNoDisponible("No se pudo iniciar Chromium: " + "; ".join(errores))

    def cerrar(self) -> None:
        try:
            self._browser.close()
        finally:
            self._pw.stop()

    def __enter__(self) -> "Navegador":
        return self

    def __exit__(self, *exc) -> None:
        self.cerrar()

    @contextmanager
    def pagina(self, html: Optional[str] = None, *, url: Optional[str] = None, ancho: int = 1280, alto: int = 900,
               esquema: str = "light", forced_colors: Optional[str] = None, ignorar_errores_https: bool = False) -> Iterator[Any]:
        """``ignorar_errores_https``: solo para un servidor de pruebas local con certificado autofirmado."""
        ctx = self._browser.new_context(viewport={"width": ancho, "height": alto}, color_scheme=esquema,
                                        forced_colors=forced_colors, reduced_motion="no-preference",
                                        ignore_https_errors=ignorar_errores_https)
        page = ctx.new_page()
        try:
            if url:
                page.goto(url)
            else:
                page.set_content(html or "", wait_until="load")
            yield page
        finally:
            ctx.close()


def navegador_disponible() -> bool:
    try:
        with Navegador():
            return True
    except NavegadorNoDisponible:
        return False


def ruta_axe() -> Optional[Path]:
    for candidata in (os.environ.get("AXE_CORE_JS", ""), "/tmp/axe/node_modules/axe-core/axe.min.js"):
        if candidata and Path(candidata).is_file():
            return Path(candidata)
    return None


# --------------------------------------------------------------------------
# Scripts que corren dentro de la página
# --------------------------------------------------------------------------

_JS_CONTRASTE = r"""
() => {
  function parse(c){
    var m=c.match(/rgba?\(([^)]+)\)/);
    if(m){var p=m[1].split(/[ ,\/]+/).filter(Boolean).map(Number);return {r:p[0],g:p[1],b:p[2],a:p.length>3?p[3]:1};}
    m=c.match(/color\(srgb ([^)]+)\)/);
    if(m){var q=m[1].split(/[ \/]+/).filter(Boolean).map(Number);return {r:q[0]*255,g:q[1]*255,b:q[2]*255,a:q.length>3?q[3]:1};}
    return null;
  }
  function lum(c){function f(v){v/=255;return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4);}return 0.2126*f(c.r)+0.7152*f(c.g)+0.0722*f(c.b);}
  function ratio(a,b){var x=lum(a),y=lum(b),hi=Math.max(x,y),lo=Math.min(x,y);return (hi+0.05)/(lo+0.05);}
  function sobre(f,b){return {r:f.r*f.a+b.r*(1-f.a),g:f.g*f.a+b.g*(1-f.a),b:f.b*f.a+b.b*(1-f.a),a:1};}
  function fondo(el){
    var capas=[],n=el,imagen=false;
    while(n&&n.nodeType===1){
      var cs=getComputedStyle(n);
      if(cs.backgroundImage&&cs.backgroundImage!=='none')imagen=true;
      var c=parse(cs.backgroundColor);
      if(c&&c.a>0){capas.push(c);if(c.a>=1)break;}
      n=n.parentElement;
    }
    var base=(matchMedia('(prefers-color-scheme: dark)').matches&&getComputedStyle(document.documentElement).colorScheme.indexOf('dark')>=0)
      ?{r:18,g:18,b:18,a:1}:{r:255,g:255,b:255,a:1};
    var r=base;for(var i=capas.length-1;i>=0;i--)r=sobre(capas[i],r);
    return {c:r,imagen:imagen};
  }
  // Texto SVG: el fondo real es la forma que hay debajo (un segmento de barra), no la tarjeta HTML.
  function fondoSvg(el){
    var base=fondo(el.ownerSVGElement||el);
    var r=el.getBoundingClientRect();
    if(r.bottom<0||r.top>innerHeight){el.scrollIntoView({block:'center'});r=el.getBoundingClientRect();}
    var pila=document.elementsFromPoint(r.left+r.width/2,r.top+r.height/2),capas=[];
    for(var i=0;i<pila.length;i++){
      var n=pila[i];
      if(n===el||!(n instanceof SVGElement)||n.tagName==='svg'||n.tagName==='text'||n.tagName==='tspan')continue;
      var cs=getComputedStyle(n),c=parse(cs.fill);
      if(!c)continue;
      c.a=c.a*parseFloat(cs.fillOpacity)*opacidad(n);
      if(c.a>0){capas.push(c);if(c.a>=1)break;}
    }
    var r2=base.c;for(var j=capas.length-1;j>=0;j--)r2=sobre(capas[j],r2);
    return {c:r2,imagen:base.imagen};
  }
  function opacidad(el){var o=1;for(var n=el;n&&n.nodeType===1;n=n.parentElement)o*=parseFloat(getComputedStyle(n).opacity);return o;}
  function oculto(el){
    for(var n=el;n&&n.nodeType===1;n=n.parentElement){
      var cs=getComputedStyle(n);
      if(cs.display==='none'||cs.visibility==='hidden'||n.getAttribute('aria-hidden')==='true')return true;
    }
    var r=el.getBoundingClientRect();return r.width<2||r.height<2;
  }
  function desc(el){var s=el.tagName.toLowerCase();if(el.id)s+='#'+el.id;if(el.classList&&el.classList.length)s+='.'+[].slice.call(el.classList).join('.');return s;}
  var fallos=[],revisados=0,omitidos=0;
  var els=document.body.querySelectorAll('*');
  for(var i=0;i<els.length;i++){
    var el=els[i];
    if(['SCRIPT','STYLE','svg','defs','pattern','line','rect','path','polyline','polygon','circle'].indexOf(el.tagName)>=0)continue;
    var propio=false;
    for(var k=0;k<el.childNodes.length;k++){var h=el.childNodes[k];if(h.nodeType===3&&h.textContent.trim())propio=true;}
    if(!propio||oculto(el))continue;
    if(el.matches('input,button,select,textarea')&&el.disabled)continue;
    var cs=getComputedStyle(el),esSvg=el instanceof SVGElement;
    var fg=parse(esSvg?cs.fill:cs.color);
    if(!fg){omitidos++;continue;}
    var f=esSvg?fondoSvg(el):fondo(el);
    if(f.imagen){omitidos++;continue;}
    fg.a=fg.a*opacidad(el);
    var color=sobre(fg,f.c);
    var tam=parseFloat(cs.fontSize);
    if(esSvg&&el.getScreenCTM)tam*=el.getScreenCTM().a;
    var grande=tam>=24||(tam>=18.66&&parseInt(cs.fontWeight,10)>=700);
    var r=ratio(color,f.c),req=grande?3:4.5;
    revisados++;
    if(r+1e-9<req)fallos.push({el:desc(el),texto:el.textContent.trim().slice(0,40),ratio:Math.round(r*100)/100,minimo:req,tam:Math.round(tam*10)/10});
  }
  return {fallos:fallos,revisados:revisados,omitidos:omitidos};
}
"""

_JS_REFLUJO = r"""
() => {
  var ancho=document.documentElement.clientWidth,doc=document.documentElement.scrollWidth;
  function desplaza(el){for(var n=el.parentElement;n&&n!==document.body;n=n.parentElement){var o=getComputedStyle(n).overflowX;if(o==='auto'||o==='scroll'||o==='hidden')return true;}return false;}
  var culpables=[];
  document.body.querySelectorAll('*').forEach(function(el){
    var cs=getComputedStyle(el);if(cs.display==='none'||cs.position==='fixed')return;
    var r=el.getBoundingClientRect();
    if(r.width>0&&r.right>ancho+1&&!desplaza(el)){
      var s=el.tagName.toLowerCase()+(el.id?'#'+el.id:'')+(el.classList.length?'.'+[].slice.call(el.classList).join('.'):'');
      culpables.push(s+' ('+Math.round(r.right)+' px)');
    }
  });
  return {ancho:ancho,documento:doc,desborda:doc>ancho+1,culpables:culpables.slice(0,6)};
}
"""

_JS_ESPACIADO = r"""
() => {
  // Hoja construida por script (no un <style>): una página con CSP estricta (style-src 'self') rechaza estilos en línea,
  // y entonces la prueba «pasaría» sin haber aplicado nada. ``aplicado`` lo comprueba.
  var css='*{line-height:1.5 !important;letter-spacing:.12em !important;word-spacing:.16em !important}p{margin-bottom:2em !important}';
  var hoja=null,st=null;
  if(typeof CSSStyleSheet==='function'&&'adoptedStyleSheets' in document){
    hoja=new CSSStyleSheet();hoja.replaceSync(css);document.adoptedStyleSheets=document.adoptedStyleSheets.concat([hoja]);
  }else{st=document.createElement('style');st.textContent=css;document.head.appendChild(st);}
  var aplicado=getComputedStyle(document.body).letterSpacing!=='normal';
  var cortados=[];
  document.body.querySelectorAll('*').forEach(function(el){
    var cs=getComputedStyle(el);
    if(cs.display==='none'||!(el.textContent||'').trim())return;
    if(el.matches('svg, svg *'))return;
    var r=el.getBoundingClientRect();if(r.width<=2||r.height<=2)return;
    var recorta=['hidden','clip'].indexOf(cs.overflowX)>=0||['hidden','clip'].indexOf(cs.overflowY)>=0;
    if(recorta&&(el.scrollWidth>el.clientWidth+1||el.scrollHeight>el.clientHeight+1))
      cortados.push(el.tagName.toLowerCase()+(el.className&&typeof el.className==='string'?'.'+el.className.split(' ').join('.'):''));
  });
  if(hoja)document.adoptedStyleSheets=document.adoptedStyleSheets.filter(function(h){return h!==hoja;});
  if(st)st.remove();
  return {cortados:cortados,aplicado:aplicado};
}
"""

_JS_FOCO = r"""
() => {
  var el=document.activeElement;
  if(!el||el===document.body||el===document.documentElement)return null;
  var cs=getComputedStyle(el),visible=false;
  if(cs.outlineStyle!=='none'&&parseFloat(cs.outlineWidth)>0)visible=true;
  if(cs.boxShadow&&cs.boxShadow!=='none')visible=true;
  if(el instanceof SVGElement&&cs.stroke!=='none'&&parseFloat(cs.strokeWidth)>0)visible=true;
  var r=el.getBoundingClientRect();
  var s=el.tagName.toLowerCase()+(el.id?'#'+el.id:'')+(el.getAttribute('class')?'.'+el.getAttribute('class').split(' ').join('.'):'');
  var nombre=(el.getAttribute('aria-label')||el.textContent||el.value||'').trim().slice(0,50);
  return {sel:s,nombre:nombre,indicador:visible,tipo:(el.type||''),ancho:Math.round(r.width),alto:Math.round(r.height)};
}
"""

_JS_OBJETIVOS = r"""
() => {
  var salida=[];
  document.body.querySelectorAll('a[href],button,input:not([type=hidden]),select,textarea,summary,[role=button]').forEach(function(el){
    var cs=getComputedStyle(el);
    if(cs.display==='none'||cs.visibility==='hidden'||cs.display==='inline'||el.closest('[aria-hidden=true]'))return;
    var r=el.getBoundingClientRect();if(r.width<=1||r.height<=1)return;
    if(r.width<24||r.height<24)salida.push((el.tagName.toLowerCase()+(el.className?'.'+String(el.className).split(' ').join('.'):''))+' '+Math.round(r.width)+'x'+Math.round(r.height));
  });
  return salida;
}
"""


def _criterio_axe(etiquetas: Sequence[str]) -> str:
    for t in etiquetas:
        m = re.fullmatch(r"wcag(\d)(\d)(\d+)", t)
        if m:
            return f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
    return "—"


def _auditar_abierta(page, etiqueta: str, ancho: int, axe: Optional[Path], agregar, informe: Informe) -> None:
    """Las comprobaciones que dependen del estado visible de la página abierta (sin teclado)."""
    c = page.evaluate(_JS_CONTRASTE)
    informe.datos[f"contraste {etiqueta}"] = {"revisados": c["revisados"], "omitidos": c["omitidos"]}
    for f in c["fallos"]:
        agregar(Hallazgo("1.4.3", ERROR, f"{etiqueta} contraste {f['ratio']}:1 (mínimo {f['minimo']:g}:1) en «{f['texto']}» ({f['tam']} px)", f["el"]))
    if ancho <= 400:
        r = page.evaluate(_JS_REFLUJO)
        if r["desborda"]:
            agregar(Hallazgo("1.4.10", ERROR, f"{etiqueta} la página se desplaza en horizontal ({r['documento']} px en {r['ancho']} px)",
                             "; ".join(r["culpables"])))
    espaciado = page.evaluate(_JS_ESPACIADO)
    if not espaciado["aplicado"]:
        agregar(Hallazgo("1.4.12", AVISO, f"{etiqueta} no se pudo aplicar el espaciado de texto de prueba: esta comprobación no se hizo"))
    for sel in espaciado["cortados"]:
        agregar(Hallazgo("1.4.12", ERROR, f"{etiqueta} el texto se corta al aumentar el espaciado", sel))
    for o in page.evaluate(_JS_OBJETIVOS):
        agregar(Hallazgo("2.5.8", AVISO, f"{etiqueta} objetivo táctil menor de 24×24 px (WCAG 2.2)", o))
    if axe is not None:
        if not page.evaluate("typeof axe !== 'undefined'"):
            # evaluate y no add_script_tag: una página con CSP estricta (``script-src 'self'``) bloquea el script en línea.
            page.evaluate(axe.read_text(encoding="utf-8"))
        res = page.evaluate("axe.run(document,{runOnly:{type:'tag',values:%s}})" % list(_ETIQUETAS_AXE))
        for v in res["violations"]:
            for nodo in v["nodes"][:5]:
                agregar(Hallazgo(_criterio_axe(v["tags"]), ERROR, f"{etiqueta} axe «{v['id']}»: {v['help']}", "".join(nodo["target"])[:120]))


def auditar_pagina_abierta(page, *, etiqueta: str = "", axe_js: Optional[Path] = None, teclado: bool = False,
                           max_tabs: int = 250) -> Informe:
    """Audita el estado ACTUAL de una página ya abierta (una aplicación de una sola página después de iniciar
    sesión y navegar, por ejemplo). Usa el ancho de ventana que la página tiene; para cambiar de ancho o de
    esquema de color, abre otra con ``Navegador.pagina(..., ancho=..., esquema=...)``."""
    informe = Informe()
    informe.datos["paradas_de_tabulacion"] = []
    ancho = page.evaluate("window.innerWidth")
    axe = Path(axe_js) if axe_js else ruta_axe()
    vistos = set()

    def agregar(h: Hallazgo) -> None:
        clave = (h.criterio, h.mensaje, h.elemento)
        if clave not in vistos:
            vistos.add(clave)
            informe.hallazgos.append(h)

    _auditar_abierta(page, etiqueta or f"[{ancho} px]", ancho, axe, agregar, informe)
    if teclado:
        informe.datos["paradas_de_tabulacion"] = _recorrer_tabulacion(page, max_tabs, agregar)
    return informe


def auditar_en_navegador(
    html: Optional[str] = None, *, url: Optional[str] = None, navegador: Optional[Navegador] = None,
    anchos: Sequence[int] = (1280, 320), esquemas: Sequence[str] = ("light", "dark"),
    axe_js: Optional[Path] = None, teclado: bool = True, max_tabs: int = 250,
) -> Informe:
    """Audita ``html`` (o ``url``) en cada combinación de ancho y esquema de color.

    Devuelve un ``Informe``; ``informe.datos`` trae el recorrido de tabulación y los conteos."""
    informe = Informe()
    informe.datos["paradas_de_tabulacion"] = []
    propio = navegador is None
    nav = navegador or Navegador()
    axe = Path(axe_js) if axe_js else ruta_axe()
    vistos = set()

    def agregar(h: Hallazgo) -> None:
        clave = (h.criterio, h.mensaje, h.elemento)
        if clave not in vistos:
            vistos.add(clave)
            informe.hallazgos.append(h)

    try:
        for esquema in esquemas:
            for ancho in anchos:
                etiqueta = f"[{esquema}, {ancho} px]"
                with nav.pagina(html, url=url, ancho=ancho, esquema=esquema) as page:
                    _auditar_abierta(page, etiqueta, ancho, axe, agregar, informe)
                    if teclado and ancho == max(anchos) and esquema == esquemas[0]:
                        paradas = _recorrer_tabulacion(page, max_tabs, agregar)
                        informe.datos["paradas_de_tabulacion"] = paradas
    finally:
        if propio:
            nav.cerrar()
    return informe


_TIPOS_COMPUESTOS = frozenset({"date", "time", "datetime-local", "month", "week"})


def _aro_del_navegador(parada: Dict[str, Any], anteriores: List[Dict[str, Any]]) -> bool:
    """Un campo de fecha/hora nativo tiene varias paradas (día, mes, año y el botón del calendario) y en la
    última el aro lo dibuja el navegador sobre el botón interno: el elemento no lo reporta como ``:focus-visible``.
    Se acepta SOLO si las paradas anteriores del mismo campo sí mostraban el aro del autor (no se quitó el foco)."""
    return bool(parada.get("tipo") in _TIPOS_COMPUESTOS and anteriores and anteriores[-1]["sel"] == parada["sel"] and anteriores[-1]["indicador"])


def _recorrer_tabulacion(page, max_tabs: int, agregar) -> List[Dict[str, Any]]:
    paradas: List[Dict[str, Any]] = []
    page.evaluate("() => { document.activeElement && document.activeElement.blur && document.activeElement.blur(); window.scrollTo(0, 0); }")
    salio = False
    for _ in range(max_tabs):
        page.keyboard.press("Tab")
        p = page.evaluate(_JS_FOCO)
        if p is None:
            salio = True
            break
        if paradas and p["sel"] == paradas[0]["sel"] and p["nombre"] == paradas[0]["nombre"]:
            salio = True  # dio la vuelta al documento
            break
        paradas.append(p)
        if not p["indicador"] and not _aro_del_navegador(p, paradas[:-1]):
            agregar(Hallazgo("2.4.7", ERROR, "El elemento recibe el foco pero no muestra ningún indicador visible", f"{p['sel']} «{p['nombre']}»"))
    if not salio:
        agregar(Hallazgo("2.1.2", ERROR, f"El foco no salió del documento tras {max_tabs} pulsaciones de Tab (posible trampa de teclado)"))
    return paradas
