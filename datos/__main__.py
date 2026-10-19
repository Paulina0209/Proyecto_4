"""python -m datos preparar | reiniciar --confirmar | estado | base   (ver docs/datos.md)"""

from __future__ import annotations

import argparse
import contextlib
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Optional, Sequence

from datos import capas, escenario


def _solo_lectura(ruta: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{Path(ruta).as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def preparar(sin_red: bool = False, aviso=print) -> int:
    rutas = capas.RutasTrabajo.por_defecto()
    if not capas.base_existe():
        if sin_red:
            if not (rutas.expediente.is_file() and rutas.pacientes.is_file()):
                aviso("Sin capa base y sin bases que adoptar: corra una vez con internet (python -m datos preparar).")
                return 1
            aviso(f"  Sin red: se adoptan las bases actuales como capa base ({capas.CARPETA_BASE}).")
            capas.adoptar_como_base(rutas.expediente, rutas.pacientes)
        else:
            aviso(f"Capa base ({capas.CARPETA_BASE}) desde cBioPortal:")
            resultado = capas.construir_base(aviso=aviso)
            if resultado.detalle_fallido:
                aviso(f"  Sin detalle (se reintenta en la próxima): {', '.join(resultado.detalle_fallido)}")
    if capas.es_trabajo_de_escenario(rutas):
        aviso("La capa de trabajo ya está preparada. Para descartar los cambios: python -m datos reiniciar --confirmar")
        return 0
    respaldo = capas.respaldar(rutas)
    if respaldo:
        aviso(f"  Lo que había en la capa de trabajo se respaldó en {respaldo}")
    resumen = capas.construir_trabajo(rutas)
    aviso(f"Capa de trabajo lista: {resumen.cohorte} pacientes con detalle, consentimientos {resumen.consentimientos}.")
    return 0


def reiniciar(confirmar: bool, aviso=print) -> int:
    rutas = capas.RutasTrabajo.por_defecto()
    if not confirmar:
        aviso("Esto DESCARTA todo lo registrado en la capa de trabajo (consultas, decisiones, consentimientos...)")
        aviso("y vuelve a la capa base + escenario. Para hacerlo: python -m datos reiniciar --confirmar")
        return 1
    resumen = capas.construir_trabajo(rutas)
    aviso(f"Capa de trabajo reiniciada: {resumen.cohorte} pacientes con detalle, consentimientos {resumen.consentimientos}.")
    return 0


def estado(aviso=print) -> int:
    from privacidad.consentimiento_ia import estado_consentimiento_ia

    rutas = capas.RutasTrabajo.por_defecto()
    aviso(f"CAPA BASE (cBioPortal, solo lectura) — {capas.CARPETA_BASE}")
    if capas.base_existe():
        with contextlib.closing(_solo_lectura(capas.BASE_EXPEDIENTE)) as e, contextlib.closing(_solo_lectura(capas.BASE_PACIENTES)) as p:
            aviso(f"  {p.execute('SELECT COUNT(*) FROM pacientes').fetchone()[0]} pacientes en el índice; "
                  f"{len(escenario.cohorte_con_detalle(e))} con detalle completo")
    else:
        aviso("  No existe. python -m datos preparar")
    aviso("\nCAPA DE TRABAJO (la que usa el sistema)")
    for ruta in rutas.todas():
        aviso(f"  {ruta} {'' if ruta.is_file() else '(no existe)'}")
    if not capas.es_trabajo_de_escenario(rutas):
        aviso("  No está armada con el escenario. python -m datos preparar")
        return 1
    with contextlib.closing(_solo_lectura(rutas.expediente)) as e, contextlib.closing(_solo_lectura(rutas.pacientes)) as p, \
            contextlib.closing(_solo_lectura(rutas.usuarios)) as u:
        aplicado = escenario.resumen_aplicado(e)
        aviso(f"  Escenario v{aplicado['version']} aplicado el {aplicado['aplicado_en'][:16]}")
        roles = Counter(f["rol"] for f in u.execute("SELECT rol FROM usuarios WHERE activo = 1"))
        aviso(f"  Usuarios activos por rol: {dict(roles)} (contraseña de demo: {escenario.CLAVE_ESCENARIO})")
        por_oncologo = dict(p.execute("SELECT oncologo_id, COUNT(*) FROM pacientes GROUP BY 1").fetchall())
        aviso(f"  Pacientes por oncólogo (id): {por_oncologo}")
        cohorte = escenario.cohorte_con_detalle(e)
        estados = Counter(estado_consentimiento_ia(e, pid).etiqueta for pid, _ in cohorte)
        aviso(f"  Consentimiento de IA en la cohorte ({len(cohorte)}): {dict(estados)}  (ahora, con lo registrado después)")
        consultas = e.execute("SELECT COUNT(*) FROM consultas").fetchone()[0]
        aviso(f"  Consultas: {consultas} ({aplicado['consultas_de_revision']} de revisión del escenario)")
        ejemplos = {}
        for pid, cbio in cohorte:
            ejemplos.setdefault(estado_consentimiento_ia(e, pid).etiqueta, cbio)
        aviso("  Un paciente de ejemplo por estado de consentimiento: "
              + ", ".join(f"{k}={v}" for k, v in sorted(ejemplos.items())))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    for flujo in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError):
            flujo.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="python -m datos", description="Capas de datos del copiloto (ver docs/datos.md).")
    sub = p.add_subparsers(dest="comando", required=True)
    pr = sub.add_parser("preparar", help="Arma lo que falte de las dos capas.")
    pr.add_argument("--sin-red", action="store_true", help="Sin cBioPortal: adopta las bases actuales como base.")
    re_ = sub.add_parser("reiniciar", help="Descarta los cambios: base + escenario de nuevo.")
    re_.add_argument("--confirmar", action="store_true")
    sub.add_parser("estado", help="Qué hay en cada capa.")
    sub.add_parser("base", help="Completa la capa base desde cBioPortal (índice y cohorte).")
    args = p.parse_args(argv)
    if args.comando == "preparar":
        return preparar(args.sin_red)
    if args.comando == "reiniciar":
        return reiniciar(args.confirmar)
    if args.comando == "base":
        capas.construir_base()
        return 0
    return estado()


if __name__ == "__main__":
    sys.exit(main())
