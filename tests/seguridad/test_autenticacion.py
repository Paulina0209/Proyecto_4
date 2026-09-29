"""SEC-01 — Autenticación segura (parte 1: login + bloqueo por intentos fallidos)."""

from datetime import datetime, timedelta, timezone

import pytest

from seguridad.autenticacion import (
    DURACION_BLOQUEO_MINUTOS,
    UMBRAL_INTENTOS_FALLIDOS,
    autenticar,
    crear_conexion,
    registrar_usuario,
)
from seguridad.models import Rol

AHORA = datetime(2026, 6, 1, tzinfo=timezone.utc)


@pytest.fixture
def conn():
    conn = crear_conexion(":memory:")
    registrar_usuario(conn, "dra.gomez", "Cl1nic@2026", Rol.ONCOLOGO)
    yield conn
    conn.close()


def test_login_correcto_devuelve_el_usuario_con_su_rol(conn):
    resultado = autenticar(conn, "dra.gomez", "Cl1nic@2026", ahora=AHORA)
    assert resultado.exito is True
    assert resultado.usuario.nombre_usuario == "dra.gomez"
    assert resultado.usuario.rol == Rol.ONCOLOGO


def test_contrasena_incorrecta_no_revela_si_el_usuario_existe(conn):
    resultado_usuario_inexistente = autenticar(conn, "no.existe", "cualquiera", ahora=AHORA)
    resultado_clave_incorrecta = autenticar(conn, "dra.gomez", "incorrecta", ahora=AHORA)
    assert resultado_usuario_inexistente.motivo_rechazo == resultado_clave_incorrecta.motivo_rechazo
    assert resultado_usuario_inexistente.exito is False
    assert resultado_clave_incorrecta.exito is False


def test_intentos_fallidos_por_debajo_del_umbral_no_bloquean_la_cuenta(conn):
    for _ in range(UMBRAL_INTENTOS_FALLIDOS - 1):
        resultado = autenticar(conn, "dra.gomez", "incorrecta", ahora=AHORA)
        assert resultado.cuenta_bloqueada is False

    # La contraseña correcta todavía funciona.
    assert autenticar(conn, "dra.gomez", "Cl1nic@2026", ahora=AHORA).exito is True


def test_al_superar_el_umbral_de_intentos_fallidos_la_cuenta_se_bloquea_y_notifica(conn):
    resultado = None
    for _ in range(UMBRAL_INTENTOS_FALLIDOS):
        resultado = autenticar(conn, "dra.gomez", "incorrecta", ahora=AHORA)

    assert resultado.exito is False
    assert resultado.cuenta_bloqueada is True
    assert resultado.motivo_rechazo  # el mensaje ES la notificación al usuario.


def test_durante_el_bloqueo_incluso_la_contrasena_correcta_es_rechazada(conn):
    for _ in range(UMBRAL_INTENTOS_FALLIDOS):
        autenticar(conn, "dra.gomez", "incorrecta", ahora=AHORA)

    resultado = autenticar(conn, "dra.gomez", "Cl1nic@2026", ahora=AHORA + timedelta(minutes=1))
    assert resultado.exito is False
    assert resultado.cuenta_bloqueada is True


def test_tras_expirar_el_bloqueo_la_contrasena_correcta_vuelve_a_funcionar(conn):
    for _ in range(UMBRAL_INTENTOS_FALLIDOS):
        autenticar(conn, "dra.gomez", "incorrecta", ahora=AHORA)

    despues_del_bloqueo = AHORA + timedelta(minutes=DURACION_BLOQUEO_MINUTOS, seconds=1)
    resultado = autenticar(conn, "dra.gomez", "Cl1nic@2026", ahora=despues_del_bloqueo)
    assert resultado.exito is True


def test_un_login_exitoso_reinicia_el_contador_de_intentos_fallidos(conn):
    for _ in range(UMBRAL_INTENTOS_FALLIDOS - 1):
        autenticar(conn, "dra.gomez", "incorrecta", ahora=AHORA)
    assert autenticar(conn, "dra.gomez", "Cl1nic@2026", ahora=AHORA).exito is True

    # Si no se hubiera reiniciado, este único intento fallido ya bloquearía.
    resultado = autenticar(conn, "dra.gomez", "incorrecta", ahora=AHORA)
    assert resultado.cuenta_bloqueada is False
