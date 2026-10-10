"""Demo de ADM-01 (en memoria, sin tocar ninguna base real).

    python -m administracion.demo
"""
from __future__ import annotations

from administracion import usuarios as adm
from seguridad.autenticacion import autenticar
from seguridad.autorizacion import Accion, verificar_permiso


def main() -> None:
    conn = adm.crear_conexion(":memory:")
    admin = adm.crear_primer_administrador(conn, "admin.sistema", "Adm1n-Inicial", "Administrador del Sistema")
    print(f"Primer administrador: {admin.nombre_usuario}")

    print("\n== AC1: el administrador gestiona usuarios ==")
    enf = adm.crear_usuario(conn, admin, "enf.paez", "Cl1nic@2026", "enfermeria", "Luis Páez", "enf.paez@hospital.org")
    sesion = autenticar(conn, "enf.paez", "Cl1nic@2026").usuario
    print(f"Creado {enf.nombre_usuario} ({enf.rol.value}). ¿Confirma tratamiento? "
          f"{verificar_permiso(sesion, Accion.CONFIRMAR_TRATAMIENTO).permitido}")
    adm.asignar_rol(conn, admin, enf.id, "oncologo", "Terminó la especialización")
    sesion = autenticar(conn, "enf.paez", "Cl1nic@2026").usuario
    print(f"Rol cambiado a oncólogo. ¿Confirma tratamiento? "
          f"{verificar_permiso(sesion, Accion.CONFIRMAR_TRATAMIENTO).permitido}")
    adm.desactivar_usuario(conn, admin, enf.id, "Dejó la institución")
    print(f"Desactivado. ¿Puede iniciar sesión? {autenticar(conn, 'enf.paez', 'Cl1nic@2026').exito}")

    print("\n== AC2: quien no es administrador no gestiona usuarios ==")
    adm.reactivar_usuario(conn, admin, enf.id)
    try:
        adm.asignar_rol(conn, sesion, enf.id, "administrador", "me ascendo")
    except adm.PermisoDenegadoError as exc:
        print(f"Denegado: {exc}")

    print("\n== AC3: nunca se queda sin administrador ==")
    try:
        adm.desactivar_usuario(conn, admin, admin.id, "x")
    except adm.OperacionNoPermitidaError as exc:
        print(f"Bloqueado: {exc}")

    print("\n== Auditoría (AUD-01) ==")
    for e in reversed(adm.eventos_de_administracion(conn, admin)):
        print(f"  #{e.id} actor={e.actor_id} {e.operacion:<22} {e.resultado:<8} objetivo={e.objetivo_id}")


if __name__ == "__main__":
    main()
