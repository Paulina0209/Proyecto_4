"""Línea de comandos de la capa de accesibilidad (NFR-03).

    python -m accesibilidad html  archivo.html [--navegador]     # audita un HTML
    python -m accesibilidad pdf   archivo.pdf                    # audita un PDF
    python -m accesibilidad sistema [--navegador]                # audita lo que el sistema genera hoy

``sistema`` construye con datos sintéticos el tablero de métricas (ADM-02), la exportación
a PDF y la exportación HTML (DOC-02) y los audita. Con ``--navegador`` añade Chromium
(contraste calculado, reflujo a 320 px, espaciado, teclado y axe-core si ``AXE_CORE_JS``
apunta a su ``axe.min.js``). Código de salida: 0 sin errores, 1 con errores.

Un resultado limpio NO significa "accesible": falta la prueba con lector de pantalla
(``docs/accesibilidad.md``, sección «Prueba manual»).
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from accesibilidad.auditoria_html import Informe, auditar_html


def _imprimir(titulo: str, informe: Informe) -> bool:
    estado = "SIN ERRORES" if informe.aprobado else f"{len(informe.errores)} ERROR(ES)"
    print(f"\n== {titulo}: {estado}; {len(informe.avisos)} aviso(s)")
    for h in informe.hallazgos:
        print("  " + str(h))
    return informe.aprobado


def _auditar_html(html: str, navegador: bool) -> Informe:
    informe = auditar_html(html)
    if navegador:
        from accesibilidad.navegador import NavegadorNoDisponible, auditar_en_navegador

        try:
            extra = auditar_en_navegador(html)
            informe.hallazgos.extend(extra.hallazgos)
            informe.datos.update(extra.datos)
        except NavegadorNoDisponible as exc:
            print(f"(Chromium no disponible: {exc}; se omite la parte de navegador.)", file=sys.stderr)
    return informe


def _documento_de_muestra():
    from documentos_clinicos.pdf_export import BloqueTabla, BloqueTexto, DocumentoExportable, SeccionDocumento

    return DocumentoExportable(
        titulo="Resumen de caso (muestra sintética)", paciente_ref="paciente-demo", generado_en=datetime(2026, 1, 1, 9, 0),
        secciones=(
            SeccionDocumento("Diagnóstico", (BloqueTexto("Cáncer de mama triple negativo, estadio II.\n\nSegundo párrafo de ejemplo. " * 20),)),
            SeccionDocumento("Laboratorios", (BloqueTabla(("Fecha", "Prueba", "Valor"), tuple(("2026-01-01", "Hemograma", "Normal") for _ in range(40))),)),
        ),
        disclaimer="Documento generado automáticamente. Verifique antes de compartir.", advertencias=("Aviso de ejemplo.",))


def _sistema(navegador: bool) -> bool:
    ok = True
    try:
        from administracion.demo_metricas import sembrar
        from administracion.metricas_uso import consultar_metricas
        from administracion.panel_metricas import renderizar_panel

        ahora = datetime.now(timezone.utc)
        fuentes, director = sembrar(ahora)
        html = renderizar_panel(consultar_metricas(fuentes, director, via="demo", ahora=ahora))
        ok &= _imprimir("Tablero de métricas de uso (ADM-02)", _auditar_html(html, navegador))
    except ImportError as exc:  # pragma: no cover - depende de los paquetes presentes
        print(f"(Se omite el tablero ADM-02: {exc})", file=sys.stderr)
    try:
        from accesibilidad.pdf import auditar_pdf
        from documentos_clinicos.html_export import renderizar_html
        from documentos_clinicos.pdf_export import exportar_a_pdf

        doc = _documento_de_muestra()
        with tempfile.TemporaryDirectory() as tmp:
            ruta = str(Path(tmp) / "muestra.pdf")
            exportar_a_pdf(doc, ruta)
            ok &= _imprimir("PDF de DOC-02", auditar_pdf(ruta))
        ok &= _imprimir("HTML accesible de DOC-02", _auditar_html(renderizar_html(doc), navegador))
    except ImportError as exc:  # pragma: no cover
        print(f"(Se omite DOC-02: {exc})", file=sys.stderr)
    return ok


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m accesibilidad", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="orden", required=True)
    h = sub.add_parser("html", help="audita un archivo HTML")
    h.add_argument("archivo")
    h.add_argument("--navegador", action="store_true", help="añade las comprobaciones en Chromium (requiere Playwright)")
    p = sub.add_parser("pdf", help="audita un archivo PDF")
    p.add_argument("archivo")
    s = sub.add_parser("sistema", help="audita lo que el sistema genera con datos sintéticos")
    s.add_argument("--navegador", action="store_true")
    args = ap.parse_args(argv)

    if args.orden == "html":
        ok = _imprimir(args.archivo, _auditar_html(Path(args.archivo).read_text(encoding="utf-8"), args.navegador))
    elif args.orden == "pdf":
        from accesibilidad.pdf import auditar_pdf

        ok = _imprimir(args.archivo, auditar_pdf(args.archivo))
    else:
        ok = _sistema(args.navegador)
    print("\nRecuerda: un resultado automático limpio no sustituye la prueba con lector de pantalla (docs/accesibilidad.md).")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
