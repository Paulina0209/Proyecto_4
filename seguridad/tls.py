"""SEC-02 — Cifrado en tránsito.

Criterio de aceptación:

    Dado cualquier intercambio cliente-servidor
    Cuando se transmite información clínica
    Entonces viaja exclusivamente sobre una versión vigente de TLS
    (sin caer a conexiones sin cifrar)

Tres piezas, una por cada lado de la conexión:

    - ``contexto_tls_servidor`` / ``contexto_tls_cliente``: contextos SSL con
      TLS 1.2 como mínimo (1.0 y 1.1 están deprecados, RFC 8996) y, del lado
      cliente, verificación obligatoria de certificado y nombre de host.
    - ``SoloHTTPSMiddleware``: la API rechaza cualquier petición que no llegue
      por HTTPS (403, sin redirigir: una redirección significa que la primera
      petición ya viajó en claro) y obliga al navegador a usar HTTPS en
      adelante con ``Strict-Transport-Security``.
    - ``exigir_url_segura``: las integraciones salientes (cBioPortal, PACS,
      visor) solo aceptan ``https://``. La única excepción es la interfaz de
      loopback (``localhost``, ``127.0.0.1``, ``::1``): ese tráfico no sale de
      la máquina, y es como corre el Orthanc local de la demo de HC-03.

Para levantar la API con TLS: ``python -m seguridad.servidor_tls`` (ver
docs/seguridad_cifrado.md).
"""

from __future__ import annotations

import ipaddress
import json
import ssl
from typing import Iterable, Optional
from urllib.parse import urlparse

#: Versión mínima aceptada en las dos puntas de la conexión.
VERSION_TLS_MINIMA = ssl.TLSVersion.TLSv1_2

#: Suites para TLS 1.2: solo intercambio de claves con secreto perfecto hacia
#: adelante (ECDHE) y cifrado autenticado (AES-GCM, ChaCha20). TLS 1.3 define
#: sus propias suites y todas cumplen esto.
CIFRADOS_TLS12 = "ECDHE+AESGCM:ECDHE+CHACHA20:!aNULL:!eNULL:!MD5:!DSS"

#: Un año, con subdominios: lo mínimo que aceptan las listas de precarga HSTS.
CABECERA_HSTS = "max-age=31536000; includeSubDomains"

HOSTS_LOOPBACK = frozenset({"localhost"})


class ConexionInseguraError(ValueError):
    """Se intentó configurar una conexión que no va cifrada con TLS."""


def contexto_tls_servidor(archivo_certificado: str, archivo_clave: str, password: Optional[str] = None) -> ssl.SSLContext:
    """Contexto para el servidor: TLS >= 1.2, suites AEAD y sin renegociación insegura."""
    contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    _endurecer(contexto)
    contexto.load_cert_chain(archivo_certificado, archivo_clave, password=password)
    return contexto


def contexto_tls_cliente(archivo_ca: Optional[str] = None) -> ssl.SSLContext:
    """Contexto para clientes: TLS >= 1.2, verifica certificado y nombre de host."""
    contexto = ssl.create_default_context(cafile=archivo_ca)
    _endurecer(contexto)
    contexto.check_hostname = True
    contexto.verify_mode = ssl.CERT_REQUIRED
    return contexto


def _endurecer(contexto: ssl.SSLContext) -> None:
    contexto.minimum_version = VERSION_TLS_MINIMA
    contexto.set_ciphers(CIFRADOS_TLS12)
    contexto.options |= ssl.OP_NO_COMPRESSION  # CRIME
    contexto.options |= getattr(ssl, "OP_NO_RENEGOTIATION", 0)


def es_loopback(host: Optional[str]) -> bool:
    if not host:
        return False
    if host.casefold() in HOSTS_LOOPBACK:
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def exigir_url_segura(url: str, *, que: str = "La integración", permitir_loopback: bool = True) -> str:
    """Devuelve ``url`` si va por HTTPS (o por loopback); si no, lanza ``ConexionInseguraError``.

    No hay respaldo a HTTP: una URL ``http://`` hacia otra máquina se rechaza
    al configurarla, antes de enviar ningún dato.
    """
    analizada = urlparse((url or "").strip())
    if not analizada.netloc:
        raise ConexionInseguraError(f"{que}: '{url}' no es una URL completa.")
    if analizada.scheme == "https":
        return url
    if analizada.scheme == "http" and permitir_loopback and es_loopback(analizada.hostname):
        return url
    raise ConexionInseguraError(
        f"{que} debe usar HTTPS (TLS): '{url}' enviaría información clínica sin cifrar. "
        "Solo se acepta http:// hacia la propia máquina (localhost)."
    )


class SoloHTTPSMiddleware:
    """Middleware ASGI: solo deja pasar peticiones HTTPS y agrega HSTS.

    El esquema lo decide el servidor ASGI: con TLS directo (``servidor_tls``)
    es ``https``; detrás de un proxy que termina TLS, uvicorn lo toma de
    ``X-Forwarded-Proto`` solo si el proxy está en ``--forwarded-allow-ips``.
    Así un cliente no puede saltarse el control mandando esa cabecera.

    ``rutas_exentas``: rutas que se sirven también en claro (p. ej. una
    sonda de salud del balanceador que no lleva datos).
    """

    def __init__(self, app, rutas_exentas: Iterable[str] = ()):
        self.app = app
        self.rutas_exentas = frozenset(rutas_exentas)

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        seguro = scope.get("scheme") in ("https", "wss")
        if not seguro and scope.get("path") not in self.rutas_exentas:
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
                return
            await _responder_403(send)
            return

        if not seguro:
            await self.app(scope, receive, send)
            return

        async def enviar_con_hsts(mensaje):
            if mensaje["type"] == "http.response.start":
                cabeceras = list(mensaje.get("headers") or [])
                cabeceras.append((b"strict-transport-security", CABECERA_HSTS.encode("ascii")))
                mensaje = {**mensaje, "headers": cabeceras}
            await send(mensaje)

        await self.app(scope, receive, enviar_con_hsts)


async def _responder_403(send) -> None:
    cuerpo = json.dumps(
        {"detail": "Conexión rechazada: la API solo acepta HTTPS (TLS). No se procesó la petición."},
        ensure_ascii=False,
    ).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 403,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(cuerpo)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": cuerpo})
