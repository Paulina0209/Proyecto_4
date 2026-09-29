"""SEC-01 — Control de acceso por rol (parte 2: autorización)."""

from seguridad.autorizacion import Accion, verificar_permiso
from seguridad.models import Rol, Usuario

ONCOLOGA = Usuario(id=1, nombre_usuario="dra.gomez", rol=Rol.ONCOLOGO, activo=True)
ENFERMERO = Usuario(id=2, nombre_usuario="enf.paez", rol=Rol.ENFERMERIA, activo=True)
ADMINISTRATIVA = Usuario(id=3, nombre_usuario="adm.rios", rol=Rol.ADMINISTRATIVO, activo=True)
ONCOLOGA_INACTIVA = Usuario(id=4, nombre_usuario="dr.baja", rol=Rol.ONCOLOGO, activo=False)


def test_ac1_enfermeria_no_puede_confirmar_un_tratamiento_tx04():
    resultado = verificar_permiso(ENFERMERO, Accion.CONFIRMAR_TRATAMIENTO)
    assert resultado.permitido is False
    assert "enfermeria" in resultado.motivo_rechazo


def test_oncologo_si_puede_confirmar_un_tratamiento_tx04():
    resultado = verificar_permiso(ONCOLOGA, Accion.CONFIRMAR_TRATAMIENTO)
    assert resultado.permitido is True
    assert resultado.motivo_rechazo is None


def test_enfermeria_si_puede_ver_el_expediente():
    resultado = verificar_permiso(ENFERMERO, Accion.VER_EXPEDIENTE)
    assert resultado.permitido is True


def test_administrativo_no_puede_confirmar_estadificacion():
    resultado = verificar_permiso(ADMINISTRATIVA, Accion.CONFIRMAR_ESTADIFICACION)
    assert resultado.permitido is False


def test_usuario_inactivo_se_rechaza_sin_importar_el_rol():
    resultado = verificar_permiso(ONCOLOGA_INACTIVA, Accion.CONFIRMAR_TRATAMIENTO)
    assert resultado.permitido is False
    assert "inactivo" in resultado.motivo_rechazo
