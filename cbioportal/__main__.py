"""Carga la base de datos del copiloto con pacientes de cBioPortal.

Ejemplos:

    # 25 pacientes de mama y 25 de pulmón de MSK-CHORD
    python -m cbioportal --db data/copiloto.db --fecha-referencia 2026-09-29

    # Pacientes puntuales, y también en la base de búsqueda/360
    python -m cbioportal --db data/copiloto.db --pacientes P-0000015 P-0000036 \\
        --db-pacientes patients/db/pacientes.db --oncologo-id 1
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from historia_clinica.db import crear_conexion

from .cliente import URL_PUBLICA, ClienteCBioPortal
from .importador import ESTUDIO_POR_DEFECTO, TIPOS_POR_DEFECTO, FuenteCBioPortal, importar_estudio
from .modulo_pacientes import volcar_en_modulo_pacientes

RUTA_DB_POR_DEFECTO = Path("data") / "copiloto.db"


def _argumentos(argv):
    p = argparse.ArgumentParser(prog="python -m cbioportal", description=__doc__.split("\n\n")[0])
    p.add_argument("--db", type=Path, default=RUTA_DB_POR_DEFECTO, help=f"Expediente SQLite (por defecto {RUTA_DB_POR_DEFECTO}).")
    p.add_argument("--estudio", default=ESTUDIO_POR_DEFECTO, help=f"Estudio de cBioPortal (por defecto {ESTUDIO_POR_DEFECTO}).")
    p.add_argument("--pacientes", nargs="+", help="Ids de paciente del estudio. Sin esto, se eligen por tipo de cáncer.")
    p.add_argument("--tipos", nargs="+", default=list(TIPOS_POR_DEFECTO), help="Tipos de cáncer (CANCER_TYPE de cBioPortal).")
    p.add_argument("--por-tipo", type=int, default=25, help="Pacientes por tipo de cáncer (por defecto 25).")
    p.add_argument("--fecha-referencia", type=date.fromisoformat, default=date.today(),
                   help="Fecha del último evento de cada paciente (AAAA-MM-DD). Fíjela para re-importar con las mismas fechas.")
    p.add_argument("--db-pacientes", type=Path, help="Base del módulo de pacientes (PAC-02/03) donde volcarlos también.")
    p.add_argument("--oncologo-id", type=int, help="Oncólogo a cargo en el módulo de pacientes (requerido con --db-pacientes).")
    p.add_argument("--url", default=URL_PUBLICA, help="URL de la API (para una instancia institucional).")
    args = p.parse_args(argv)
    if args.db_pacientes and args.oncologo_id is None:
        p.error("--db-pacientes requiere --oncologo-id.")
    return args


def main(argv=None) -> int:
    args = _argumentos(argv)
    args.db.parent.mkdir(parents=True, exist_ok=True)
    conn = crear_conexion(str(args.db))
    cliente = ClienteCBioPortal(args.url, token=os.environ.get("CBIOPORTAL_TOKEN"))
    fuente = FuenteCBioPortal(cliente, args.fecha_referencia)

    conn_pac = None
    if args.db_pacientes:
        from patients import db as db_pacientes

        conn_pac = db_pacientes.conectar(args.db_pacientes)
        db_pacientes.inicializar(conn_pac)

    def al_importar(i, total, r):
        s = r.sincronizacion
        estado = f"paciente {r.paciente_id} ({'nuevo' if r.paciente_nuevo else 'existente'}): {s.mensaje}" if s.exito else f"FALLÓ: {s.mensaje}"
        if s.exito and conn_pac is not None:
            estado += f" | módulo de pacientes: id {volcar_en_modulo_pacientes(conn_pac, r, args.fecha_referencia, args.oncologo_id)}"
        print(f"[{i}/{total}] {r.identificacion} -> {estado}", flush=True)

    if not args.pacientes:
        print(f"Seleccionando pacientes de {args.estudio} ({', '.join(args.tipos)}; {args.por_tipo} por tipo)...", flush=True)
    resultados = importar_estudio(conn, fuente, args.estudio, args.pacientes, args.tipos, args.por_tipo, al_importar)
    fallidos = [r for r in resultados if not r.sincronizacion.exito]
    print(f"Listo: {len(resultados) - len(fallidos)} importado(s), {len(fallidos)} con fallo. Base: {args.db}")
    return 1 if fallidos else 0


if __name__ == "__main__":
    sys.exit(main())
