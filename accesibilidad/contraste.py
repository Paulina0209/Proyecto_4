"""Contraste de color según WCAG 2.1 (criterios 1.4.3 y 1.4.11).

Fórmulas de la especificación (https://www.w3.org/TR/WCAG21/#dfn-contrast-ratio):
luminancia relativa en sRGB y razón (L1 + 0.05) / (L2 + 0.05).

Umbrales AA:
    - texto normal: 4.5 : 1
    - texto grande (>= 24 px, o >= 18.66 px en negrita): 3 : 1
    - componentes de interfaz y objetos gráficos necesarios para entender el
      contenido (1.4.11): 3 : 1 contra los colores adyacentes
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Tuple

Color = Tuple[int, int, int]

UMBRAL_TEXTO = 4.5
UMBRAL_TEXTO_GRANDE = 3.0
UMBRAL_NO_TEXTO = 3.0

_HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_RGBA = re.compile(r"^rgba?\(\s*(\d+(?:\.\d+)?)[,\s]+(\d+(?:\.\d+)?)[,\s]+(\d+(?:\.\d+)?)(?:[,\s/]+(\d*\.?\d+%?))?\s*\)$")
_NOMBRES = {"white": (255, 255, 255), "black": (0, 0, 0)}


def parsear_color(texto: str, fondo: Optional[Color] = None) -> Color:
    """``#rgb``, ``#rrggbb``, ``rgb()``/``rgba()`` o ``white``/``black`` a (r, g, b).

    Un color con transparencia se compone sobre ``fondo`` (obligatorio en ese caso:
    sin saber qué hay debajo no hay contraste que calcular)."""
    t = texto.strip().lower()
    if t in _NOMBRES:
        return _NOMBRES[t]
    m = _HEX.match(t)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    m = _RGBA.match(t)
    if m:
        r, g, b = (float(m.group(i)) for i in (1, 2, 3))
        a_txt = m.group(4)
        alfa = 1.0
        if a_txt:
            alfa = float(a_txt[:-1]) / 100 if a_txt.endswith("%") else float(a_txt)
        if alfa < 1.0:
            if fondo is None:
                raise ValueError(f"El color translúcido {texto!r} necesita un fondo para calcular su contraste.")
            r, g, b = (alfa * c + (1 - alfa) * f for c, f in zip((r, g, b), fondo))
        return round(r), round(g), round(b)
    raise ValueError(f"No se reconoce el color {texto!r}.")


def _canal(c: int) -> float:
    s = c / 255
    return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4


def luminancia(color: Color) -> float:
    r, g, b = (_canal(c) for c in color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def razon_de_contraste(a: Color, b: Color) -> float:
    la, lb = luminancia(a), luminancia(b)
    claro, oscuro = max(la, lb), min(la, lb)
    return (claro + 0.05) / (oscuro + 0.05)


def es_texto_grande(tamano_px: float, negrita: bool = False) -> bool:
    """Definición de WCAG: 18 pt (24 px) o 14 pt (18.66 px) en negrita."""
    return tamano_px >= 24 or (negrita and tamano_px >= 18.66)


def umbral(*, texto: bool = True, grande: bool = False) -> float:
    if not texto:
        return UMBRAL_NO_TEXTO
    return UMBRAL_TEXTO_GRANDE if grande else UMBRAL_TEXTO


def cumple_aa(primer_plano: Color, fondo: Color, *, texto: bool = True, grande: bool = False) -> bool:
    return razon_de_contraste(primer_plano, fondo) >= umbral(texto=texto, grande=grande)


def mejor_tinta(fondo: Color, opciones: Iterable[Color] = ((11, 11, 11), (255, 255, 255))) -> Color:
    """La tinta (por defecto casi negro o blanco) con más contraste sobre ``fondo``."""
    return max(opciones, key=lambda c: razon_de_contraste(c, fondo))


# --- Tokens de diseño en CSS --------------------------------------------------

_BLOQUE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_VARIABLE = re.compile(r"(--[\w-]+)\s*:\s*([^;}]+)")


def extraer_variables_css(css: str) -> Dict[str, Dict[str, str]]:
    """Variables CSS (``--nombre: valor``) por alcance, tal como están escritas.

    Devuelve ``{selector_o_media: {--variable: valor}}``. Los bloques dentro de
    ``@media`` se identifican como ``"@media (…) :: selector"``."""
    salida: Dict[str, Dict[str, str]] = {}
    contexto: List[str] = []
    # Recorrido simple con pila de @media (el CSS del proyecto no anida otra cosa).
    for m in re.finditer(r"@media[^{]*\{|\}|[^{}]+\{[^{}]*\}", css):
        trozo = m.group(0)
        if trozo.startswith("@media"):
            contexto.append(trozo[:-1].strip())
        elif trozo == "}":
            if contexto:
                contexto.pop()
        else:
            bloque = _BLOQUE.match(trozo)
            if not bloque:
                continue
            variables = {k: v.strip() for k, v in _VARIABLE.findall(bloque.group(2))}
            if variables:
                clave = (" :: ".join(contexto + [bloque.group(1).strip()]))
                salida.setdefault(clave, {}).update(variables)
    return salida


def resolver(valor: str, variables: Dict[str, str], _profundidad: int = 0) -> str:
    """Sustituye ``var(--x)`` por su valor (con ``var(--x, respaldo)`` y variables anidadas)."""
    def reemplazo(m: "re.Match[str]") -> str:
        nombre, respaldo = m.group(1), m.group(2)
        if nombre in variables and _profundidad < 8:
            return resolver(variables[nombre], variables, _profundidad + 1)
        if respaldo is not None:
            return respaldo.strip()
        raise KeyError(nombre)

    return re.sub(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^)]*))?\)", reemplazo, valor)
