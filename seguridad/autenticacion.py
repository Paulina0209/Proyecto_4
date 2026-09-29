"""SEC-01 — Autenticación segura y control de acceso por rol (parte 1: login).

Como administrador del sistema, quiero controlar el acceso mediante
autenticación segura y roles (oncólogo, enfermería, administrativo), para
que cada usuario vea solo lo que le corresponde.

Diseño:
  - La contraseña nunca se guarda en texto plano: se guarda un hash
    PBKDF2-HMAC-SHA256 con sal aleatoria por usuario (librería estándar,
    sin dependencias nuevas).
  - Tras ``UMBRAL_INTENTOS_FALLIDOS`` intentos fallidos consecutivos, la
    cuenta se bloquea temporalmente por ``DURACION_BLOQUEO_MINUTOS`` (AC2).
    Un intento más durante el bloqueo se rechaza sin importar si la
    contraseña es correcta, y no reinicia el contador.
  - Un login exitoso reinicia ``intentos_fallidos`` a 0.
  - "Notificar al usuario" (AC2) se resuelve, en este prototipo sin canal
    de mensajería propio, devolviendo el mensaje explícito en
    ``ResultadoAutenticacion.motivo_rechazo`` -- es lo que la capa que
    llame (API, CLI, demo) debe mostrarle a quien intenta iniciar sesión.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from seguridad.models import ResultadoAutenticacion, Rol, Usuario

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema_usuarios.sql"

UMBRAL_INTENTOS_FALLIDOS = 5
DURACION_BLOQUEO_MINUTOS = 15
_ITERACIONES_PBKDF2 = 200_000


def crear_conexion(ruta: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(ruta)
    conn.row_factory = sqlite3.Row
    inicializar_esquema(conn)
    return conn


def inicializar_esquema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def _hash_contrasena(contrasena: str, sal: bytes) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", contrasena.encode("utf-8"), sal, _ITERACIONES_PBKDF2
    ).hex()


def registrar_usuario(
    conn: sqlite3.Connection, nombre_usuario: str, contrasena: str, rol: Rol
) -> Usuario:
    """Alta de un usuario institucional (ligado a ADM-01: gestión de usuarios y roles).

    No es parte del flujo del oncólogo en consulta -- la ejecuta un
    administrador del sistema.
    """
    if not nombre_usuario or not nombre_usuario.strip():
        raise ValueError("El nombre de usuario no puede estar vacío.")
    if not contrasena:
        raise ValueError("La contraseña no puede estar vacía.")

    sal = os.urandom(16)
    cursor = conn.execute(
        """
        INSERT INTO usuarios
            (nombre_usuario, rol, activo, hash_contrasena, sal, intentos_fallidos, bloqueado_hasta)
        VALUES (?, ?, 1, ?, ?, 0, NULL)
        """,
        (nombre_usuario.strip(), rol.value, _hash_contrasena(contrasena, sal), sal.hex()),
    )
    conn.commit()
    fila = conn.execute("SELECT * FROM usuarios WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _fila_a_usuario(fila)


def autenticar(
    conn: sqlite3.Connection,
    nombre_usuario: str,
    contrasena: str,
    ahora: Optional[datetime] = None,
) -> ResultadoAutenticacion:
    """Verifica credenciales y aplica el bloqueo temporal por intentos fallidos (AC2).

    El mensaje de rechazo cuando el usuario no existe o la contraseña es
    incorrecta es deliberadamente genérico ("usuario o contraseña
    incorrectos"), para no revelar si un nombre de usuario existe.
    """
    ahora = ahora or datetime.now(timezone.utc)
    fila = conn.execute(
        "SELECT * FROM usuarios WHERE nombre_usuario = ?", (nombre_usuario,)
    ).fetchone()

    if fila is None:
        return ResultadoAutenticacion(exito=False, motivo_rechazo="Usuario o contraseña incorrectos.")

    bloqueado_hasta = fila["bloqueado_hasta"]
    if bloqueado_hasta is not None and datetime.fromisoformat(bloqueado_hasta) > ahora:
        return ResultadoAutenticacion(
            exito=False,
            cuenta_bloqueada=True,
            bloqueado_hasta=bloqueado_hasta,
            motivo_rechazo=(
                f"Cuenta bloqueada temporalmente hasta {bloqueado_hasta} por múltiples "
                "intentos fallidos. Intente de nuevo más tarde."
            ),
        )

    if not fila["activo"]:
        return ResultadoAutenticacion(exito=False, motivo_rechazo="Usuario inactivo.")

    sal = bytes.fromhex(fila["sal"])
    hash_calculado = _hash_contrasena(contrasena, sal)
    if not hmac.compare_digest(hash_calculado, fila["hash_contrasena"]):
        intentos = fila["intentos_fallidos"] + 1
        nuevo_bloqueo: Optional[str] = None
        if intentos >= UMBRAL_INTENTOS_FALLIDOS:
            nuevo_bloqueo = (ahora + timedelta(minutes=DURACION_BLOQUEO_MINUTOS)).isoformat()
        conn.execute(
            "UPDATE usuarios SET intentos_fallidos = ?, bloqueado_hasta = ? WHERE id = ?",
            (intentos, nuevo_bloqueo, fila["id"]),
        )
        conn.commit()
        if nuevo_bloqueo is not None:
            return ResultadoAutenticacion(
                exito=False,
                cuenta_bloqueada=True,
                bloqueado_hasta=nuevo_bloqueo,
                motivo_rechazo=(
                    f"Cuenta bloqueada temporalmente tras {UMBRAL_INTENTOS_FALLIDOS} intentos "
                    f"fallidos. Notifique al usuario: cuenta bloqueada hasta {nuevo_bloqueo}."
                ),
            )
        return ResultadoAutenticacion(exito=False, motivo_rechazo="Usuario o contraseña incorrectos.")

    conn.execute(
        "UPDATE usuarios SET intentos_fallidos = 0, bloqueado_hasta = NULL WHERE id = ?",
        (fila["id"],),
    )
    conn.commit()
    return ResultadoAutenticacion(exito=True, usuario=_fila_a_usuario(fila))


def _fila_a_usuario(fila: sqlite3.Row) -> Usuario:
    return Usuario(
        id=fila["id"],
        nombre_usuario=fila["nombre_usuario"],
        rol=Rol(fila["rol"]),
        activo=bool(fila["activo"]),
    )
