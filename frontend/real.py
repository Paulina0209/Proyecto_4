"""La interfaz web con los datos REALES del sistema, en un solo comando.

    python -m frontend.real                    # prepara lo que falte y sirve https://127.0.0.1:8443
    python -m frontend.real --puerto 9443
    python -m frontend.real --sin-indexar      # no espera a la base vectorial (se llena sola al preguntar)
    python -m frontend.real --workers 4        # varios procesos (NFR-05)

A diferencia de ``python -m frontend.demo`` (pacientes y usuarios inventados), aquí:

    - los pacientes son los de cBioPortal (MSK-CHORD, desidentificados): capa de trabajo
      ``data/copiloto.db`` + ``patients/db/pacientes.db``, armada desde la capa base ``data/cbioportal/``;
    - los usuarios son los de nuestra base ``data/usuarios.db`` (los crea el escenario).

Pasos, cada uno solo si hace falta:
    1. capas de datos (``python -m datos preparar``);
    2. certificado local autofirmado en ``certs/`` (el sistema solo atiende HTTPS, SEC-02);
    3. base vectorial del asistente (``python -m asistente indexar``; sin llave de OpenAI se omite);
    4. servidor TLS con la pasarela ``frontend.servidor:app``.
"""
from __future__ import annotations

import argparse
import contextlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional, Sequence, Tuple

RAIZ = Path(__file__).resolve().parent.parent
CARPETA_CERTS = RAIZ / "certs"
#: Si al certificado le queda menos que esto, se renueva antes de arrancar.
MARGEN_CERTIFICADO = timedelta(days=2)


def preparar_datos(aviso: Callable[[str], None] = print) -> int:
    from datos import capas
    from datos.__main__ import preparar

    if capas.base_existe() and capas.es_trabajo_de_escenario(capas.RutasTrabajo.por_defecto()):
        from datos.escenario import asegurar_equipo_y_ordenes

        # Capas armadas antes del equipo de atención y las órdenes médicas: se completan sin tocar lo demás.
        equipos, ordenes = asegurar_equipo_y_ordenes(capas.RutasTrabajo.por_defecto())
        extra = "".join([f" Equipo de atención asignado ({equipos})." if equipos else "", f" Órdenes de demostración: {ordenes}." if ordenes else ""])
        aviso(f"1/3 Datos: capa base de cBioPortal y capa de trabajo listas.{extra}")
        return 0
    aviso("1/3 Datos: armando las capas (la primera vez descarga de cBioPortal, toma unos minutos)...")
    return preparar(aviso=aviso)


def _vigente(cert: Path, ahora: datetime) -> bool:
    from cryptography import x509

    try:
        vence = x509.load_pem_x509_certificate(cert.read_bytes()).not_valid_after_utc
    except (OSError, ValueError):
        return False
    return vence - ahora > MARGEN_CERTIFICADO


def asegurar_certificado(carpeta: Path = CARPETA_CERTS, ahora: Optional[datetime] = None,
                         aviso: Callable[[str], None] = print) -> Tuple[Path, Path]:
    """Reutiliza el certificado local si sigue vigente; si falta o está por vencer, crea uno nuevo."""
    from seguridad.servidor_tls import generar_certificado_local

    cert, clave = carpeta / "localhost.pem", carpeta / "localhost-clave.pem"
    if clave.is_file() and _vigente(cert, ahora or datetime.now(timezone.utc)):
        aviso(f"2/3 Certificado: {cert} vigente.")
        return cert, clave
    cert, clave = generar_certificado_local(carpeta)
    aviso(f"2/3 Certificado: autofirmado nuevo en {carpeta} (el navegador mostrará un aviso: es solo local).")
    return cert, clave


def indexar(aviso: Callable[[str], None] = print) -> None:
    """Deja al día la base vectorial. Nunca impide arrancar: lo que falte se indexa al preguntar."""
    from core import llm_config

    if not llm_config.obtener_api_key():
        aviso("3/3 Asistente: sin OPENAI_API_KEY en .env se omite la base vectorial (el chat responderá que no puede).")
        return
    aviso("3/3 Asistente: actualizando la base vectorial (solo recalcula lo que cambió)...")
    from asistente.__main__ import main as asistente_main

    try:
        if asistente_main(["indexar"]) != 0:
            aviso("    Algunos pacientes quedaron pendientes; se indexan solos cuando se pregunte por ellos.")
    except Exception as exc:  # noqa: BLE001 - p. ej. sin red: el servidor arranca igual
        aviso(f"    No se pudo indexar ahora ({type(exc).__name__}); se intentará al preguntar.")


def usuarios_activos(ruta: Optional[Path] = None) -> list:
    """(usuario, rol) de las cuentas activas de la base de usuarios: las del escenario y las creadas después."""
    import sqlite3

    from datos import capas

    ruta = ruta or capas.RutasTrabajo.por_defecto().usuarios
    with contextlib.closing(sqlite3.connect(f"file:{Path(ruta).as_posix()}?mode=ro", uri=True)) as conn:
        return conn.execute("SELECT nombre_usuario, rol FROM usuarios WHERE activo = 1 ORDER BY id").fetchall()


def mostrar_accesos(puerto: int, aviso: Callable[[str], None] = print, ruta_usuarios: Optional[Path] = None) -> None:
    from datos.escenario import CLAVE_ESCENARIO, USUARIOS

    del_escenario = {u for u, _r, _n in USUARIOS}
    aviso(f"\nInterfaz: https://127.0.0.1:{puerto}   (Ctrl+C para detener)")
    aviso(f"Usuarios activos (base propia data/usuarios.db). Los del escenario usan la contraseña de demo {CLAVE_ESCENARIO}:")
    for usuario, rol in usuarios_activos(ruta_usuarios):
        aviso(f"  {usuario:<15} {rol:<22} {'' if usuario in del_escenario else '(creado en el sistema, contraseña propia)'}")
    aviso("")


def argumentos_servidor(cert: Path, clave: Path, puerto: int, host: str, workers: int) -> list:
    return ["--app", "frontend.servidor:app", "--host", host, "--port", str(puerto),
            "--cert", str(cert), "--key", str(clave), "--workers", str(workers)]


def main(argv: Optional[Sequence[str]] = None) -> int:
    for flujo in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError):
            flujo.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="python -m frontend.real", description=__doc__.split("\n\n")[0])
    p.add_argument("--puerto", type=int, default=8443)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--workers", type=int, default=1, help="Procesos que atienden en paralelo (NFR-05).")
    p.add_argument("--sin-indexar", action="store_true", help="Arranca sin actualizar la base vectorial.")
    args = p.parse_args(argv)

    if preparar_datos() != 0:
        return 1
    cert, clave = asegurar_certificado()
    if args.sin_indexar:
        print("3/3 Asistente: sin indexar ahora (cada paciente se indexa al abrirlo o preguntar por él).")
    else:
        indexar()
    mostrar_accesos(args.puerto)

    from seguridad.servidor_tls import main as servidor_main

    return servidor_main(argumentos_servidor(cert, clave, args.puerto, args.host, args.workers))


if __name__ == "__main__":
    sys.exit(main())
