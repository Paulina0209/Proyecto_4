"""Auditor estático de accesibilidad (WCAG 2.1 AA) para HTML generado por el sistema.

No sustituye una prueba con lector de pantalla ni con usuarios (ver
``docs/accesibilidad.md``): revisa lo que SÍ se puede decidir leyendo el
documento, para que una regresión rompa una prueba en vez de llegar a un
médico con baja visión. Cubre, por criterio WCAG:

    1.1.1   alternativa de texto de imágenes y SVG
    1.3.1   encabezados (uno solo, sin saltos), tablas con celdas de encabezado,
            referencias ARIA que apuntan a algo que existe, ``<main>`` único
    1.3.5   ``autocomplete`` en campos de datos personales
    1.4.4   zoom no bloqueado (``viewport``) y texto de menos de 12 px (aviso)
    1.4.3 / 1.4.11  contraste de los tokens de color (``verificar_pares``)
    2.2.1   sin refresco automático
    2.4.2   título de página
    2.4.3   sin ``tabindex`` positivo
    2.4.4   texto de enlace significativo (aviso)
    2.4.7   foco visible: nada quita el contorno sin ofrecer otro indicador
    3.1.1   idioma de la página
    3.3.2   etiquetas en los campos
    4.1.2   nombre accesible de controles y roles ARIA válidos

Un ``error`` es un incumplimiento seguro; un ``aviso`` es una práctica que
conviene revisar a mano. ``Informe.aprobado`` exige cero errores.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple, Union

from accesibilidad import contraste as cn

ERROR = "error"
AVISO = "aviso"


@dataclass(frozen=True)
class Hallazgo:
    criterio: str
    severidad: str
    mensaje: str
    elemento: str = ""

    def __str__(self) -> str:
        donde = f" → {self.elemento}" if self.elemento else ""
        return f"[{self.severidad.upper()} WCAG {self.criterio}] {self.mensaje}{donde}"


@dataclass
class Informe:
    hallazgos: List[Hallazgo] = field(default_factory=list)
    #: Datos de apoyo que no son hallazgos (p. ej. el recorrido de tabulación del navegador).
    datos: Dict[str, Any] = field(default_factory=dict)

    @property
    def errores(self) -> List[Hallazgo]:
        return [h for h in self.hallazgos if h.severidad == ERROR]

    @property
    def avisos(self) -> List[Hallazgo]:
        return [h for h in self.hallazgos if h.severidad == AVISO]

    @property
    def aprobado(self) -> bool:
        return not self.errores

    def criterios(self, severidad: Optional[str] = None) -> Set[str]:
        return {h.criterio for h in self.hallazgos if severidad in (None, h.severidad)}

    def resumen(self) -> str:
        if not self.hallazgos:
            return "Sin hallazgos automáticos (la revisión manual sigue siendo necesaria)."
        return "\n".join(str(h) for h in self.hallazgos)

    def extender(self, otros: Iterable[Hallazgo]) -> "Informe":
        self.hallazgos.extend(otros)
        return self


# --------------------------------------------------------------------------
# Árbol del documento
# --------------------------------------------------------------------------

_VACIOS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_BLOQUES = {"address", "article", "aside", "blockquote", "details", "div", "dl", "fieldset", "figure", "footer", "form", "h1", "h2",
            "h3", "h4", "h5", "h6", "header", "hr", "main", "nav", "ol", "p", "pre", "section", "table", "ul"}
_CIERRA_AL_ABRIR = {
    "li": {"li"}, "dt": {"dt", "dd"}, "dd": {"dt", "dd"}, "td": {"td", "th"}, "th": {"td", "th"},
    "tr": {"td", "th", "tr"}, "option": {"option"}, "thead": {"tbody", "tr", "td", "th"}, "tbody": {"thead", "tbody", "tr", "td", "th"},
}


class Nodo:
    __slots__ = ("tag", "attrs", "hijos", "padre")

    def __init__(self, tag: str, attrs: Dict[str, str], padre: Optional["Nodo"]):
        self.tag, self.attrs, self.hijos, self.padre = tag, attrs, [], padre

    def get(self, nombre: str, defecto: Optional[str] = None) -> Optional[str]:
        return self.attrs.get(nombre, defecto)

    def tiene(self, nombre: str) -> bool:
        return nombre in self.attrs

    def descendientes(self) -> Iterator["Nodo"]:
        for h in self.hijos:
            if isinstance(h, Nodo):
                yield h
                yield from h.descendientes()

    def ancestros(self) -> Iterator["Nodo"]:
        n = self.padre
        while n is not None:
            yield n
            n = n.padre

    def texto_crudo(self) -> str:
        return "".join(h if isinstance(h, str) else h.texto_crudo() for h in self.hijos)

    def descripcion(self) -> str:
        pares = []
        for k in ("id", "class", "role", "aria-label", "href", "name", "type", "scope"):
            if k in self.attrs:
                v = self.attrs[k]
                pares.append(f'{k}="{v[:40]}"')
        return f"<{self.tag}{' ' if pares else ''}{' '.join(pares)}>"

    def __repr__(self) -> str:  # pragma: no cover
        return self.descripcion()


class _Constructor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.raiz = Nodo("#documento", {}, None)
        self.actual = self.raiz

    def _abrir(self, tag: str, attrs) -> Nodo:
        cierra = _CIERRA_AL_ABRIR.get(tag, set())
        if tag in _BLOQUES:
            cierra = cierra | {"p"}
        while self.actual.tag in cierra and self.actual.padre is not None:
            self.actual = self.actual.padre
        nodo = Nodo(tag, {k.lower(): (v if v is not None else "") for k, v in attrs}, self.actual)
        self.actual.hijos.append(nodo)
        return nodo

    def handle_starttag(self, tag, attrs):
        nodo = self._abrir(tag, attrs)
        if tag not in _VACIOS:
            self.actual = nodo

    def handle_startendtag(self, tag, attrs):
        self._abrir(tag, attrs)

    def handle_endtag(self, tag):
        n = self.actual
        while n is not None and n.tag != tag:
            n = n.padre
        if n is not None and n.padre is not None:
            self.actual = n.padre

    def handle_data(self, data):
        self.actual.hijos.append(data)


def parsear(html: str) -> Nodo:
    c = _Constructor()
    c.feed(html)
    c.close()
    return c.raiz


# --------------------------------------------------------------------------
# Utilidades de accesibilidad
# --------------------------------------------------------------------------

_ROLES_VALIDOS = {
    "alert", "alertdialog", "application", "article", "banner", "button", "cell", "checkbox", "columnheader", "combobox", "complementary",
    "contentinfo", "definition", "dialog", "directory", "document", "feed", "figure", "form", "grid", "gridcell", "group", "heading", "img",
    "link", "list", "listbox", "listitem", "log", "main", "marquee", "math", "menu", "menubar", "menuitem", "menuitemcheckbox",
    "menuitemradio", "meter", "navigation", "none", "note", "option", "presentation", "progressbar", "radio", "radiogroup", "region",
    "row", "rowgroup", "rowheader", "scrollbar", "search", "searchbox", "separator", "slider", "spinbutton", "status", "switch", "tab",
    "table", "tablist", "tabpanel", "term", "textbox", "timer", "toolbar", "tooltip", "tree", "treegrid", "treeitem", "graphics-document",
    "graphics-symbol", "graphics-object",
}
_ROLES_CON_NOMBRE = {"button", "link", "checkbox", "radio", "switch", "tab", "textbox", "combobox", "slider", "spinbutton", "menuitem",
                     "option", "searchbox", "progressbar", "meter", "img", "listbox"}
_TIPOS_BOTON = {"submit", "reset", "button"}
_AUTOCOMPLETE = {"name": "name", "nombre": "name", "email": "email", "correo": "email", "username": "username", "usuario": "username",
                 "nombre_usuario": "username", "password": "current-password", "contrasena": "current-password", "tel": "tel",
                 "telefono": "tel", "address": "street-address", "direccion": "street-address", "bday": "bday", "birthdate": "bday"}
_ENLACE_VAGO = {"aqui", "aquí", "clic aqui", "clic aquí", "haz clic aqui", "haz clic aquí", "click here", "here", "mas", "más", "ver mas",
                "ver más", "leer mas", "leer más", "read more", "more", "link", "enlace"}


def _norm(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


def _estilo(nodo: Nodo) -> str:
    return re.sub(r"\s+", "", (nodo.get("style") or "").lower())


def oculto(nodo: Nodo) -> bool:
    """Fuera del árbol de accesibilidad (``aria-hidden``, ``hidden``, ``display:none``, ``visibility:hidden``), él o un ancestro."""
    for n in (nodo, *nodo.ancestros()):
        if n.get("aria-hidden") == "true" or n.tiene("hidden") or n.tag in ("script", "style", "template", "head"):
            return True
        est = _estilo(n)
        if "display:none" in est or "visibility:hidden" in est:
            return True
    return False


def _por_id(raiz: Nodo) -> Dict[str, Nodo]:
    return {n.get("id"): n for n in raiz.descendientes() if n.get("id")}


def texto_visible(nodo: Nodo, *, con_etiquetas: bool = True) -> str:
    """Texto que un lector de pantalla leería de este nodo (incluye ``alt`` y ``aria-label`` de descendientes)."""
    partes: List[str] = []

    def rec(n: Nodo) -> None:
        for h in n.hijos:
            if isinstance(h, str):
                partes.append(h)
                continue
            if h.get("aria-hidden") == "true" or h.tiene("hidden") or h.tag in ("script", "style", "template"):
                continue
            est = _estilo(h)
            if "display:none" in est or "visibility:hidden" in est:
                continue
            if h.tag == "img" and h.get("alt"):
                partes.append(h.get("alt") or "")
            elif con_etiquetas and (h.get("aria-label") or "").strip() and h.tag not in ("svg",):
                partes.append(h.get("aria-label") or "")
            elif h.tag == "svg":
                t = next((x for x in h.hijos if isinstance(x, Nodo) and x.tag == "title"), None)
                partes.append((h.get("aria-label") or "").strip() or (t.texto_crudo() if t else ""))
            else:
                rec(h)

    rec(nodo)
    return _norm(" ".join(partes))


def nombre_accesible(nodo: Nodo, ids: Dict[str, Nodo], etiquetas_for: Dict[str, List[Nodo]]) -> str:
    """Aproximación del nombre accesible (accname): suficiente para detectar controles sin nombre."""
    ref = nodo.get("aria-labelledby")
    if ref:
        t = _norm(" ".join(texto_visible(ids[i], con_etiquetas=True) or (ids[i].get("aria-label") or "") for i in ref.split() if i in ids))
        if t:
            return t
    if (nodo.get("aria-label") or "").strip():
        return _norm(nodo.get("aria-label") or "")
    tag, tipo = nodo.tag, (nodo.get("type") or "text").lower()
    if tag == "img":
        return _norm(nodo.get("alt") or "")
    if tag == "input" and tipo == "image":
        return _norm(nodo.get("alt") or "")
    if tag == "input" and tipo in _TIPOS_BOTON:
        return _norm(nodo.get("value") or {"submit": "Enviar", "reset": "Restablecer"}.get(tipo, ""))
    if tag in ("input", "select", "textarea", "meter", "progress"):
        etiquetas = list(etiquetas_for.get(nodo.get("id") or "", []))
        etiquetas += [a for a in nodo.ancestros() if a.tag == "label"]
        t = _norm(" ".join(texto_visible(e) for e in etiquetas))
        if t:
            return t
        return _norm(nodo.get("title") or "")
    if tag == "svg":
        t = next((x for x in nodo.hijos if isinstance(x, Nodo) and x.tag == "title"), None)
        return _norm(t.texto_crudo()) if t else ""
    if tag == "table":
        c = next((x for x in nodo.hijos if isinstance(x, Nodo) and x.tag == "caption"), None)
        return texto_visible(c) if c else _norm(nodo.get("title") or "")
    t = texto_visible(nodo)
    return t or _norm(nodo.get("title") or "")


def enfocable(nodo: Nodo) -> bool:
    if nodo.tiene("disabled"):
        return False
    ti = nodo.get("tabindex")
    if ti is not None and re.fullmatch(r"-?\d+", ti.strip() or "x"):
        return int(ti) >= 0
    t = nodo.tag
    if t == "a":
        return nodo.tiene("href")
    if t in ("button", "select", "textarea"):
        return True
    if t == "input":
        return (nodo.get("type") or "text").lower() != "hidden"
    if t == "summary":
        return nodo.padre is not None and nodo.padre.tag == "details"
    if t in ("audio", "video"):
        return nodo.tiene("controls")
    return nodo.tiene("contenteditable") and nodo.get("contenteditable") != "false"


def _interactivo(nodo: Nodo) -> bool:
    return enfocable(nodo) or (nodo.get("role") or "").lower() in {"button", "link", "checkbox", "radio", "switch", "tab", "menuitem"}


# --------------------------------------------------------------------------
# Verificaciones del documento
# --------------------------------------------------------------------------


def auditar_html(html: str) -> Informe:
    """Audita un documento HTML completo (o un fragmento) y devuelve el ``Informe``."""
    raiz = parsear(html)
    todos = list(raiz.descendientes())
    informe = Informe()
    add = informe.hallazgos.append
    ids = _por_id(raiz)

    etiquetas_for: Dict[str, List[Nodo]] = {}
    for n in todos:
        if n.tag == "label" and n.get("for"):
            etiquetas_for.setdefault(n.get("for") or "", []).append(n)

    def h(criterio: str, sev: str, msg: str, n: Optional[Nodo] = None) -> None:
        add(Hallazgo(criterio, sev, msg, n.descripcion() if n is not None else ""))

    documento = next((n for n in todos if n.tag == "html"), None)
    es_pagina = documento is not None

    # 3.1.1 idioma, 2.4.2 título, 1.4.4 viewport
    if es_pagina:
        lang = (documento.get("lang") or "").strip()
        if not re.fullmatch(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*", lang):
            h("3.1.1", ERROR, "El elemento <html> no declara un idioma válido (lang).", documento)
        titulo = next((n for n in todos if n.tag == "title"), None)
        if titulo is None or not _norm(titulo.texto_crudo()):
            h("2.4.2", ERROR, "La página no tiene un <title> descriptivo.")
        for m in (n for n in todos if n.tag == "meta"):
            nombre, contenido = (m.get("name") or "").lower(), re.sub(r"\s+", "", (m.get("content") or "").lower())
            if nombre == "viewport":
                if re.search(r"user-scalable=(no|0)", contenido):
                    h("1.4.4", ERROR, "El viewport impide el zoom (user-scalable=no).", m)
                mx = re.search(r"maximum-scale=([\d.]+)", contenido)
                if mx and float(mx.group(1)) < 2:
                    h("1.4.4", ERROR, "El viewport limita el zoom a menos de 200 % (maximum-scale).", m)
            if (m.get("http-equiv") or "").lower() == "refresh" and re.match(r"\d+", (m.get("content") or "")):
                h("2.2.1", ERROR, "Refresco o redirección automática por <meta http-equiv=refresh>: el usuario no puede controlar el tiempo.", m)

    cuerpo = [n for n in todos if not oculto(n) and n.tag not in ("html", "head", "body", "meta", "title", "link")]

    # Landmarks 1.3.1 / 2.4.1
    mains = [n for n in cuerpo if n.tag == "main" or (n.get("role") or "") == "main"]
    if es_pagina and not mains:
        h("2.4.1", ERROR, "La página no tiene región <main>: no hay forma de saltar al contenido.")
    if len(mains) > 1:
        h("1.3.1", ERROR, "Hay más de un <main> visible.", mains[1])
    navs = [n for n in cuerpo if n.tag == "nav" or (n.get("role") or "") == "navigation"]
    if len(navs) > 1:
        for n in navs:
            if not nombre_accesible(n, ids, etiquetas_for) and not (n.get("aria-label") or n.get("aria-labelledby")):
                h("1.3.1", ERROR, "Hay varias regiones de navegación y ésta no tiene nombre (aria-label).", n)

    # Encabezados 1.3.1 / 2.4.6
    heads = [n for n in cuerpo if re.fullmatch(r"h[1-6]", n.tag)]
    h1s = [n for n in heads if n.tag == "h1"]
    if es_pagina and not h1s:
        h("1.3.1", ERROR, "La página no tiene encabezado de nivel 1 (<h1>).")
    if len(h1s) > 1:
        h("1.3.1", AVISO, "Hay más de un <h1>.", h1s[1])
    previo = 0
    for n in heads:
        nivel = int(n.tag[1])
        if not texto_visible(n):
            h("2.4.6", ERROR, "Encabezado vacío.", n)
        if previo and nivel > previo + 1:
            h("1.3.1", ERROR, f"Salto de encabezados: de h{previo} a h{nivel}.", n)
        previo = nivel

    # Imágenes y SVG 1.1.1
    for n in cuerpo:
        if n.tag == "img":
            if not n.tiene("alt") and (n.get("role") or "") not in ("presentation", "none"):
                h("1.1.1", ERROR, "Imagen sin atributo alt (usa alt=\"\" si es decorativa).", n)
            elif (n.get("alt") or "").strip().lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".svg")):
                h("1.1.1", AVISO, "El alt parece un nombre de archivo.", n)
        elif n.tag == "svg" and not any(a.tag == "svg" for a in n.ancestros()):
            rol = (n.get("role") or "").lower()
            if rol in ("presentation", "none"):
                continue
            if not nombre_accesible(n, ids, etiquetas_for):
                h("1.1.1", ERROR, "SVG visible sin nombre accesible (aria-label, <title>) ni aria-hidden=\"true\".", n)
        elif n.tag in ("area",) and not (n.get("alt") or "").strip():
            h("1.1.1", ERROR, "<area> sin alt.", n)

    # ARIA válido y referencias 4.1.2 / 1.3.1
    for n in todos:
        for rol in (n.get("role") or "").lower().split():
            if rol not in _ROLES_VALIDOS:
                h("4.1.2", ERROR, f"role=\"{rol}\" no es un rol ARIA válido.", n)
                break
        for attr in ("aria-labelledby", "aria-describedby", "aria-controls", "aria-owns", "aria-activedescendant"):
            for ref in (n.get(attr) or "").split():
                if ref not in ids:
                    h("1.3.1", ERROR, f"{attr} apunta a #{ref}, que no existe.", n)
        if n.tag == "label" and n.get("for") and n.get("for") not in ids:
            h("1.3.1", ERROR, f"<label for=\"{n.get('for')}\"> no apunta a ningún control.", n)

    conteo_ids: Dict[str, int] = {}
    for n in todos:
        if n.get("id"):
            conteo_ids[n.get("id")] = conteo_ids.get(n.get("id"), 0) + 1
    for i, c in conteo_ids.items():
        if c > 1:
            h("4.1.1", ERROR, f"El id \"{i}\" está repetido {c} veces (rompe etiquetas y referencias ARIA).")

    # aria-hidden con contenido enfocable 4.1.2
    for n in todos:
        if n.get("aria-hidden") == "true" and not any(a.get("aria-hidden") == "true" for a in n.ancestros()):
            for d in (n, *n.descendientes()):
                if enfocable(d):
                    h("4.1.2", ERROR, "Elemento enfocable dentro de aria-hidden=\"true\": el teclado llega a algo que el lector no anuncia.", d)

    # Orden de tabulación 2.4.3
    for n in todos:
        ti = n.get("tabindex")
        if ti is not None and re.fullmatch(r"\d+", ti.strip() or "x") and int(ti) > 0:
            h("2.4.3", ERROR, "tabindex positivo altera el orden natural de foco.", n)

    # Controles: nombre 4.1.2 / etiquetas 3.3.2 / 1.3.5
    for n in cuerpo:
        rol = (n.get("role") or "").lower()
        es_control = enfocable(n) or rol in _ROLES_CON_NOMBRE
        if not es_control:
            continue
        if n.tag == "input" and (n.get("type") or "text").lower() == "hidden":
            continue
        if n.tag == "summary" or n.tag == "a" or rol or n.tag in ("button", "input", "select", "textarea") or n.tiene("tabindex"):
            nombre = nombre_accesible(n, ids, etiquetas_for)
            if not nombre:
                campo = n.tag in ("input", "select", "textarea") and (n.get("type") or "text").lower() not in _TIPOS_BOTON
                if campo and (n.get("placeholder") or "").strip():
                    h("3.3.2", AVISO, "El campo solo tiene placeholder como etiqueta (desaparece al escribir).", n)
                else:
                    h("3.3.2" if campo else "4.1.2", ERROR,
                      "Campo de formulario sin etiqueta asociada." if campo else "Control sin nombre accesible.", n)
        if n.tag == "input" and (n.get("name") or "").lower() in _AUTOCOMPLETE and not n.tiene("autocomplete") \
                and (n.get("type") or "text").lower() not in _TIPOS_BOTON:
            h("1.3.5", ERROR, f"Campo de datos personales ({n.get('name')}) sin atributo autocomplete.", n)

    for n in cuerpo:
        if n.tag == "a" and n.tiene("href"):
            t = texto_visible(n).lower().strip(" .:→»›")
            if t in _ENLACE_VAGO:
                h("2.4.4", AVISO, f"El texto del enlace (\"{t}\") no dice a dónde lleva.", n)
        if n.tag == "details" and not any(isinstance(x, Nodo) and x.tag == "summary" for x in n.hijos):
            h("4.1.2", ERROR, "<details> sin <summary>.", n)
        if n.tag in ("marquee", "blink"):
            h("2.2.2", ERROR, f"<{n.tag}> es contenido en movimiento sin control del usuario.", n)
        if n.tag in ("audio", "video") and n.tiene("autoplay"):
            h("1.4.2", ERROR, "Medio con reproducción automática.", n)

    # Tablas 1.3.1
    for t in (n for n in cuerpo if n.tag == "table"):
        if (t.get("role") or "") in ("presentation", "none"):
            continue
        ths = [x for x in t.descendientes() if x.tag == "th"]
        if not ths:
            h("1.3.1", ERROR, "Tabla de datos sin celdas de encabezado (<th>).", t)
        for th in ths:
            if not th.get("scope") and not th.get("id"):
                h("1.3.1", ERROR, "Celda de encabezado <th> sin scope.", th)
        if not nombre_accesible(t, ids, etiquetas_for) and not t.get("aria-labelledby"):
            h("1.3.1", AVISO, "Tabla sin <caption> ni nombre: difícil de distinguir al navegar entre tablas.", t)

    # CSS incrustado: foco visible 2.4.7, texto pequeño 1.4.4
    css = "\n".join(n.texto_crudo() for n in todos if n.tag == "style")
    if css:
        informe.extender(auditar_css(css))
    return informe


# --------------------------------------------------------------------------
# CSS
# --------------------------------------------------------------------------

_REGLA = re.compile(r"([^{}@][^{}]*)\{([^{}]*)\}")
_SIN_CONTORNO = re.compile(r"outline(?:-style)?\s*:\s*(?:none|0)(?![.\w])", re.I)
_INDICADORES = re.compile(r"(outline\s*:\s*(?!none|0\b)|outline-(?:width|color)|box-shadow|border|stroke|background|fill|text-decoration)", re.I)


def _reglas(css: str) -> List[Tuple[List[str], str]]:
    sin_comentarios = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    salida = []
    for m in _REGLA.finditer(sin_comentarios):
        selectores = [s.strip() for s in m.group(1).split(",") if s.strip()]
        salida.append((selectores, m.group(2)))
    return salida


def auditar_css(css: str) -> List[Hallazgo]:
    hall: List[Hallazgo] = []
    reglas = _reglas(css)
    # 2.4.7: un selector sin contorno necesita una regla :focus/:focus-visible equivalente.
    for selectores, cuerpo in reglas:
        if not _SIN_CONTORNO.search(cuerpo):
            continue
        for sel in selectores:
            if ":focus" in sel:
                if not _INDICADORES.search(cuerpo):
                    hall.append(Hallazgo("2.4.7", ERROR, "Regla de foco que quita el contorno y no ofrece otro indicador.", sel))
                continue
            base = re.sub(r"::?[\w-]+(\([^)]*\))?$", "", sel).strip()
            tiene_sustituto = any(
                any(s.startswith(base) and re.search(r":focus(-visible)?", s) for s in sels) and _INDICADORES.search(c)
                for sels, c in reglas)
            if not tiene_sustituto:
                hall.append(Hallazgo("2.4.7", ERROR, "outline:none sin indicador de foco alternativo (:focus-visible).", sel))
    # 1.4.4: tamaños de texto pequeños (aviso: en SVG la unidad es la del viewBox)
    for selectores, cuerpo in reglas:
        for m in re.finditer(r"font-size\s*:\s*([\d.]+)(px|pt)", cuerpo):
            px = float(m.group(1)) * (4 / 3 if m.group(2) == "pt" else 1)
            if px < 12:
                hall.append(Hallazgo("1.4.4", AVISO, f"Texto de {m.group(1)}{m.group(2)} (menos de 12 px).", ", ".join(selectores)))
    return hall


# --------------------------------------------------------------------------
# Contraste de los tokens de diseño (1.4.3 y 1.4.11)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ParContraste:
    """Un color de primer plano sobre un fondo, con el criterio que le toca.

    ``frente`` y ``fondo`` son colores CSS o ``var(--token)``. ``tipo``: ``"texto"``
    (4.5:1), ``"texto_grande"`` (3:1) o ``"grafico"`` (3:1, 1.4.11)."""
    frente: str
    fondo: str
    tipo: str = "texto"
    descripcion: str = ""


def esquemas_de_color(css: str) -> Dict[str, Dict[str, str]]:
    """Variables CSS efectivas en cada esquema: ``claro``, ``oscuro (sistema)`` y ``oscuro (manual)``."""
    bloques = cn.extraer_variables_css(css)
    claro: Dict[str, str] = {}
    sistema: Dict[str, str] = {}
    manual: Dict[str, str] = {}
    for clave, variables in bloques.items():
        compacto = re.sub(r"\s+", "", clave)
        if "prefers-color-scheme:dark" in compacto:
            sistema.update(variables)
        elif 'data-theme="dark"' in compacto or "data-theme='dark'" in compacto:
            manual.update(variables)
        elif "@media" not in compacto:
            claro.update(variables)
    esquemas = {"claro": dict(claro)}
    if sistema:
        esquemas["oscuro (sistema)"] = {**claro, **sistema}
    if manual:
        esquemas["oscuro (manual)"] = {**claro, **manual}
    return esquemas


def verificar_pares(css: str, pares: Sequence[ParContraste]) -> List[Hallazgo]:
    """Evalúa cada par en cada esquema de color del CSS; un token que falta es un error (no se calla)."""
    hall: List[Hallazgo] = []
    for esquema, variables in esquemas_de_color(css).items():
        for p in pares:
            try:
                fondo = cn.parsear_color(cn.resolver(p.fondo, variables))
                frente = cn.parsear_color(cn.resolver(p.frente, variables), fondo)
            except (KeyError, ValueError) as exc:
                hall.append(Hallazgo("1.4.3", ERROR, f"[{esquema}] no se pudo resolver el color de {p.descripcion or p.frente}: {exc}"))
                continue
            minimo = cn.umbral(texto=p.tipo != "grafico", grande=p.tipo == "texto_grande")
            razon = cn.razon_de_contraste(frente, fondo)
            if razon + 1e-9 < minimo:
                criterio = "1.4.11" if p.tipo == "grafico" else "1.4.3"
                hall.append(Hallazgo(
                    criterio, ERROR,
                    f"[{esquema}] {p.descripcion or p.frente + ' sobre ' + p.fondo}: contraste {razon:.2f}:1, mínimo {minimo:g}:1",
                    f"{p.frente} sobre {p.fondo}"))
    return hall
