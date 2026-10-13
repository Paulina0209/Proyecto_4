"""SEC-02 — Cifrado en reposo.

AES-256-GCM (cifrado autenticado): además de ocultar el contenido, detecta
cualquier alteración del archivo. Cada cifrado usa un nonce aleatorio nuevo y
va ligado a un *contexto* (p. ej. ``documento:paciente_7``) como dato
autenticado: un archivo cifrado para un paciente no se puede descifrar
haciéndolo pasar por el de otro.

Formato de un archivo cifrado::

    b"CPC1" | id de la clave (8 bytes) | nonce (12 bytes) | texto cifrado + etiqueta (16 bytes)

El id de la clave es una huella (SHA-256 truncado), no la clave: sirve para
avisar con claridad si se intenta descifrar con una clave distinta.

La clave (32 bytes en base64 url-safe) se toma, en este orden, de:

    1. ``COPILOTO_CLAVE_CIFRADO``: en producción, inyectada por el gestor de
       secretos de la institución;
    2. el archivo de ``COPILOTO_ARCHIVO_CLAVE``;
    3. ``~/.copiloto_clinico/clave_cifrado``, que se crea la primera vez
       (desarrollo). Queda fuera del repositorio y de la carpeta de datos, para
       que una copia de ``data/`` no lleve consigo la clave.

Si la clave se pierde, lo cifrado con ella no se puede recuperar.

    python -m seguridad.cifrado generar-clave
    python -m seguridad.cifrado respaldar data/copiloto.db respaldo.db.cpc
    python -m seguridad.cifrado restaurar respaldo.db.cpc copiloto.db
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import secrets
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIA = b"CPC1"
_LARGO_ID = 8
_LARGO_NONCE = 12
_CABECERA = len(MAGIA) + _LARGO_ID + _LARGO_NONCE

ENV_CLAVE = "COPILOTO_CLAVE_CIFRADO"
ENV_ARCHIVO_CLAVE = "COPILOTO_ARCHIVO_CLAVE"
ARCHIVO_CLAVE_POR_DEFECTO = Path.home() / ".copiloto_clinico" / "clave_cifrado"

CONTEXTO_RESPALDO = "respaldo_base_datos"


class ErrorCifrado(Exception):
    """No se pudo cifrar o descifrar (clave inválida, distinta o dato alterado)."""


def generar_clave() -> str:
    """Clave nueva de 256 bits, en base64 url-safe (el formato de ``COPILOTO_CLAVE_CIFRADO``)."""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")


@dataclass(frozen=True)
class Cifrador:
    """Cifra y descifra bytes con una clave AES-256."""

    clave: bytes
    #: De dónde salió la clave (para el informe de cumplimiento; nunca la clave misma).
    origen: str = "explícita"

    def __post_init__(self) -> None:
        if len(self.clave) != 32:
            raise ErrorCifrado("La clave de cifrado debe tener 32 bytes (AES-256).")

    @classmethod
    def desde_texto(cls, texto: str, origen: str = "explícita") -> "Cifrador":
        try:
            clave = base64.urlsafe_b64decode(texto.strip().encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise ErrorCifrado("La clave de cifrado no es base64 válido.") from exc
        return cls(clave, origen)

    @property
    def id_clave(self) -> bytes:
        return hashlib.sha256(b"copiloto-id-clave" + self.clave).digest()[:_LARGO_ID]

    def cifrar(self, datos: bytes, contexto: str) -> bytes:
        nonce = secrets.token_bytes(_LARGO_NONCE)
        cabecera = MAGIA + self.id_clave + nonce
        return cabecera + AESGCM(self.clave).encrypt(nonce, datos, cabecera[:-_LARGO_NONCE] + contexto.encode("utf-8"))

    def descifrar(self, blob: bytes, contexto: str) -> bytes:
        if not esta_cifrado(blob):
            raise ErrorCifrado("El dato no tiene el formato cifrado del copiloto.")
        id_clave = blob[len(MAGIA) : len(MAGIA) + _LARGO_ID]
        if id_clave != self.id_clave:
            raise ErrorCifrado("El dato se cifró con otra clave: no se puede descifrar con la configurada.")
        nonce = blob[len(MAGIA) + _LARGO_ID : _CABECERA]
        try:
            return AESGCM(self.clave).decrypt(
                nonce, blob[_CABECERA:], MAGIA + id_clave + contexto.encode("utf-8")
            )
        except InvalidTag as exc:
            raise ErrorCifrado("El dato cifrado fue alterado o no corresponde a este contexto.") from exc


def esta_cifrado(blob: bytes) -> bool:
    return blob[: len(MAGIA)] == MAGIA and len(blob) >= _CABECERA + 16


def cifrador_configurado(crear_si_falta: bool = True) -> Cifrador:
    """El cifrador con la clave de la institución (ver el orden en el docstring del módulo)."""
    texto = os.environ.get(ENV_CLAVE)
    if texto:
        return Cifrador.desde_texto(texto, origen=f"variable {ENV_CLAVE}")

    ruta = Path(os.environ.get(ENV_ARCHIVO_CLAVE) or ARCHIVO_CLAVE_POR_DEFECTO)
    if ruta.is_file():
        return Cifrador.desde_texto(ruta.read_text(encoding="ascii"), origen=f"archivo {ruta}")
    if not crear_si_falta:
        raise ErrorCifrado(f"No hay clave de cifrado: defina {ENV_CLAVE} o cree {ruta}.")

    ruta.parent.mkdir(parents=True, exist_ok=True)
    clave = generar_clave()
    # O_EXCL: si otro proceso la creó al mismo tiempo, se usa la suya.
    try:
        descriptor = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return Cifrador.desde_texto(ruta.read_text(encoding="ascii"), origen=f"archivo {ruta}")
    with os.fdopen(descriptor, "w", encoding="ascii") as archivo:
        archivo.write(clave)
    return Cifrador.desde_texto(clave, origen=f"archivo {ruta} (creado)")


# ---------------------------------------------------------------------------
# Archivos
# ---------------------------------------------------------------------------


def escribir_cifrado(ruta: Path, datos: bytes, contexto: str, cifrador: Optional[Cifrador] = None) -> None:
    cifrador = cifrador or cifrador_configurado()
    Path(ruta).write_bytes(cifrador.cifrar(datos, contexto))


def leer_descifrado(ruta: Path, contexto: str, cifrador: Optional[Cifrador] = None) -> bytes:
    """Lee un archivo cifrado. Un archivo en claro (anterior a SEC-02) se
    devuelve tal cual, para no perder lo que ya estaba guardado; el informe de
    cumplimiento lo señala para que se migre."""
    blob = Path(ruta).read_bytes()
    if not esta_cifrado(blob):
        return blob
    return (cifrador or cifrador_configurado()).descifrar(blob, contexto)


def respaldar_base_cifrada(origen: Path, destino: Path, cifrador: Optional[Cifrador] = None) -> Path:
    """Copia consistente de una base SQLite (API de backup, aunque esté en uso), cifrada."""
    cifrador = cifrador or cifrador_configurado()
    with tempfile.TemporaryDirectory() as carpeta:
        copia = Path(carpeta) / "copia.db"
        with sqlite3.connect(str(origen)) as fuente, sqlite3.connect(str(copia)) as destino_tmp:
            fuente.backup(destino_tmp)
        fuente.close()
        destino_tmp.close()
        escribir_cifrado(Path(destino), copia.read_bytes(), CONTEXTO_RESPALDO, cifrador)
    return Path(destino)


def restaurar_respaldo(origen: Path, destino: Path, cifrador: Optional[Cifrador] = None) -> Path:
    if Path(destino).exists():
        raise FileExistsError(f"{destino} ya existe: no se sobrescribe una base al restaurar.")
    Path(destino).write_bytes((cifrador or cifrador_configurado()).descifrar(Path(origen).read_bytes(), CONTEXTO_RESPALDO))
    return Path(destino)


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="python -m seguridad.cifrado", description="Cifrado en reposo (SEC-02).")
    sub = p.add_subparsers(dest="comando", required=True)
    sub.add_parser("generar-clave", help="Imprime una clave nueva para COPILOTO_CLAVE_CIFRADO.")
    r = sub.add_parser("respaldar", help="Respaldo cifrado de una base SQLite.")
    r.add_argument("origen", type=Path)
    r.add_argument("destino", type=Path)
    d = sub.add_parser("restaurar", help="Descifra un respaldo a una base nueva.")
    d.add_argument("origen", type=Path)
    d.add_argument("destino", type=Path)
    args = p.parse_args(argv)

    if args.comando == "generar-clave":
        print(generar_clave())
    elif args.comando == "respaldar":
        print(f"Respaldo cifrado: {respaldar_base_cifrada(args.origen, args.destino)}")
    else:
        print(f"Base restaurada: {restaurar_respaldo(args.origen, args.destino)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
