"""
Convierte lo que ya se descargo de Kontent.ai en un .html crudo --
sin estilos, sin armar arbol de navegacion propio. Concatena el
content_html/footnotes_html tal cual los tiene ESMO, seccion por
seccion, y ademas extrae el texto de los nodos del diagrama (la
info del algoritmo de tratamiento vive SOLO ahi en varias
secciones -- omitirla perderia recomendaciones clinicas reales).

No hace requests de red -- solo transforma datos que downloadContent.py
ya bajo.
"""

import html as html_module
import json


def _is_empty_richtext(value):
    """El rich_text vacio de Kontent.ai no es None, es '<p><br></p>'
    -- hay que filtrarlo explicitamente o queda un parrafo vacio
    dando vueltas en el HTML final."""

    return not value or value.strip() in ("", "<p><br></p>")


def _diagram_nodes_html(diagram_json):
    """Extrae el texto de cada nodo del diagrama GoJS, ordenados de
    arriba a abajo segun su posicion 'loc' (aproxima el orden de
    lectura del algoritmo original). Es la unica fuente de la
    recomendacion en varias secciones -- no se puede omitir sin
    perder contenido clinico real."""

    if not diagram_json:
        return ""

    try:
        data = json.loads(diagram_json)
    except (json.JSONDecodeError, TypeError):
        return ""

    nodes = data.get("nodeDataArray", [])
    if not nodes:
        return ""

    def y_position(node):
        loc = node.get("loc", "0 0")
        try:
            return float(str(loc).split()[1])
        except (IndexError, ValueError):
            return 0.0

    items = []
    for node in sorted(nodes, key=y_position):
        text = node.get("text", "").strip()
        if text:
            items.append(f"<li>{text}</li>")

    if not items:
        return ""

    return f"<ul>{''.join(items)}</ul>"


def _section_raw_html(node, is_root=False):
    """HTML crudo de UNA seccion (sin bajar a sus subpages).
    is_root=True omite el <h2> -- el titulo del nodo raiz ya se
    muestra como <h1> mas arriba, repetirlo como seccion duplica el
    titulo."""

    parts = []

    if not is_root:
        title = node.get("title") or node.get("codename") or ""
        if title.strip():
            parts.append(f"<h2>{html_module.escape(title.strip())}</h2>")

    content = node.get("content_html")
    if not _is_empty_richtext(content):
        parts.append(content)

    diagram_html = _diagram_nodes_html(node.get("diagram_json"))
    if diagram_html:
        parts.append(diagram_html)

    footnotes = node.get("footnotes_html")
    if not _is_empty_richtext(footnotes):
        parts.append(footnotes)

    return "\n".join(parts)


def render_raw_living_guideline_html(tree, module_id, snapshot_date):
    """tree es la estructura que arma build_section_node() en
    downloadContent.py -- se usa solo para recorrer subpages y
    juntar el HTML crudo de cada seccion en orden, no se persiste
    como estructura propia."""

    title = tree.get("title") or module_id

    sections_html = []

    def walk(node, is_root=False):
        sections_html.append(_section_raw_html(node, is_root=is_root))
        for child in node.get("subpages", []):
            walk(child, is_root=False)

    walk(tree, is_root=True)

    body = "\n".join(s for s in sections_html if s.strip())

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>{html_module.escape(title)}</title>
</head>
<body>
<h1>{html_module.escape(title)}</h1>
<p>Snapshot descargado: {snapshot_date} -- Modulo: {module_id}</p>
{body}
</body>
</html>
"""