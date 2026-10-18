"""Auditoría de accesibilidad de un PDF generado (WCAG 2.1 AA aplicado a PDF).

Revisa lo que se puede decidir leyendo el archivo, sin dibujarlo:

    2.4.2   el documento tiene título y pide mostrarlo (/DisplayDocTitle)
    3.1.1   declara su idioma (/Lang)
    2.4.1 / 2.4.5   si tiene varias páginas, tiene marcadores (índice navegable)
    1.4.5 / 1.1.1   el texto es texto real (no una imagen de texto)
    1.4.3   contraste de cada texto contra el fondo que realmente tiene debajo
            (se lee el flujo de contenido: color de relleno, rectángulos rellenos, matrices)
    1.4.4   texto menor de 9 pt (aviso)
    1.3.1   ¿está etiquetado (estructura lógica)? Si no, **aviso**: los lectores de
            pantalla tienen que adivinar el orden de lectura.

Un PDF generado con reportlab no es etiquetado: ese aviso es esperado y es la razón
de existir de la alternativa HTML (``documentos_clinicos.html_export``). Nunca se
convierte en "cumple" por callarlo.

Requiere ``pypdf`` (solo para auditar; el sistema no lo necesita para exportar).
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Tuple

from accesibilidad import contraste as cn
from accesibilidad.auditoria_html import AVISO, ERROR, Hallazgo, Informe

try:
    from pypdf import PdfReader
except ImportError as exc:  # pragma: no cover - depende del entorno
    raise ImportError("auditar_pdf necesita 'pypdf' (pip install pypdf).") from exc

Matriz = Tuple[float, float, float, float, float, float]
_ID: Matriz = (1, 0, 0, 1, 0, 0)
_BLANCO = (255, 255, 255)
_NEGRO = (0, 0, 0)
TAMANO_MINIMO_PT = 9.0
#: Valores que los generadores ponen cuando nadie dio título: no describen nada (WCAG 2.4.2).
_TITULOS_VACIOS = {"untitled", "anonymous", "sin título", "sin titulo", "documento", "document", "sin nombre"}


def _por(m: Matriz, n: Matriz) -> Matriz:
    """Producto m × n con la convención de PDF (vectores fila)."""
    a, b, c, d, e, f = m
    A, B, C, D, E, F = n
    return (a * A + b * C, a * B + b * D, c * A + d * C, c * B + d * D, e * A + f * C + E, e * B + f * D + F)


def _punto(m: Matriz, x: float, y: float) -> Tuple[float, float]:
    return m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]


def _color(operandos: Sequence) -> Optional[Tuple[int, int, int]]:
    v = [float(o) for o in operandos]
    clamp = lambda x: max(0, min(255, round(x * 255)))  # noqa: E731
    if len(v) == 1:
        return (clamp(v[0]),) * 3
    if len(v) == 3:
        return clamp(v[0]), clamp(v[1]), clamp(v[2])
    if len(v) == 4:  # CMYK ingenuo (suficiente para detectar grises claros)
        c, m, y, k = v
        return clamp((1 - c) * (1 - k)), clamp((1 - m) * (1 - k)), clamp((1 - y) * (1 - k))
    return None


def _nombre_fuentes(pagina) -> Dict[str, str]:
    try:
        fuentes = pagina["/Resources"]["/Font"]
    except (KeyError, TypeError):
        return {}
    salida = {}
    for nombre, ref in fuentes.items():
        try:
            salida[str(nombre)] = str(ref.get_object().get("/BaseFont", ""))
        except Exception:  # noqa: BLE001
            salida[str(nombre)] = ""
    return salida


def _texto_de(operandos: Sequence) -> str:
    partes = []
    for o in operandos:
        if isinstance(o, (list, tuple)):
            partes.append(_texto_de(o))
        elif isinstance(o, (bytes, bytearray)):
            partes.append(bytes(o).decode("cp1252", errors="replace"))
        elif isinstance(o, str):
            partes.append(o)
    return "".join(partes)


def textos_con_contraste(pagina) -> List[dict]:
    """Cada texto dibujado en la página con su color, tamaño (pt), si es negrita y el fondo que tiene debajo."""
    from pypdf.generic import ContentStream

    contenido = pagina.get_contents()
    if contenido is None:
        return []
    cs = ContentStream(contenido, pagina.pdf)
    fuentes = _nombre_fuentes(pagina)
    ctm, pila = _ID, []
    relleno: Tuple[int, int, int] = _NEGRO
    fuente, tam = "", 0.0
    tm = tlm = _ID
    lead = 0.0
    modo = 0
    ruta: List[Tuple[float, float, float, float]] = []
    rellenos: List[Tuple[float, float, float, float, Tuple[int, int, int]]] = []
    salida: List[dict] = []

    def dibuja(texto: str) -> None:
        if modo == 3 or not texto.strip():
            return
        x, y = _punto(ctm, *_punto(tm, 0, 0))
        escala = abs(tm[3]) * abs(ctm[3]) if tm[3] else abs(ctm[3])
        tam_pt = tam * (escala or 1)
        yc = y + tam_pt * 0.3
        fondo = _BLANCO
        for x0, y0, x1, y1, c in reversed(rellenos):
            if x0 - 0.5 <= x <= x1 + 0.5 and y0 - 0.5 <= yc <= y1 + 0.5:
                fondo = c
                break
        base = fuentes.get(fuente, "")
        salida.append({"texto": texto.strip()[:40], "color": relleno, "fondo": fondo, "pt": round(tam_pt, 2),
                       "negrita": bool(re.search(r"bold|black|heavy", base, re.I)), "fuente": base})

    for operandos, op in cs.operations:
        op = op.decode() if isinstance(op, bytes) else str(op)
        if op == "q":
            pila.append((ctm, relleno))
        elif op == "Q":
            if pila:
                ctm, relleno = pila.pop()
        elif op == "cm":
            ctm = _por(tuple(float(o) for o in operandos), ctm)  # type: ignore[arg-type]
        elif op in ("rg", "g", "k"):
            relleno = _color(operandos) or relleno
        elif op in ("sc", "scn"):
            nuevo = _color([o for o in operandos if not isinstance(o, str)])
            relleno = nuevo or relleno
        elif op == "re":
            x, y, w, h = (float(o) for o in operandos)
            esquinas = [_punto(ctm, x, y), _punto(ctm, x + w, y), _punto(ctm, x, y + h), _punto(ctm, x + w, y + h)]
            xs, ys = [p[0] for p in esquinas], [p[1] for p in esquinas]
            ruta.append((min(xs), min(ys), max(xs), max(ys)))
        elif op in ("f", "F", "f*", "B", "B*", "b", "b*"):
            rellenos.extend((*r, relleno) for r in ruta)
            ruta = []
        elif op in ("n", "S", "s"):
            ruta = []
        elif op == "BT":
            tm = tlm = _ID
        elif op == "Tf":
            fuente, tam = str(operandos[0]), float(operandos[1])
        elif op == "TL":
            lead = float(operandos[0])
        elif op in ("Td", "TD"):
            tx, ty = float(operandos[0]), float(operandos[1])
            if op == "TD":
                lead = -ty
            tlm = _por((1, 0, 0, 1, tx, ty), tlm)
            tm = tlm
        elif op == "Tm":
            tm = tlm = tuple(float(o) for o in operandos)  # type: ignore[assignment]
        elif op == "T*":
            tlm = _por((1, 0, 0, 1, 0, -lead), tlm)
            tm = tlm
        elif op == "Tr":
            modo = int(operandos[0])
        elif op in ("Tj", "TJ"):
            dibuja(_texto_de(operandos))
        elif op == "'":
            tlm = _por((1, 0, 0, 1, 0, -lead), tlm)
            tm = tlm
            dibuja(_texto_de(operandos))
        elif op == '"':
            tlm = _por((1, 0, 0, 1, 0, -lead), tlm)
            tm = tlm
            dibuja(_texto_de(operandos[2:]))
    return salida


def auditar_pdf(ruta: str) -> Informe:
    """Audita el PDF en ``ruta``; ver el docstring del módulo para lo que cubre."""
    lector = PdfReader(ruta)
    informe = Informe()
    add = informe.hallazgos.append
    raiz = lector.trailer["/Root"]

    # 2.4.2 título
    titulo = (lector.metadata.title if lector.metadata else None) or ""
    marcador = titulo.strip().lower().strip("()")
    if not marcador or marcador in _TITULOS_VACIOS or re.search(r"\.(pdf|docx?|odt|txt)$", marcador):
        add(Hallazgo("2.4.2", ERROR, f"El PDF no tiene un título descriptivo en sus propiedades (/Title = «{titulo.strip()}»)."))
        titulo = ""
    prefs = raiz.get("/ViewerPreferences") or {}
    if titulo.strip() and not prefs.get("/DisplayDocTitle"):
        add(Hallazgo("2.4.2", ERROR, "El PDF tiene título pero no pide mostrarlo (/DisplayDocTitle): la ventana mostraría el nombre del archivo."))

    # 3.1.1 idioma
    idioma = str(raiz.get("/Lang") or "")
    if not re.fullmatch(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*", idioma):
        add(Hallazgo("3.1.1", ERROR, "El PDF no declara idioma (/Lang): el lector de pantalla no sabe qué voz usar."))

    # 2.4.1 / 2.4.5 marcadores
    paginas = len(lector.pages)
    if paginas >= 2 and not lector.outline:
        add(Hallazgo("2.4.5", ERROR, f"El PDF tiene {paginas} páginas y ningún marcador (índice de navegación)."))

    # Etiquetado 1.3.1 (aviso: depende del generador)
    marcado = (raiz.get("/MarkInfo") or {}).get("/Marked")
    if not (marcado and "/StructTreeRoot" in raiz):
        add(Hallazgo("1.3.1", AVISO, "El PDF no está etiquetado (sin /StructTreeRoot): el orden de lectura y las tablas dependen de la "
                                      "heurística del lector de pantalla. Ofrece la versión HTML como alternativa accesible."))
    if lector.is_encrypted:
        add(Hallazgo("4.1.2", AVISO, "El PDF está cifrado: verifica que no impida el acceso a lectores de pantalla."))

    # Texto real + contraste + tamaño
    revisados, sin_texto = 0, []
    vistos = set()
    for n, pagina in enumerate(lector.pages, start=1):
        textos = textos_con_contraste(pagina)
        if not textos and not (pagina.extract_text() or "").strip():
            sin_texto.append(n)
            continue
        for t in textos:
            revisados += 1
            razon = cn.razon_de_contraste(t["color"], t["fondo"])
            grande = cn.es_texto_grande(t["pt"] * 4 / 3, t["negrita"])
            minimo = cn.umbral(texto=True, grande=grande)
            clave = (t["color"], t["fondo"], t["pt"])
            if razon + 1e-9 < minimo and clave not in vistos:
                vistos.add(clave)
                add(Hallazgo("1.4.3", ERROR, f"Página {n}: contraste {razon:.2f}:1 (mínimo {minimo:g}:1) en «{t['texto']}» "
                                              f"({t['pt']:g} pt, texto {'#%02x%02x%02x' % t['color']} sobre {'#%02x%02x%02x' % t['fondo']})"))
            clave_t = ("tam", t["pt"])
            if t["pt"] < TAMANO_MINIMO_PT and clave_t not in vistos:
                vistos.add(clave_t)
                add(Hallazgo("1.4.4", AVISO, f"Página {n}: texto de {t['pt']:g} pt («{t['texto']}»), menos de {TAMANO_MINIMO_PT:g} pt."))
    if sin_texto:
        add(Hallazgo("1.4.5", ERROR if len(sin_texto) == paginas else AVISO,
                     f"Páginas sin texto extraíble ({', '.join(map(str, sin_texto))}): probablemente son imágenes de texto."))
    informe.datos["textos_revisados"] = revisados
    informe.datos["paginas"] = paginas
    return informe
