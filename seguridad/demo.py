"""Demo de SEC-01 — Autenticación segura y control de acceso por rol.

Ejecutar: python -m seguridad.demo
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from seguridad.autenticacion import (
    DURACION_BLOQUEO_MINUTOS,
    UMBRAL_INTENTOS_FALLIDOS,
    autenticar,
    crear_conexion,
    registrar_usuario,
)
from seguridad.autorizacion import Accion, verificar_permiso
from seguridad.models import Rol


def main() -> None:
    conn = crear_conexion(":memory:")
    registrar_usuario(conn, "dra.gomez", "Cl1nic@2026", Rol.ONCOLOGO)
    registrar_usuario(conn, "enf.paez", "Cl1nic@2026", Rol.ENFERMERIA)

    print("=" * 78)
    print("SEC-01 — AUTENTICACIÓN Y CONTROL DE ACCESO POR ROL")
    print("=" * 78)

    print("\n--- Login correcto ---")
    resultado = autenticar(conn, "dra.gomez", "Cl1nic@2026")
    print(f"Éxito: {resultado.exito} | usuario: {resultado.usuario.nombre_usuario} ({resultado.usuario.rol.value})")

    print("\n--- AC1: un usuario con rol 'enfermería' intenta confirmar un tratamiento (TX-04) ---")
    login_enfermeria = autenticar(conn, "enf.paez", "Cl1nic@2026")
    autorizacion = verificar_permiso(login_enfermeria.usuario, Accion.CONFIRMAR_TRATAMIENTO)
    print(f"Permitido: {autorizacion.permitido}")
    print(f"Motivo: {autorizacion.motivo_rechazo}")

    print("\n--- Ese mismo usuario SÍ puede ver el expediente ---")
    autorizacion_ver = verificar_permiso(login_enfermeria.usuario, Accion.VER_EXPEDIENTE)
    print(f"Permitido ver expediente: {autorizacion_ver.permitido}")

    print(f"\n--- AC2: {UMBRAL_INTENTOS_FALLIDOS} intentos fallidos consecutivos bloquean la cuenta ---")
    ahora = datetime.now(timezone.utc)
    resultado = None
    for intento in range(1, UMBRAL_INTENTOS_FALLIDOS + 1):
        resultado = autenticar(conn, "dra.gomez", "clave-incorrecta", ahora=ahora)
        print(f"Intento {intento}: éxito={resultado.exito} bloqueada={resultado.cuenta_bloqueada}")
    print(f"Notificación al usuario: {resultado.motivo_rechazo}")

    print("\n--- Un intento más durante el bloqueo, incluso con la contraseña correcta ---")
    resultado = autenticar(conn, "dra.gomez", "Cl1nic@2026", ahora=ahora + timedelta(minutes=1))
    print(f"Éxito: {resultado.exito} | bloqueada: {resultado.cuenta_bloqueada}")
    print(f"Motivo: {resultado.motivo_rechazo}")

    print("\n--- Tras expirar el bloqueo, la contraseña correcta vuelve a funcionar ---")
    resultado = autenticar(
        conn, "dra.gomez", "Cl1nic@2026", ahora=ahora + timedelta(minutes=DURACION_BLOQUEO_MINUTOS + 1)
    )
    print(f"Éxito: {resultado.exito}")


if __name__ == "__main__":
    main()
