"""python -m asistente indexar [--paciente ID]   deja al día la base vectorial (guías + pacientes con consentimiento).

Así la primera pregunta sobre un paciente no espera a que se calculen sus embeddings (NFR-01).
Los pacientes sin consentimiento de IA vigente no se indexan y, si estaban, se sacan (SEC-03).
"""

from __future__ import annotations

import argparse
import contextlib
import sys
import time
from typing import Optional, Sequence


def indexar_paciente(conn_exp, expediente_id: int, indice) -> Optional[int]:
    """Sincroniza un paciente; ``None`` si no tiene consentimiento (y queda fuera del índice)."""
    from asistente.fragmentos import fragmentos_del_expediente
    from privacidad.consentimiento_ia import estado_consentimiento_ia

    if not estado_consentimiento_ia(conn_exp, expediente_id).ia_habilitada:
        indice.olvidar_paciente(expediente_id)
        return None
    return indice.sincronizar_paciente(expediente_id, fragmentos_del_expediente(conn_exp, expediente_id))


def main(argv: Optional[Sequence[str]] = None) -> int:
    for flujo in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError):
            flujo.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="python -m asistente", description="Base vectorial del asistente.")
    sub = p.add_subparsers(dest="comando", required=True)
    i = sub.add_parser("indexar", help="Guías y pacientes con detalle y consentimiento.")
    i.add_argument("--paciente", type=int, help="Solo este paciente (id del expediente).")
    args = p.parse_args(argv)

    from asistente.indice import indice
    from datos.escenario import cohorte_con_detalle
    from historia_clinica.db import conectar_expediente

    inicio = time.monotonic()
    idx = indice()
    print(f"Guías: {idx.asegurar_guias()} fragmentos recalculados.")
    conn = conectar_expediente()
    try:
        pacientes = [args.paciente] if args.paciente else [pid for pid, _ in cohorte_con_detalle(conn)]
        indexados = omitidos = 0
        for pid in pacientes:
            r = indexar_paciente(conn, pid, idx)
            if r is None:
                omitidos += 1
            else:
                indexados += 1
        print(f"Pacientes: {indexados} al día, {omitidos} sin consentimiento (fuera del índice). "
              f"{idx.cuantos()} fragmentos en total, {time.monotonic() - inicio:.0f} s.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
