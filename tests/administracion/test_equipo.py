"""Equipo de atención: a qué oncólogos asiste cada persona de enfermería o admisiones."""
from datetime import datetime, timezone

import pytest

from administracion import equipo
from administracion import usuarios as adm
from seguridad.models import Rol, Usuario

AHORA = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
CLAVE = "Cl1nic@2026"


@pytest.fixture(autouse=True)
def _hash_rapido(monkeypatch):
    monkeypatch.setattr("seguridad.autenticacion._ITERACIONES_PBKDF2", 1_000)


@pytest.fixture
def conn():
    conexion = adm.crear_conexion(":memory:")
    yield conexion
    conexion.close()


@pytest.fixture
def gente(conn):
    a = adm.crear_primer_administrador(conn, "admin.sistema", "Adm1n-Inicial", "Administrador", ahora=AHORA)
    admin = Usuario(a.id, a.nombre_usuario, a.rol, a.activo)
    crear = lambda n, r, c: adm.crear_usuario(conn, admin, n, CLAVE, r, c, ahora=AHORA)  # noqa: E731
    return {"admin": admin, "gomez": crear("dra.gomez", Rol.ONCOLOGO, "Dra. Ana Gómez"), "vega": crear("dr.vega", Rol.ONCOLOGO, "Dr. Andrés Vega"),
            "mora": crear("enf.mora", Rol.ENFERMERIA, "Enf. Laura Mora"), "lopez": crear("adm.lopez", Rol.ADMINISTRATIVO, "Julián López"),
            "auditor": crear("auditor", Rol.AUDITOR, "Auditoría")}


def test_sin_asignacion_no_trabaja_con_ningun_oncologo(conn, gente):
    assert equipo.oncologos_de(conn, gente["mora"].id) == []


def test_asignar_y_retirar_queda_auditado(conn, gente):
    g = gente
    a = equipo.asignar(conn, g["admin"], g["mora"].id, g["gomez"].id, ahora=AHORA)
    assert (a.oncologo_id, a.oncologo_nombre) == (g["gomez"].id, "Dra. Ana Gómez")
    equipo.asignar(conn, g["admin"], g["mora"].id, g["vega"].id, ahora=AHORA)
    equipo.asignar(conn, g["admin"], g["mora"].id, g["gomez"].id, ahora=AHORA)          # idempotente
    assert equipo.oncologos_de(conn, g["mora"].id) == [g["gomez"].id, g["vega"].id]
    equipo.retirar(conn, g["admin"], g["mora"].id, g["gomez"].id, ahora=AHORA)
    assert equipo.oncologos_de(conn, g["mora"].id) == [g["vega"].id]
    detalles = " ".join(f[0] for f in conn.execute("SELECT detalle FROM eventos_acceso"))
    assert "asignar_equipo" in detalles and "retirar_equipo" in detalles
    assert conn.execute("SELECT COUNT(*) FROM equipo_atencion WHERE retirado_en IS NOT NULL").fetchone()[0] == 1   # no se borra


def test_admisiones_tambien_se_asigna(conn, gente):
    equipo.asignar(conn, gente["admin"], gente["lopez"].id, gente["vega"].id)
    assert equipo.oncologos_de(conn, gente["lopez"].id) == [gente["vega"].id]


@pytest.mark.parametrize("persona,oncologo,campo", [("auditor", "gomez", "usuario_id"), ("mora", "lopez", "oncologo_id"), ("gomez", "vega", "usuario_id")])
def test_solo_enfermeria_o_admisiones_y_solo_a_oncologos(conn, gente, persona, oncologo, campo):
    with pytest.raises(adm.ErrorValidacion) as exc:
        equipo.asignar(conn, gente["admin"], gente[persona].id, gente[oncologo].id)
    assert campo in {c for c, _m in exc.value.errores}


def test_solo_el_administrador_asigna(conn, gente):
    oncologa = Usuario(gente["gomez"].id, "dra.gomez", Rol.ONCOLOGO, True)
    with pytest.raises(adm.PermisoDenegadoError):
        equipo.asignar(conn, oncologa, gente["mora"].id, gente["gomez"].id)


def test_un_oncologo_desactivado_sale_del_equipo(conn, gente):
    equipo.asignar(conn, gente["admin"], gente["mora"].id, gente["gomez"].id)
    adm.desactivar_usuario(conn, gente["admin"], gente["gomez"].id, "Retiro de la institución")
    assert equipo.oncologos_de(conn, gente["mora"].id) == []
