"""Arranque de ADM-01: crea el primer administrador.

    python -m administracion crear-admin

Pide el usuario, el nombre completo y la contraseña (sin mostrarla). Solo
funciona mientras no exista un administrador activo. Usa la misma base que la
API (``COPILOTO_USUARIOS_DB`` o ``data/usuarios.db``).
"""
from __future__ import annotations

import getpass
import sys

from administracion import api
from administracion import usuarios as adm


def main(argv: list[str]) -> int:
    if argv[1:] != ["crear-admin"]:
        print(__doc__)
        return 2
    ruta = api._ruta()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    conn = adm.crear_conexion(str(ruta))
    try:
        nombre_usuario = input("Usuario del administrador (p. ej. admin.sistema): ").strip()
        nombre_completo = input("Nombre completo: ").strip()
        correo = input("Correo (opcional): ").strip() or None
        contrasena = getpass.getpass(f"Contraseña (mínimo {adm.LARGO_MINIMO_CONTRASENA}, letras y números): ")
        if contrasena != getpass.getpass("Repite la contraseña: "):
            print("Las contraseñas no coinciden.")
            return 1
        creado = adm.crear_primer_administrador(conn, nombre_usuario, contrasena, nombre_completo, correo)
    except adm.ErrorValidacion as exc:
        for campo, mensaje in exc.errores:
            print(f"- {campo}: {mensaje}")
        return 1
    except adm.ErrorAdministracion as exc:
        print(exc)
        return 1
    finally:
        conn.close()
    print(f"Administrador '{creado.nombre_usuario}' creado en {ruta}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
