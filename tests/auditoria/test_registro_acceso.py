"""AUD-01 — Registro de auditoría de accesos y acciones."""

from datetime import datetime, timezone

import pytest

from auditoria import registro_acceso
from auditoria.models import TipoAccion
from auditoria.registro_acceso import (
    crear_conexion,
    obtener_eventos_de_paciente,
    obtener_eventos_de_usuario,
    registrar_acceso,
)

AHORA = datetime(2026, 6, 1, tzinfo=timezone.utc)


@pytest.fixture
def conn():
    conn = crear_conexion(":memory:")
    yield conn
    conn.close()


def test_un_acceso_queda_registrado_con_usuario_fecha_y_accion(conn):
    evento = registrar_acceso(
        conn, usuario_id=10, accion=TipoAccion.VER, paciente_id=1,
        detalle="Apertura del expediente.", ahora=AHORA,
    )
    assert evento.usuario_id == 10
    assert evento.paciente_id == 1
    assert evento.accion is TipoAccion.VER
    assert evento.fecha == AHORA.isoformat()


def test_el_modulo_no_expone_ninguna_forma_de_editar_ni_borrar_un_evento():
    nombres_expuestos = {nombre for nombre in dir(registro_acceso) if not nombre.startswith("_")}
    prohibidos = {"actualizar_evento", "editar_evento", "eliminar_evento", "borrar_evento"}
    assert nombres_expuestos.isdisjoint(prohibidos)


def test_historial_de_paciente_va_del_mas_reciente_al_mas_antiguo(conn):
    registrar_acceso(conn, usuario_id=10, accion=TipoAccion.VER, paciente_id=1, ahora=AHORA)
    registrar_acceso(conn, usuario_id=11, accion=TipoAccion.EDITAR, paciente_id=1, ahora=AHORA)

    historial = obtener_eventos_de_paciente(conn, paciente_id=1)
    assert [e.usuario_id for e in historial] == [11, 10]


def test_historial_de_usuario_permite_reconstruir_que_hizo_una_persona_concreta(conn):
    registrar_acceso(conn, usuario_id=10, accion=TipoAccion.VER, paciente_id=1, ahora=AHORA)
    registrar_acceso(conn, usuario_id=10, accion=TipoAccion.EXPORTAR, paciente_id=2, ahora=AHORA)
    registrar_acceso(conn, usuario_id=99, accion=TipoAccion.VER, paciente_id=1, ahora=AHORA)

    historial = obtener_eventos_de_usuario(conn, usuario_id=10)
    assert len(historial) == 2
    assert {e.paciente_id for e in historial} == {1, 2}
