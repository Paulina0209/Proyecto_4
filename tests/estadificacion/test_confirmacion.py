"""EST-02 — Ajuste manual de estadificación."""

from datetime import datetime, timezone

import pytest

from estadificacion.builder import proponer_estadificacion
from estadificacion.confirmacion import (
    ConfirmacionInvalidaError,
    confirmar_estadificacion,
    crear_conexion,
    obtener_confirmacion_vigente,
    obtener_estadificacion_vigente,
    obtener_historial_confirmaciones,
)

AHORA = datetime(2026, 6, 1, tzinfo=timezone.utc)


@pytest.fixture
def conn_confirmaciones():
    conn = crear_conexion(":memory:")
    yield conn
    conn.close()


def test_confirmar_igual_a_la_sugerencia_no_se_marca_como_diferente(conn_sembrada, conn_confirmaciones):
    conn_hc, ids = conn_sembrada
    propuesta = proponer_estadificacion(conn_hc, ids["paciente_maria"])  # -> IIA

    confirmacion = confirmar_estadificacion(
        conn_confirmaciones,
        ids["paciente_maria"],
        estadio_confirmado="IIA",
        autor="dr. Gómez",
        propuesta_sistema=propuesta,
        ahora=AHORA,
    )

    assert confirmacion.estadio_confirmado == "IIA"
    assert confirmacion.sugerencia_disponible is True
    assert confirmacion.difiere_de_sugerencia is False
    assert confirmacion.estadio_sugerido_por_sistema == "IIA"


def test_el_estadio_confirmado_por_el_medico_es_el_final_aunque_difiera(conn_sembrada, conn_confirmaciones):
    conn_hc, ids = conn_sembrada
    propuesta = proponer_estadificacion(conn_hc, ids["paciente_maria"])  # -> IIA sugerido

    confirmacion = confirmar_estadificacion(
        conn_confirmaciones,
        ids["paciente_maria"],
        estadio_confirmado="IIIA",
        autor="dr. Gómez",
        propuesta_sistema=propuesta,
        justificacion="Reevaluación de ganglios en junta multidisciplinaria.",
        ahora=AHORA,
    )

    assert confirmacion.estadio_confirmado == "IIIA"
    assert confirmacion.difiere_de_sugerencia is True
    assert confirmacion.estadio_sugerido_por_sistema == "IIA"
    assert confirmacion.sistema_id == "AJCC"

    vigente = obtener_estadificacion_vigente(conn_confirmaciones, ids["paciente_maria"], propuesta)
    assert vigente.fuente == "confirmacion_medica"
    assert vigente.estadio == "IIIA"
    assert vigente.es_confirmacion_medica() is True


def test_diferencia_se_registra_de_forma_insensible_a_mayusculas_y_espacios(conn_sembrada, conn_confirmaciones):
    conn_hc, ids = conn_sembrada
    propuesta = proponer_estadificacion(conn_hc, ids["paciente_maria"])  # -> IIA

    confirmacion = confirmar_estadificacion(
        conn_confirmaciones,
        ids["paciente_maria"],
        estadio_confirmado="  iia  ",
        autor="dr. Gómez",
        propuesta_sistema=propuesta,
        ahora=AHORA,
    )
    assert confirmacion.difiere_de_sugerencia is False


def test_confirmacion_sin_sugerencia_del_sistema_no_se_marca_como_diferente(conn_confirmaciones):
    # Paciente sin propuesta de EST-01 disponible (p. ej. sistema no soportado
    # o T/N/M insuficientes): no hay nada contra qué comparar.
    confirmacion = confirmar_estadificacion(
        conn_confirmaciones,
        paciente_id=999,
        estadio_confirmado="IIB",
        autor="dr. Gómez",
        propuesta_sistema=None,
        ahora=AHORA,
    )
    assert confirmacion.sugerencia_disponible is False
    assert confirmacion.difiere_de_sugerencia is False
    assert confirmacion.estadio_sugerido_por_sistema is None


def test_estadio_vacio_o_autor_vacio_se_rechazan(conn_confirmaciones):
    with pytest.raises(ConfirmacionInvalidaError):
        confirmar_estadificacion(conn_confirmaciones, 1, "   ", autor="dr. Gómez", ahora=AHORA)
    with pytest.raises(ConfirmacionInvalidaError):
        confirmar_estadificacion(conn_confirmaciones, 1, "IIA", autor="", ahora=AHORA)


def test_nunca_bloquea_ni_sobreescribe_una_confirmacion_previa(conn_confirmaciones):
    confirmar_estadificacion(conn_confirmaciones, 1, "IIA", autor="dr. Gómez", ahora=AHORA)
    confirmar_estadificacion(conn_confirmaciones, 1, "IIIA", autor="dr. Gómez", ahora=AHORA)

    historial = obtener_historial_confirmaciones(conn_confirmaciones, 1)
    assert [c.estadio_confirmado for c in historial] == ["IIIA", "IIA"]

    vigente = obtener_confirmacion_vigente(conn_confirmaciones, 1)
    assert vigente.estadio_confirmado == "IIIA"


def test_sin_ninguna_confirmacion_prevalece_la_propuesta_del_sistema_como_apoyo(conn_sembrada, conn_confirmaciones):
    conn_hc, ids = conn_sembrada
    propuesta = proponer_estadificacion(conn_hc, ids["paciente_maria"])

    vigente = obtener_estadificacion_vigente(conn_confirmaciones, ids["paciente_maria"], propuesta)
    assert vigente.fuente == "apoyo_sistema"
    assert vigente.estadio == "IIA"
    assert vigente.es_confirmacion_medica() is False


def test_estadificacion_incompleta_sin_confirmar_no_presenta_estadio_vigente(conn_sembrada, conn_confirmaciones):
    conn_hc, ids = conn_sembrada
    # Laura: T y N documentados, M pendiente -> sin estadio_global.
    propuesta = proponer_estadificacion(conn_hc, ids["paciente_laura"])
    assert propuesta.estadio_global is None

    vigente = obtener_estadificacion_vigente(conn_confirmaciones, ids["paciente_laura"], propuesta)
    assert vigente.fuente == "apoyo_sistema"
    assert vigente.estadio is None


def test_componentes_confirmados_se_conservan_como_snapshot_de_auditoria(conn_confirmaciones):
    confirmacion = confirmar_estadificacion(
        conn_confirmaciones,
        1,
        "IIIA",
        autor="dr. Gómez",
        componentes_confirmados={"T": "T2", "N": "N2", "M": "M0"},
        ahora=AHORA,
    )
    assert confirmacion.componentes_confirmados == {"T": "T2", "N": "N2", "M": "M0"}
