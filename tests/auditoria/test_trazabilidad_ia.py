"""AUD-02 — Trazabilidad de recomendaciones de IA (vista unificada DX + EST + TX)."""

from datetime import datetime, timezone

import pytest

from auditoria.trazabilidad_ia import obtener_trazabilidad_ia_paciente
from clinical_decision.registro import crear_conexion as crear_conexion_tx
from clinical_decision.registro import registrar_decision_tratamiento
from dx_clinica.juicio_clinico import crear_conexion as crear_conexion_dx
from dx_clinica.juicio_clinico import registrar_juicio_clinico
from estadificacion.confirmacion import confirmar_estadificacion
from estadificacion.confirmacion import crear_conexion as crear_conexion_est

AHORA = datetime(2026, 6, 1, tzinfo=timezone.utc)


@pytest.fixture
def conn_dx():
    conn = crear_conexion_dx(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def conn_est():
    conn = crear_conexion_est(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def conn_tx():
    conn = crear_conexion_tx(":memory:")
    yield conn
    conn.close()


def test_cada_dominio_disponible_aparece_vinculado_a_la_decision_del_medico(conn_dx, conn_est, conn_tx):
    registrar_juicio_clinico(
        conn_dx, paciente_id=1, diagnostico_registrado="Carcinoma ductal infiltrante.",
        autor="dra. Gómez", ahora=AHORA,
    )
    confirmar_estadificacion(
        conn_est, paciente_id=1, estadio_confirmado="IIIA", autor="dra. Gómez", ahora=AHORA,
    )
    registrar_decision_tratamiento(
        conn_tx, paciente_id=1, oncologo_id=10, tipo_decision="reject",
        recomendacion_ia_snapshot={}, regimenes_candidatos_ids=[],
        regimen_sugerido_id="AC-T", motivo_rechazo="Neuropatía previa.",
    )

    trazabilidad = obtener_trazabilidad_ia_paciente(
        paciente_id=1, conn_dx=conn_dx, conn_est=conn_est, conn_tx=conn_tx
    )

    dominios = {r.dominio for r in trazabilidad}
    assert dominios == {"DX", "EST", "TX"}
    for registro in trazabilidad:
        assert registro.decision_medico  # siempre hay una decisión del médico vinculada.


def test_un_dominio_se_omite_si_no_se_provee_su_conexion(conn_est):
    confirmar_estadificacion(
        conn_est, paciente_id=1, estadio_confirmado="IIIA", autor="dra. Gómez", ahora=AHORA,
    )

    trazabilidad = obtener_trazabilidad_ia_paciente(paciente_id=1, conn_est=conn_est)

    assert {r.dominio for r in trazabilidad} == {"EST"}


def test_sin_ninguna_conexion_provista_devuelve_vacio():
    assert obtener_trazabilidad_ia_paciente(paciente_id=1) == ()


def test_est_marca_diferencia_cuando_el_medico_no_sigue_la_sugerencia(conn_est):
    from estadificacion.builder import proponer_estadificacion
    from historia_clinica_mock.db import crear_conexion as crear_conexion_hc
    from historia_clinica_mock.seed import sembrar_datos_sinteticos

    conn_hc = crear_conexion_hc(":memory:")
    ids = sembrar_datos_sinteticos(conn_hc)
    propuesta = proponer_estadificacion(conn_hc, ids["paciente_maria"])

    confirmar_estadificacion(
        conn_est, paciente_id=ids["paciente_maria"], estadio_confirmado="IIIA",
        autor="dra. Gómez", propuesta_sistema=propuesta, ahora=AHORA,
    )

    trazabilidad = obtener_trazabilidad_ia_paciente(paciente_id=ids["paciente_maria"], conn_est=conn_est)
    assert trazabilidad[0].difiere_de_sugerencia is True


def test_tx_reject_se_marca_como_diferente_de_la_sugerencia(conn_tx):
    registrar_decision_tratamiento(
        conn_tx, paciente_id=1, oncologo_id=10, tipo_decision="reject",
        recomendacion_ia_snapshot={}, regimenes_candidatos_ids=[],
        regimen_sugerido_id="AC-T", motivo_rechazo="Neuropatía previa.",
    )

    trazabilidad = obtener_trazabilidad_ia_paciente(paciente_id=1, conn_tx=conn_tx)
    assert trazabilidad[0].difiere_de_sugerencia is True
    assert trazabilidad[0].recomendacion_sistema == "AC-T"


def test_orden_del_mas_reciente_al_mas_antiguo_entre_dominios(conn_dx, conn_est):
    from datetime import timedelta

    confirmar_estadificacion(
        conn_est, paciente_id=1, estadio_confirmado="IIA", autor="dra. Gómez", ahora=AHORA,
    )
    registrar_juicio_clinico(
        conn_dx, paciente_id=1, diagnostico_registrado="Diagnóstico posterior.",
        autor="dra. Gómez", ahora=AHORA + timedelta(days=1),
    )

    trazabilidad = obtener_trazabilidad_ia_paciente(paciente_id=1, conn_dx=conn_dx, conn_est=conn_est)
    assert [r.dominio for r in trazabilidad] == ["DX", "EST"]
