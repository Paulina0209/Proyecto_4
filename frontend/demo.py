"""Demostración de la interfaz web con datos SINTÉTICOS.

    python -m frontend.demo                    # crea los datos y sirve https://127.0.0.1:8443
    python -m frontend.demo --puerto 9443
    python -m frontend.demo --solo-sembrar     # solo crea las bases en la carpeta y termina

Crea (en ``salida_demo_frontend/`` por defecto) bases nuevas con pacientes, laboratorios, biomarcadores y estudios
inventados, genera un certificado local autofirmado (el sistema solo atiende HTTPS) y arranca el servidor.
Nada de esto toca ``data/`` ni tus bases reales. Abre la dirección en el navegador y acepta el aviso del
certificado autofirmado (es solo de desarrollo). Los usuarios y la contraseña se muestran al arrancar y en la
propia pantalla de acceso.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional, Sequence

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from administracion import metricas_uso as met
from administracion import usuarios as adm
from administracion.demo_metricas import sembrar as sembrar_metricas
from frontend.demo_datos import CLAVE_DEMO, EntornoDemo, sembrar_demo
from frontend.servidor import _pagina_mensaje, crear_app

DESCRIPCION_USUARIOS = [
    {"usuario": "dra.rios", "descripcion": "Oncología: seis pacientes con laboratorios, alertas, imágenes y biomarcadores"},
    {"usuario": "dr.vega", "descripcion": "Oncología: otros dos pacientes (la Dra. Ríos no puede verlos)"},
    {"usuario": "direccion", "descripcion": "Dirección médica: tablero de métricas de uso"},
    {"usuario": "enf.mora", "descripcion": "Enfermería: muestra el aviso de «sin pantallas de expediente»"},
    {"usuario": "admin.demo", "descripcion": "Administración del sistema: tampoco ve expedientes"},
]


class _SinCargador:
    """La carga de detalle desde cBioPortal no aplica a la demo (la API de pacientes la pide si existe el expediente)."""

    def asegurar_detalle(self, conn, paciente_id) -> None:
        return None


def _guardar_metricas(carpeta: Path) -> dict:
    """Las métricas de la demo salen de un periodo de 90 días inventado (``administracion.demo_metricas``), guardado en archivos."""
    fuentes, _director = sembrar_metricas(datetime.now(timezone.utc))
    rutas = {}
    # Solo los accesos y el expediente inventados: las cuentas son las de la propia demo (mismos ids y roles).
    for nombre, conn in zip(("usuarios", "accesos", "expediente"), fuentes.conexiones):
        if nombre == "usuarios":
            continue
        ruta = carpeta / f"metricas_{nombre}.db"
        ruta.unlink(missing_ok=True)
        destino = sqlite3.connect(ruta)
        conn.backup(destino)
        destino.close()
        rutas[nombre] = ruta
    return rutas


def configurar_api_de_pacientes(entorno: EntornoDemo, puerto: int) -> None:
    """Apunta la API de pacientes (que no se modifica) a las bases de la demo y a su PACS de juguete."""
    from patients import api as papi

    papi.DB_PATH = entorno.pacientes_db
    papi.EXPEDIENTE_PATH = entorno.expediente_db
    papi.PACS_FUENTE = entorno.pacs
    papi.VISOR_PLANTILLA = f"https://127.0.0.1:{puerto}/demo/visor?StudyInstanceUIDs={{study_uid}}"
    papi.CARGADOR_DETALLE = _SinCargador()


def construir_app(entorno: EntornoDemo, puerto: int = 8443, metricas: Optional[dict] = None) -> FastAPI:
    configurar_api_de_pacientes(entorno, puerto)
    rutas = metricas or _guardar_metricas(entorno.carpeta)

    @contextmanager
    def fuentes() -> Iterator[met.FuentesMetricas]:
        usuarios = adm.crear_conexion(str(entorno.usuarios_db), check_same_thread=False)
        otras = [met.abrir_solo_lectura(rutas["accesos"]), met.abrir_solo_lectura(rutas["expediente"])]
        try:
            yield met.FuentesMetricas(usuarios, otras)
        finally:
            for c in (usuarios, *otras):
                c.close()

    app = crear_app(usuarios_db=entorno.usuarios_db, fuentes_metricas=fuentes,
                    modo_demo={"clave": CLAVE_DEMO, "usuarios": DESCRIPCION_USUARIOS})

    @app.get("/demo/visor", include_in_schema=False)
    def visor(StudyInstanceUIDs: str = ""):  # noqa: N803 - nombre fijado por la convención de los visores DICOM
        return HTMLResponse(_pagina_mensaje(
            "Visor de demostración",
            f"Aquí se abriría el estudio {StudyInstanceUIDs[:64]}. En la demostración no hay imágenes reales: "
            "en producción este enlace lleva al visor del PACS de la institución."),
            headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"})

    return app


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="python -m frontend.demo", description=__doc__.split("\n\n")[0])
    p.add_argument("--carpeta", type=Path, default=Path("salida_demo_frontend"))
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--puerto", type=int, default=8443)
    p.add_argument("--solo-sembrar", action="store_true", help="Crea las bases y termina, sin arrancar el servidor.")
    args = p.parse_args(argv)

    entorno = sembrar_demo(args.carpeta)
    _guardar_metricas(args.carpeta)
    print(f"Datos sintéticos creados en {args.carpeta.resolve()}")
    if args.solo_sembrar:
        return 0

    import os

    from seguridad.servidor_tls import construir_config, generar_certificado_local

    os.environ.setdefault("COPILOTO_EXPEDIENTE_DB", str(entorno.expediente_db))
    cert, clave = generar_certificado_local(args.carpeta / "certs")
    app = construir_app(entorno, args.puerto)
    print(f"\nAbre https://{args.host}:{args.puerto} (acepta el aviso del certificado autofirmado: es solo de desarrollo).")
    print(f"Contraseña de todos los usuarios: {CLAVE_DEMO}")
    for u in DESCRIPCION_USUARIOS:
        print(f"  {u['usuario']:<11} {u['descripcion']}")
    print("\nCtrl+C para detener.\n")

    import uvicorn

    uvicorn.Server(construir_config(app, args.host, args.puerto, str(cert), str(clave))).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
