"""EST-03 — Manejo de la estadificación incompleta."""

from estadificacion.builder import proponer_estadificacion
from estadificacion.incompleta import analizar_estadificacion_incompleta


def _analizar(conn, paciente_id):
    return analizar_estadificacion_incompleta(proponer_estadificacion(conn, paciente_id))


def test_identifica_explicitamente_el_componente_que_no_se_puede_determinar(conn_sembrada):
    conn, ids = conn_sembrada
    # Laura: T y N documentados, M pendiente.
    analisis = _analizar(conn, ids["paciente_laura"])

    indeterminados = {c.codigo for c in analisis.componentes_indeterminados}
    assert indeterminados == {"M"}
    m = analisis.componentes_indeterminados[0]
    assert m.variable_expediente == "clinical_m_status"
    assert m.motivo == "sin dato registrado en el expediente"


def test_muestra_los_componentes_establecidos_sin_asumir_los_faltantes(conn_sembrada):
    conn, ids = conn_sembrada
    analisis = _analizar(conn, ids["paciente_laura"])

    assert set(analisis.componentes_determinados) == {"T", "N"}
    # No se asume ningún valor para M.
    assert "M" not in analisis.componentes_determinados
    assert not analisis.estadificacion_completa


def test_indica_que_informacion_adicional_se_necesita(conn_sembrada):
    conn, ids = conn_sembrada
    analisis = _analizar(conn, ids["paciente_laura"])

    assert analisis.informacion_faltante
    assert all(texto.strip() for texto in analisis.informacion_faltante)
    assert "metástasis" in analisis.componentes_indeterminados[0].informacion_requerida


def test_comunica_el_rango_de_estadios_posibles_sin_elegir_uno(conn_sembrada):
    conn, ids = conn_sembrada
    analisis = _analizar(conn, ids["paciente_laura"])

    # melanoma pT3 N0, con M en {M0, M1}: II (M0) o IV (M1).
    assert set(analisis.estadios_posibles) == {"II", "IV"}
    assert analisis.rango_legible is not None
    assert "II" in analisis.rango_legible and "IV" in analisis.rango_legible


def test_no_presenta_un_estadio_definitivo_si_la_informacion_es_insuficiente(conn_sembrada):
    conn, ids = conn_sembrada
    analisis = _analizar(conn, ids["paciente_laura"])

    assert analisis.estadio_confirmado is False
    propuesta = proponer_estadificacion(conn, ids["paciente_laura"])
    assert propuesta.estadio_global is None


def test_estadificacion_completa_queda_marcada_como_confirmada(conn_sembrada):
    conn, ids = conn_sembrada
    # María: cT2 N0 cM0 -> IIA, sin componentes pendientes.
    analisis = _analizar(conn, ids["paciente_maria"])

    assert analisis.estadificacion_completa is True
    assert analisis.estadio_confirmado is True
    assert analisis.componentes_indeterminados == ()
    assert analisis.estadios_posibles == ("IIA",)


def test_metastasis_conocida_acota_el_estadio_aunque_falten_componentes(conn_sembrada):
    conn, ids = conn_sembrada
    # Paciente NSCLC con solo M1 documentado: T y N pendientes, pero el grupo
    # ya queda acotado a IV por el comodín de la tabla.
    conn.execute(
        "INSERT INTO datos_clinicos_estructurados (paciente_id, consulta_id, fecha, variable, valor) "
        "VALUES (?, ?, ?, ?, ?)",
        (ids["paciente_carlos"], ids["consulta_carlos_1"], "2026-02-03", "clinical_m_status", "cM1"),
    )
    analisis = _analizar(conn, ids["paciente_carlos"])

    assert {c.codigo for c in analisis.componentes_indeterminados} == {"T", "N"}
    assert analisis.estadios_posibles == ("IV",)
    # Un solo estadio posible pero con componentes pendientes: no se marca como
    # "completa", aunque el grupo esté acotado.
    assert analisis.estadificacion_completa is False
    assert analisis.estadio_confirmado is False


def test_sin_ningun_componente_determinado_no_acota_el_estadio(conn_sembrada):
    conn, ids = conn_sembrada
    # Patricia (RCC): sin T/N/M en el expediente.
    analisis = _analizar(conn, ids["paciente_patricia"])

    assert set(c.codigo for c in analisis.componentes_indeterminados) == {"T", "N", "M"}
    assert analisis.componentes_determinados == ()
    assert analisis.estadio_confirmado is False
