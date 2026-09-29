"""SEC-01 integrado en TX-04: solo un usuario con rol oncólogo puede
registrar la decisión final de tratamiento (criterio de aceptación
explícito de SEC-01, referido literalmente a esta función)."""

import pytest

from clinical_decision.registro import crear_conexion, registrar_decision_tratamiento
from seguridad.autenticacion import crear_conexion as crear_conexion_usuarios
from seguridad.autenticacion import registrar_usuario
from seguridad.models import Rol


@pytest.fixture
def conn_decisiones():
    conn = crear_conexion(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def conn_usuarios():
    conn = crear_conexion_usuarios(":memory:")
    yield conn
    conn.close()


def _rechazar(conn_decisiones, usuario=None):
    return registrar_decision_tratamiento(
        conn_decisiones,
        paciente_id=1,
        oncologo_id=1,
        tipo_decision="reject",
        recomendacion_ia_snapshot={},
        regimenes_candidatos_ids=[],
        regimen_sugerido_id=None,
        motivo_rechazo="Comorbilidad no evaluada por el motor de reglas.",
        usuario=usuario,
    )


def test_sin_usuario_no_se_aplica_ningun_control_de_acceso(conn_decisiones):
    """Compatibilidad hacia atrás: llamadas existentes que no pasan `usuario`
    (p. ej. la tool de tx_clinica) siguen funcionando igual que antes."""
    resultado = _rechazar(conn_decisiones)
    assert resultado.exito is True


def test_un_usuario_con_rol_enfermeria_no_puede_registrar_la_decision(conn_decisiones, conn_usuarios):
    enfermero = registrar_usuario(conn_usuarios, "enf.paez", "clave123", Rol.ENFERMERIA)

    resultado = _rechazar(conn_decisiones, usuario=enfermero)

    assert resultado.exito is False
    assert "enfermeria" in resultado.motivo_rechazo


def test_un_usuario_con_rol_oncologo_si_puede_registrar_la_decision(conn_decisiones, conn_usuarios):
    oncologa = registrar_usuario(conn_usuarios, "dra.gomez", "clave123", Rol.ONCOLOGO)

    resultado = _rechazar(conn_decisiones, usuario=oncologa)

    assert resultado.exito is True
