"""SEC-01 — Autenticación segura y control de acceso por rol (parte 2: autorización).

Modelo de permisos por rol (oncólogo, enfermería, administrativo, auditor):
qué acciones clínicas sensibles puede ejecutar cada rol. El criterio de
aceptación de referencia de la historia (AC1) es el caso de prueba
canónico: un usuario con rol "enfermería" no puede ejecutar la
confirmación de tratamiento de TX-04.

Por diseño, una acción sin entrada en ``PERMISOS_POR_ROL`` se deniega a
todos los roles (fail-closed): es preferible que una acción nueva quede
sin permisos explícitos a que quede accesible por omisión.
"""

from __future__ import annotations

from enum import Enum

from seguridad.models import ResultadoAutorizacion, Rol, Usuario


class Accion(str, Enum):
    """Acciones clínicas sensibles sujetas a control de acceso por rol."""

    CONFIRMAR_TRATAMIENTO = "confirmar_tratamiento"  # TX-04
    CONFIRMAR_ESTADIFICACION = "confirmar_estadificacion"  # EST-02
    REGISTRAR_JUICIO_DIAGNOSTICO = "registrar_juicio_diagnostico"  # DX-03
    VER_EXPEDIENTE = "ver_expediente"
    EDITAR_EXPEDIENTE = "editar_expediente"
    EXPORTAR_EXPEDIENTE = "exportar_expediente"
    CONFIGURAR_GUIAS_INSTITUCIONALES = "configurar_guias_institucionales"  # CFG-01
    GESTIONAR_USUARIOS = "gestionar_usuarios"  # ADM-01
    REGISTRAR_CONSENTIMIENTO_IA = "registrar_consentimiento_ia"  # SEC-03
    CONFIGURAR_POLITICA_DATOS = "configurar_politica_datos"  # NFR-06 / NFR-04
    VER_METRICAS_USO = "ver_metricas_uso"  # ADM-02
    VER_AUDITORIA = "ver_auditoria"  # AUD-01 / AUD-02 desde la interfaz
    VER_ESTADO_SISTEMA = "ver_estado_sistema"  # NFR-01 / NFR-02 desde la interfaz


PERMISOS_POR_ROL: dict[Accion, frozenset[Rol]] = {
    Accion.CONFIRMAR_TRATAMIENTO: frozenset({Rol.ONCOLOGO}),
    Accion.CONFIRMAR_ESTADIFICACION: frozenset({Rol.ONCOLOGO}),
    Accion.REGISTRAR_JUICIO_DIAGNOSTICO: frozenset({Rol.ONCOLOGO}),
    Accion.VER_EXPEDIENTE: frozenset({Rol.ONCOLOGO, Rol.ENFERMERIA, Rol.AUDITOR}),
    Accion.EDITAR_EXPEDIENTE: frozenset({Rol.ONCOLOGO, Rol.ENFERMERIA}),
    Accion.EXPORTAR_EXPEDIENTE: frozenset({Rol.ONCOLOGO, Rol.ADMINISTRATIVO}),
    Accion.CONFIGURAR_GUIAS_INSTITUCIONALES: frozenset({Rol.ADMINISTRADOR_CLINICO}),
    Accion.GESTIONAR_USUARIOS: frozenset({Rol.ADMINISTRADOR}),
    # Lo recibe quien atiende al paciente o lo admite; el auditor solo lo consulta.
    Accion.REGISTRAR_CONSENTIMIENTO_IA: frozenset({Rol.ONCOLOGO, Rol.ENFERMERIA, Rol.ADMINISTRATIVO}),
    Accion.CONFIGURAR_POLITICA_DATOS: frozenset({Rol.ADMINISTRADOR_CLINICO}),
    # Métricas agregadas de la institución (nunca por médico): las ve la dirección médica.
    Accion.VER_METRICAS_USO: frozenset({Rol.DIRECTOR_MEDICO}),
    Accion.VER_AUDITORIA: frozenset({Rol.AUDITOR}),
    Accion.VER_ESTADO_SISTEMA: frozenset({Rol.ADMINISTRADOR}),
}


def permisos_del_rol(rol: Rol) -> tuple[Accion, ...]:
    """Acciones que un rol puede ejecutar, en el orden de ``Accion`` (para
    mostrarlas al administrador, ADM-01). Es la misma tabla que usa
    ``verificar_permiso``: no hay una segunda fuente de verdad."""
    return tuple(a for a in Accion if rol in PERMISOS_POR_ROL.get(a, frozenset()))


def verificar_permiso(usuario: Usuario, accion: Accion) -> ResultadoAutorizacion:
    """Decide si ``usuario`` puede ejecutar ``accion`` (criterio de aceptación de SEC-01)."""
    if not usuario.activo:
        return ResultadoAutorizacion(permitido=False, motivo_rechazo="El usuario está inactivo.")

    roles_permitidos = PERMISOS_POR_ROL.get(accion, frozenset())
    if usuario.rol in roles_permitidos:
        return ResultadoAutorizacion(permitido=True)

    permitidos = ", ".join(sorted(r.value for r in roles_permitidos)) or "ningún rol"
    return ResultadoAutorizacion(
        permitido=False,
        motivo_rechazo=(
            f"El rol '{usuario.rol.value}' no tiene permiso para '{accion.value}'; "
            f"esta acción está restringida a: {permitidos}."
        ),
    )
