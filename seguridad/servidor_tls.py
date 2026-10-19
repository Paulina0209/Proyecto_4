"""SEC-02 — Levanta una API del copiloto solo sobre TLS.

    python -m seguridad.servidor_tls --cert cert.pem --key clave.pem
    python -m seguridad.servidor_tls --app administracion.api:app --port 8444 ...

El certificado y la clave también se pueden dar con ``COPILOTO_TLS_CERT`` y
``COPILOTO_TLS_KEY``. Sin ellos el servidor no arranca: no hay modo de
respaldo en HTTP. Detrás de un proxy que termina TLS (nginx, un balanceador),
se usa uvicorn con ``--proxy-headers --forwarded-allow-ips=<ip del proxy>``
y ``SoloHTTPSMiddleware`` sigue rechazando lo que no llegó por HTTPS.

Para probar en local, un certificado autofirmado:

    python -m seguridad.servidor_tls --generar-certificado-local certs/

NFR-05: ``--workers N`` levanta N procesos que comparten el puerto. Con más de
uno, las sesiones de la interfaz web pasan a ``data/sesiones.db`` (o a
``COPILOTO_SESIONES_DB``) para que cualquier proceso atienda a cualquier usuario.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Sequence

from seguridad.tls import contexto_tls_servidor

ENV_CERT = "COPILOTO_TLS_CERT"
ENV_KEY = "COPILOTO_TLS_KEY"
ENV_KEY_PASSWORD = "COPILOTO_TLS_KEY_PASSWORD"
SESIONES_POR_DEFECTO = Path(__file__).resolve().parent.parent / "data" / "sesiones.db"


class FabricaContextoTLS:
    """Fábrica del contexto TLS para uvicorn. Es una clase (y no una lambda) para que
    se pueda pasar a los procesos hijos con ``--workers`` (en Windows se serializa)."""

    def __init__(self, cert: str, key: str, password: Optional[str] = None):
        self.cert, self.key, self.password = cert, key, password

    def __call__(self, _config=None, _por_defecto=None):
        return contexto_tls_servidor(self.cert, self.key, self.password)


def construir_config(
    app: str, host: str, port: int, cert: str, key: str, password: Optional[str] = None, workers: int = 1
):
    """``uvicorn.Config`` con el contexto TLS endurecido de ``seguridad.tls``."""
    import uvicorn

    for ruta, que in ((cert, "certificado"), (key, "clave privada")):
        if not Path(ruta).is_file():
            raise FileNotFoundError(f"No existe el archivo de {que}: {ruta}")
    if workers > 1 and not isinstance(app, str):
        raise ValueError("Con varios procesos la aplicación se indica como texto, p. ej. 'patients.api:app'.")
    # Falla aquí, antes de abrir el puerto, si el par certificado/clave no sirve.
    contexto_tls_servidor(cert, key, password)
    return uvicorn.Config(
        app,
        host=host,
        port=port,
        workers=workers,
        ssl_certfile=cert,
        ssl_keyfile=key,
        ssl_keyfile_password=password,
        ssl_context_factory=FabricaContextoTLS(cert, key, password),
    )


def ejecutar(config) -> None:
    """Un proceso (``Server.run``) o varios (supervisor de uvicorn) según ``config.workers``."""
    import uvicorn

    if config.workers and config.workers > 1:
        from uvicorn.supervisors import Multiprocess

        sock = config.bind_socket()
        Multiprocess(config, sockets=[sock]).run()
    else:
        uvicorn.Server(config).run()


def generar_certificado_local(carpeta: Path, dias: int = 30) -> tuple[Path, Path]:
    """Certificado autofirmado para ``localhost`` (solo desarrollo y pruebas)."""
    import ipaddress

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    carpeta.mkdir(parents=True, exist_ok=True)
    clave = ec.generate_private_key(ec.SECP256R1())
    nombre = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    ahora = datetime.now(timezone.utc)
    certificado = (
        x509.CertificateBuilder()
        .subject_name(nombre)
        .issuer_name(nombre)
        .public_key(clave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(ahora - timedelta(minutes=5))
        .not_valid_after(ahora + timedelta(days=dias))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(clave, hashes.SHA256())
    )
    ruta_cert, ruta_clave = carpeta / "localhost.pem", carpeta / "localhost-clave.pem"
    ruta_cert.write_bytes(certificado.public_bytes(serialization.Encoding.PEM))
    ruta_clave.write_bytes(
        clave.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    return ruta_cert, ruta_clave


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="python -m seguridad.servidor_tls", description=__doc__.split("\n\n")[0])
    p.add_argument("--app", default="patients.api:app", help="Aplicación ASGI (por defecto patients.api:app).")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8443)
    p.add_argument("--cert", default=os.environ.get(ENV_CERT), help=f"Certificado PEM (o {ENV_CERT}).")
    p.add_argument("--key", default=os.environ.get(ENV_KEY), help=f"Clave privada PEM (o {ENV_KEY}).")
    p.add_argument("--workers", type=int, default=1, help="Procesos que atienden en paralelo (NFR-05).")
    p.add_argument("--generar-certificado-local", metavar="CARPETA", type=Path,
                   help="Crea un certificado autofirmado para localhost y termina.")
    args = p.parse_args(argv)

    if args.generar_certificado_local:
        cert, clave = generar_certificado_local(args.generar_certificado_local)
        print(f"Certificado: {cert}\nClave:       {clave}")
        print(f"Arranca con: python -m seguridad.servidor_tls --cert {cert} --key {clave}")
        return 0

    if not args.cert or not args.key:
        print(f"Falta el certificado TLS (--cert/--key o {ENV_CERT}/{ENV_KEY}). "
              "La API no se sirve sin cifrar.", file=sys.stderr)
        return 2

    if args.workers > 1:
        # Las sesiones de la interfaz se comparten entre procesos (los hijos heredan el entorno).
        os.environ.setdefault("COPILOTO_SESIONES_DB", str(SESIONES_POR_DEFECTO))
    config = construir_config(
        args.app, args.host, args.port, args.cert, args.key, os.environ.get(ENV_KEY_PASSWORD), args.workers
    )
    ejecutar(config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
