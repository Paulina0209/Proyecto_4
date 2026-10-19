"""NFR-01 / NFR-05 — Prueba de carga de la API de pacientes.

Simula médicos que abren expedientes al mismo tiempo (ficha, resumen 360 y
laboratorios de cada paciente) y compara el resultado con NFR-01: el 95 % de
las consultas en menos de 2 s y ninguna con error.

    python -m operacion.carga                               # servidor local sobre una copia de la base real
    python -m operacion.carga --usuarios 25 --workers 2     # NFR-05: dos procesos
    python -m operacion.carga --url https://127.0.0.1:8443 --ca certs/localhost.pem --oncologo 1

Sin ``--url`` levanta su propio servidor TLS (``seguridad.servidor_tls``) sobre
una COPIA de ``data/copiloto.db`` y ``patients/db/pacientes.db`` en una carpeta
temporal: la base real no se modifica. Ese servidor no trae datos de
cBioPortal por la red al abrir un paciente (``COPILOTO_DETALLE_BAJO_DEMANDA=0``),
porque lo que se mide es el sistema, no internet.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Sequence, Tuple

from operacion.latencia import OBJETIVO_CONSULTA_S, PERCENTIL_OBJETIVO, percentil

RAIZ = Path(__file__).resolve().parent.parent
RUTAS_POR_PACIENTE = ("/pacientes/{id}", "/pacientes/{id}/resumen-360", "/pacientes/{id}/laboratorios/marcadores")


@dataclass(frozen=True)
class ResultadoCarga:
    usuarios: int
    peticiones: int
    errores: int
    p50_ms: float
    p95_ms: float
    max_ms: float
    peticiones_por_segundo: float
    objetivo_ms: float = OBJETIVO_CONSULTA_S * 1000
    workers: int = 1
    primer_error: Optional[str] = None

    @property
    def cumple(self) -> bool:
        return self.errores == 0 and self.p95_ms <= self.objetivo_ms

    def a_dict(self) -> dict:
        return asdict(self) | {"cumple": self.cumple}

    def a_texto(self) -> str:
        marca = "✔" if self.cumple else "✘"
        texto = (
            f"  {marca} {self.usuarios:>3} usuarios · {self.workers} proceso(s): {self.peticiones} peticiones, "
            f"p50 {self.p50_ms:.0f} ms, p{PERCENTIL_OBJETIVO} {self.p95_ms:.0f} ms (objetivo {self.objetivo_ms:.0f}), "
            f"máx {self.max_ms:.0f} ms, {self.peticiones_por_segundo:.0f} pet/s, errores {self.errores}"
        )
        return texto + (f"\n      primer error: {self.primer_error}" if self.primer_error else "")


def ejecutar_carga(
    url_base: str,
    pacientes: Sequence[Tuple[int, int]],
    usuarios: int,
    iteraciones: int,
    verificar=True,
    workers: int = 1,
) -> ResultadoCarga:
    """``usuarios`` hilos, cada uno abre ``iteraciones`` pacientes (3 peticiones por paciente)."""
    import httpx

    latencias: List[float] = []
    errores: List[str] = []
    cerrojo = threading.Lock()

    def medico(numero: int) -> None:
        with httpx.Client(verify=verificar, timeout=30) as cliente:
            for k in range(iteraciones):
                paciente_id, oncologo_id = pacientes[(numero * 7 + k) % len(pacientes)]
                for plantilla in RUTAS_POR_PACIENTE:
                    inicio = time.perf_counter()
                    error = None
                    try:
                        r = cliente.get(url_base + plantilla.format(id=paciente_id), params={"oncologo_id": oncologo_id})
                        if r.status_code >= 500:
                            error = f"HTTP {r.status_code}"
                    except httpx.HTTPError as exc:
                        error = f"{type(exc).__name__}: {exc}"[:150]
                    with cerrojo:
                        latencias.append((time.perf_counter() - inicio) * 1000)
                        if error:
                            errores.append(error)

    inicio = time.perf_counter()
    hilos = [threading.Thread(target=medico, args=(i,)) for i in range(usuarios)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    duracion = time.perf_counter() - inicio
    return ResultadoCarga(
        usuarios=usuarios,
        peticiones=len(latencias),
        errores=len(errores),
        p50_ms=round(percentil(latencias, 50), 1),
        p95_ms=round(percentil(latencias, PERCENTIL_OBJETIVO), 1),
        max_ms=round(max(latencias, default=0.0), 1),
        peticiones_por_segundo=round(len(latencias) / duracion, 1) if duracion else 0.0,
        workers=workers,
        primer_error=errores[0] if errores else None,
    )


def pacientes_de_muestra(ruta_pacientes: Path, cuantos: int = 200, oncologo: Optional[int] = None) -> List[Tuple[int, int]]:
    with contextlib.closing(sqlite3.connect(f"file:{Path(ruta_pacientes).as_posix()}?mode=ro", uri=True)) as conn:
        if oncologo is None:
            filas = conn.execute("SELECT id, oncologo_id FROM pacientes ORDER BY id LIMIT ?", (cuantos,)).fetchall()
        else:
            filas = conn.execute(
                "SELECT id, oncologo_id FROM pacientes WHERE oncologo_id = ? ORDER BY id LIMIT ?", (oncologo, cuantos)
            ).fetchall()
    if not filas:
        raise SystemExit("No hay pacientes en la base para la prueba de carga.")
    return [(f[0], f[1]) for f in filas]


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.contextmanager
def servidor_local(carpeta: Path, workers: int = 1) -> Iterator[Tuple[str, str, Path]]:
    """Servidor TLS sobre una copia de las bases reales. Devuelve (url, certificado, base de pacientes)."""
    from seguridad.servidor_tls import generar_certificado_local

    origen_exp, origen_pac = RAIZ / "data" / "copiloto.db", RAIZ / "patients" / "db" / "pacientes.db"
    if not origen_exp.is_file() or not origen_pac.is_file():
        raise SystemExit("Falta la base real. Prepárela una vez con: python demo.py --solo pac")
    carpeta.mkdir(parents=True, exist_ok=True)
    copia_exp, copia_pac = carpeta / "copiloto.db", carpeta / "pacientes.db"
    for origen, destino in ((origen_exp, copia_exp), (origen_pac, copia_pac)):
        with contextlib.closing(sqlite3.connect(str(origen))) as fuente, contextlib.closing(sqlite3.connect(str(destino))) as copia:
            fuente.backup(copia)
    cert, clave = generar_certificado_local(carpeta / "certs")
    puerto = _puerto_libre()
    entorno = {
        **os.environ,
        "COPILOTO_EXPEDIENTE_DB": str(copia_exp),
        "COPILOTO_PACIENTES_DB": str(copia_pac),
        "COPILOTO_DETALLE_BAJO_DEMANDA": "0",
        "COPILOTO_SESIONES_DB": str(carpeta / "sesiones.db"),
        "PYTHONIOENCODING": "utf-8",
    }
    proceso = subprocess.Popen(
        [sys.executable, "-m", "seguridad.servidor_tls", "--app", "patients.api:app", "--port", str(puerto),
         "--workers", str(workers), "--cert", str(cert), "--key", str(clave)],
        cwd=str(RAIZ), env=entorno, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    url = f"https://127.0.0.1:{puerto}"
    try:
        _esperar_listo(url, str(cert), proceso)
        yield url, str(cert), copia_pac
    finally:
        proceso.terminate()
        try:
            proceso.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proceso.kill()


def _esperar_listo(url: str, cert: str, proceso: subprocess.Popen, espera_s: float = 60) -> None:
    import httpx

    from seguridad.tls import contexto_tls_cliente

    limite = time.monotonic() + espera_s
    while time.monotonic() < limite:
        if proceso.poll() is not None:
            raise SystemExit(f"El servidor de la prueba no arrancó: {proceso.stderr.read().decode('utf-8', 'replace')[-800:]}")
        try:
            if httpx.get(url + "/salud/listo", verify=contexto_tls_cliente(cert), timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    raise SystemExit("El servidor de la prueba no respondió a tiempo.")


def main(argv: Optional[Sequence[str]] = None) -> int:
    for flujo in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError):
            flujo.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="python -m operacion.carga", description="Prueba de carga (NFR-01 / NFR-05).")
    p.add_argument("--usuarios", type=int, nargs="+", default=[1, 10, 25], help="Médicos simultáneos (uno o varios).")
    p.add_argument("--iteraciones", type=int, default=10, help="Pacientes que abre cada médico.")
    p.add_argument("--workers", type=int, default=1, help="Procesos del servidor local (NFR-05).")
    p.add_argument("--url", help="Probar un servidor ya levantado en vez de uno local.")
    p.add_argument("--ca", help="Certificado en el que confiar (con --url).")
    p.add_argument("--oncologo", type=int, help="Con --url: oncólogo cuyos pacientes se abren.")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    from seguridad.tls import contexto_tls_cliente

    resultados: List[ResultadoCarga] = []
    with contextlib.ExitStack() as pila:
        if args.url:
            url, verificar = args.url.rstrip("/"), contexto_tls_cliente(args.ca) if args.ca else True
            from patients import db

            pacientes = pacientes_de_muestra(Path(os.environ.get("COPILOTO_PACIENTES_DB") or db.RUTA_DB), oncologo=args.oncologo)
        else:
            carpeta = Path(pila.enter_context(tempfile.TemporaryDirectory(prefix="copiloto_carga_", ignore_cleanup_errors=True)))
            print(f"  Levantando el servidor TLS de la prueba ({args.workers} proceso(s)) sobre una copia de la base real...", flush=True)
            url, cert, copia_pac = pila.enter_context(servidor_local(carpeta, args.workers))
            verificar = contexto_tls_cliente(cert)
            pacientes = pacientes_de_muestra(copia_pac)
        for usuarios in args.usuarios:
            resultado = ejecutar_carga(url, pacientes, usuarios, args.iteraciones, verificar, args.workers)
            resultados.append(resultado)
            if not args.json:
                print(resultado.a_texto(), flush=True)
    if args.json:
        print(json.dumps([r.a_dict() for r in resultados], ensure_ascii=False, indent=2))
    return 0 if all(r.cumple for r in resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
