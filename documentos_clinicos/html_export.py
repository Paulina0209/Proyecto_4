"""Alternativa accesible al PDF de DOC-02: el mismo ``DocumentoExportable`` como HTML (NFR-03).

Un PDF generado con reportlab no es etiquetado, así que un lector de pantalla tiene que adivinar
su estructura. Este módulo produce, desde el MISMO modelo genérico, un documento HTML
autocontenido (sin scripts ni recursos externos) con la estructura real: idioma, título, un
``<h1>``, secciones con ``<h2>``, tablas con ``<caption>`` y encabezados con ``scope``, el aviso
y las advertencias como secciones propias, modo claro/oscuro, impresión y reflujo a 320 px.

Misma regla que el PDF: sin contenido real no se genera nada (``DocumentoInsuficienteError``).
Todo texto del documento se escapa; no hay forma de inyectar HTML desde los datos clínicos.
"""
from __future__ import annotations

import html
import os
from dataclasses import dataclass
from datetime import datetime
from typing import List

from documentos_clinicos.pdf_export import (
    BloqueTabla,
    BloqueTexto,
    DocumentoExportable,
    DocumentoInsuficienteError,
)

IDIOMA_HTML = "es-MX"


@dataclass(frozen=True)
class ResultadoExportacionHTML:
    """Resultado de una exportación exitosa a HTML."""

    ruta: str
    bytes_escritos: int
    generado_en: datetime


_CSS = """
:root{color-scheme:light dark;--fondo:#ffffff;--tinta:#111111;--tinta2:#4a4a4a;--enlace:#0b4f9c;--borde:#767676;--rejilla:#767676;
 --encabezado-tabla:#1a3a5c;--sobre-encabezado:#ffffff;--alterna:#f0f3f7;--aviso-fondo:#fff6e0;--aviso-tinta:#6b4e00;--aviso-borde:#8a6d00;
 --adv:#8a1f11;--foco:#0b57d0}
@media (prefers-color-scheme:dark){:root{--fondo:#121212;--tinta:#f0f0f0;--tinta2:#c8c8c8;--enlace:#8ab4f8;--borde:#8c8c8c;--rejilla:#8c8c8c;
 --encabezado-tabla:#2b4d73;--sobre-encabezado:#ffffff;--alterna:#1d2229;--aviso-fondo:#2a2208;--aviso-tinta:#f5d77a;--aviso-borde:#b99a2e;
 --adv:#ff9d8f;--foco:#8ab4f8}}
*{box-sizing:border-box}
body{margin:0;background:var(--fondo);color:var(--tinta);font:1.0625rem/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}
.pagina{max-width:60rem;margin:0 auto;padding:1.5rem 1rem 3rem}
h1{font-size:1.75rem;line-height:1.25;margin:0 0 .5rem}
h2{font-size:1.3rem;line-height:1.3;margin:2rem 0 .75rem}
.meta{display:flex;flex-wrap:wrap;gap:.25rem 2rem;margin:0 0 1rem;color:var(--tinta2)}
.meta div{display:flex;gap:.5rem}.meta dt{font-weight:600}.meta dd{margin:0}
:focus-visible{outline:3px solid var(--foco);outline-offset:2px}
.saltar{position:absolute;left:.5rem;top:-4rem;background:var(--fondo);color:var(--tinta);padding:.6rem .9rem;border:2px solid var(--foco);border-radius:.4rem;z-index:5}
.saltar:focus{top:.5rem}
.aviso{background:var(--aviso-fondo);color:var(--aviso-tinta);border:2px solid var(--aviso-borde);border-radius:.5rem;padding:.25rem 1rem 1rem;margin:1rem 0}
.aviso h2{margin-top:.75rem;font-size:1.1rem}.aviso p{margin:0}
.advertencias{color:var(--adv)}.advertencias ul{margin:0;padding-left:1.25rem}
p{margin:0 0 .9rem;max-width:70ch}
.tabla{overflow-x:auto;margin:0 0 1rem}
table{border-collapse:collapse;width:100%;font-size:1rem}
caption{text-align:left;font-weight:600;padding:.25rem 0 .5rem;color:var(--tinta2)}
th,td{border:1px solid var(--rejilla);padding:.45rem .6rem;text-align:left;vertical-align:top}
thead th{background:var(--encabezado-tabla);color:var(--sobre-encabezado)}
tbody tr:nth-child(even){background:var(--alterna)}
footer{margin-top:2.5rem;color:var(--tinta2);font-size:.95rem}
@media print{body{background:#fff;color:#000}.saltar{display:none}.aviso{border-width:1px}thead th{background:#fff;color:#000;border-bottom:2px solid #000}
 tbody tr:nth-child(even){background:#fff}a{color:#000}}
"""


def _e(texto: object) -> str:
    return html.escape(str(texto), quote=True)


def _parrafos(texto: str) -> str:
    """Un ``<p>`` por bloque separado por línea en blanco; los saltos simples quedan como ``<br>``."""
    trozos = [t for t in (p.strip() for p in texto.replace("\r\n", "\n").split("\n\n")) if t]
    return "".join(f"<p>{_e(t).replace(chr(10), '<br>')}</p>" for t in trozos)


def renderizar_html(documento: DocumentoExportable) -> str:
    """El documento como una página HTML completa y accesible. Lanza ``DocumentoInsuficienteError`` si está vacío."""
    if not documento.tiene_contenido():
        raise DocumentoInsuficienteError(
            "El documento no tiene ninguna sección con contenido; no se genera una versión HTML a partir de información insuficiente."
        )
    partes: List[str] = []
    n_tabla = 0

    if documento.disclaimer:
        partes.append(f'<section class="aviso" aria-labelledby="h-aviso"><h2 id="h-aviso">Aviso importante</h2>{_parrafos(documento.disclaimer)}</section>')

    for i, seccion in enumerate(documento.secciones, start=1):
        if not seccion.tiene_contenido():
            continue
        cuerpo = []
        tablas_de_la_seccion = sum(isinstance(b, BloqueTabla) for b in seccion.bloques)
        dentro = 0
        for bloque in seccion.bloques:
            if isinstance(bloque, BloqueTexto):
                cuerpo.append(_parrafos(bloque.texto))
            elif isinstance(bloque, BloqueTabla):
                n_tabla += 1
                dentro += 1
                titulo = seccion.titulo if tablas_de_la_seccion == 1 else f"{seccion.titulo} (tabla {dentro} de {tablas_de_la_seccion})"
                encabezados = "".join(f'<th scope="col">{_e(h)}</th>' for h in bloque.encabezados)
                filas = "".join("<tr>" + "".join(f"<td>{_e(c)}</td>" for c in fila) + "</tr>" for fila in bloque.filas)
                cuerpo.append(
                    f'<div class="tabla" role="region" aria-labelledby="t{n_tabla}" tabindex="0">'
                    f'<table><caption id="t{n_tabla}">{_e(titulo)}</caption><thead><tr>{encabezados}</tr></thead><tbody>{filas}</tbody></table></div>'
                )
        partes.append(f'<section aria-labelledby="s{i}"><h2 id="s{i}">{_e(seccion.titulo)}</h2>{"".join(cuerpo)}</section>')

    if documento.advertencias:
        items = "".join(f"<li>{_e(a)}</li>" for a in documento.advertencias)
        partes.append(f'<section class="advertencias" aria-labelledby="h-adv"><h2 id="h-adv">Avisos de generación</h2><ul>{items}</ul></section>')

    generado = documento.generado_en
    return (
        f'<!doctype html><html lang="{IDIOMA_HTML}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="color-scheme" content="light dark">'
        f"<title>{_e(documento.titulo)} — {_e(documento.paciente_ref)}</title><style>{_CSS}</style></head>"
        '<body><a class="saltar" href="#contenido">Saltar al contenido</a><div class="pagina">'
        f'<header><h1>{_e(documento.titulo)}</h1>'
        f'<dl class="meta"><div><dt>Paciente</dt><dd>{_e(documento.paciente_ref)}</dd></div>'
        f'<div><dt>Generado</dt><dd><time datetime="{_e(generado.isoformat())}">{_e(generado.strftime("%Y-%m-%d %H:%M"))}</time></dd></div></dl></header>'
        f'<main id="contenido" tabindex="-1">{"".join(partes)}</main>'
        f"<footer><p>Documento generado automáticamente — {_e(documento.paciente_ref)} — {_e(generado.strftime('%Y-%m-%d %H:%M'))}</p></footer>"
        "</div></body></html>"
    )


def exportar_a_html(documento: DocumentoExportable, ruta_destino: str) -> ResultadoExportacionHTML:
    """Escribe la versión HTML accesible de ``documento`` en ``ruta_destino`` (UTF-8)."""
    contenido = renderizar_html(documento)  # falla antes de tocar el disco si no hay contenido
    os.makedirs(os.path.dirname(os.path.abspath(ruta_destino)), exist_ok=True)
    with open(ruta_destino, "w", encoding="utf-8", newline="\n") as f:
        f.write(contenido)
    return ResultadoExportacionHTML(ruta=ruta_destino, bytes_escritos=os.path.getsize(ruta_destino), generado_en=documento.generado_en)
