"""HC-05 — Detección de información faltante (tres criterios de aceptación)."""

import pytest

from historia_clinica.informacion_faltante import (
    EstadoCompletitud,
    cargar_checklists,
    evaluar_informacion_faltante,
)

from .conftest import insertar_biomarcador, insertar_dato, insertar_imagen, insertar_paciente


def _mama_completa(conn, paciente_id):
    insertar_dato(conn, paciente_id, "histopathology_confirmed", "yes")
    insertar_imagen(conn, paciente_id, "mama derecha")
    insertar_dato(conn, paciente_id, "er_status", "positive")
    insertar_dato(conn, paciente_id, "pr_status", "negative")
    insertar_biomarcador(conn, paciente_id, "HER2", "negativo")
    insertar_dato(conn, paciente_id, "clinical_t_category", "cT2")
    insertar_dato(conn, paciente_id, "clinical_n_status", "N0")
    insertar_dato(conn, paciente_id, "clinical_m_status", "cM0")


# --- AC1: sospecha de cáncer de mama -> indica si faltan receptores o HER2 ---


def test_mama_sin_receptores_hormonales_ni_her2_los_reporta_como_faltantes(conn):
    paciente_id = insertar_paciente(conn, cancer_type="breast")

    evaluacion = evaluar_informacion_faltante(conn, paciente_id, fases=["diagnostico"])

    assert evaluacion.estado is EstadoCompletitud.INCOMPLETA
    faltantes = {f.id for f in evaluacion.faltantes}
    assert {"receptor_estrogeno", "receptor_progesterona", "her2"} <= faltantes
    assert evaluacion.mostrar_alerta
    assert "receptor de estrógeno" in evaluacion.alerta
    assert "HER2" in evaluacion.alerta


def test_sospecha_de_mama_se_puede_indicar_sin_diagnostico_registrado(conn):
    paciente_id = insertar_paciente(conn)

    evaluacion = evaluar_informacion_faltante(conn, paciente_id, tipo_cancer="cáncer de mama")

    assert evaluacion.tipo_cancer == "breast"
    assert evaluacion.estado is EstadoCompletitud.INCOMPLETA


def test_paciente_sembrada_con_her2_pero_sin_receptores(conn_sembrada):
    conn, ids = conn_sembrada

    evaluacion = evaluar_informacion_faltante(conn, ids["paciente_maria"], fases=["diagnostico"])

    faltantes = {f.id for f in evaluacion.faltantes}
    assert "her2" not in faltantes  # el HER2 "negativo" del seed cuenta como presente
    assert {"receptor_estrogeno", "receptor_progesterona"} <= faltantes
    assert ("her2", f"biomarcador-{ids['biomarcador_maria_1']}") in evaluacion.presentes


@pytest.mark.parametrize("valor", ["equívoco", "pendiente", "Indeterminado", "unknown"])
def test_valor_no_concluyente_cuenta_como_faltante_y_se_muestra(conn, valor):
    paciente_id = insertar_paciente(conn, cancer_type="breast")
    insertar_biomarcador(conn, paciente_id, "HER2", valor)

    evaluacion = evaluar_informacion_faltante(conn, paciente_id, fases=["diagnostico"])

    her2 = next(f for f in evaluacion.faltantes if f.id == "her2")
    assert her2.motivo == "valor no concluyente"
    assert her2.valor_registrado == valor
    assert her2.fuente.startswith("biomarcador-")


def test_resultado_reciente_concluyente_reemplaza_uno_viejo_pendiente(conn):
    paciente_id = insertar_paciente(conn, cancer_type="breast")
    insertar_biomarcador(conn, paciente_id, "HER2", "pendiente", fecha="2026-01-01")
    insertar_biomarcador(conn, paciente_id, "HER2", "positivo", fecha="2026-02-01")

    evaluacion = evaluar_informacion_faltante(conn, paciente_id, fases=["diagnostico"])

    assert "her2" not in {f.id for f in evaluacion.faltantes}


def test_ultimo_valor_de_una_variable_es_el_que_cuenta(conn):
    paciente_id = insertar_paciente(conn, cancer_type="breast")
    insertar_dato(conn, paciente_id, "er_status", "positive", fecha="2026-01-01")
    insertar_dato(conn, paciente_id, "er_status", "unknown", fecha="2026-03-01")

    evaluacion = evaluar_informacion_faltante(conn, paciente_id, fases=["diagnostico"])

    receptor = next(f for f in evaluacion.faltantes if f.id == "receptor_estrogeno")
    assert receptor.valor_registrado == "unknown"


def test_solo_evalua_los_items_de_la_fase_pedida(conn):
    paciente_id = insertar_paciente(conn, cancer_type="breast")

    evaluacion = evaluar_informacion_faltante(conn, paciente_id, fases=["estadificacion"])

    assert {f.id for f in evaluacion.faltantes} == {"categoria_t", "categoria_n", "categoria_m"}


# --- AC2: toda la información disponible -> sin alerta ---


def test_expediente_completo_no_muestra_alerta(conn):
    paciente_id = insertar_paciente(conn, cancer_type="breast")
    _mama_completa(conn, paciente_id)

    evaluacion = evaluar_informacion_faltante(conn, paciente_id)

    assert evaluacion.estado is EstadoCompletitud.COMPLETA
    assert evaluacion.faltantes == ()
    assert not evaluacion.mostrar_alerta
    assert evaluacion.alerta is None


# --- AC3: sin checklist para ese tipo de cáncer -> no asume completo ---


def test_tipo_de_cancer_sin_checklist_es_no_evaluable_y_alerta(conn):
    paciente_id = insertar_paciente(conn, cancer_type="glioblastoma")

    evaluacion = evaluar_informacion_faltante(conn, paciente_id)

    assert evaluacion.estado is EstadoCompletitud.NO_EVALUABLE
    assert evaluacion.mostrar_alerta
    assert "no puede evaluar" in evaluacion.alerta
    assert "no significa que la información esté completa" in evaluacion.alerta


def test_sin_tipo_de_cancer_conocido_es_no_evaluable(conn):
    paciente_id = insertar_paciente(conn)

    evaluacion = evaluar_informacion_faltante(conn, paciente_id)

    assert evaluacion.estado is EstadoCompletitud.NO_EVALUABLE
    assert evaluacion.mostrar_alerta


def test_fase_sin_items_en_el_checklist_es_no_evaluable(conn):
    paciente_id = insertar_paciente(conn, cancer_type="renal_cell_carcinoma")

    evaluacion = evaluar_informacion_faltante(conn, paciente_id, fases=["estadificacion"])

    assert evaluacion.estado is EstadoCompletitud.NO_EVALUABLE


# --- Configuración del checklist ---


def test_checklist_institucional_personalizado(conn, tmp_path):
    ruta = tmp_path / "checklist.yaml"
    ruta.write_text(
        "tipos_cancer:\n"
        "  glioblastoma:\n"
        "    nombre: Glioblastoma\n"
        "    items:\n"
        "      - id: mgmt\n"
        "        descripcion: Metilación de MGMT\n"
        "        fases: [tratamiento]\n"
        "        evidencias:\n"
        "          - biomarcador: [mgmt]\n",
        encoding="utf-8",
    )
    paciente_id = insertar_paciente(conn, cancer_type="glioblastoma")

    evaluacion = evaluar_informacion_faltante(conn, paciente_id, checklists=cargar_checklists(ruta))

    assert evaluacion.estado is EstadoCompletitud.INCOMPLETA
    assert [f.id for f in evaluacion.faltantes] == ["mgmt"]


def test_checklist_con_item_sin_evidencias_se_rechaza_al_cargar(tmp_path):
    ruta = tmp_path / "checklist.yaml"
    ruta.write_text(
        "tipos_cancer:\n  x:\n    items:\n      - id: a\n        fases: [tratamiento]\n        evidencias: []\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        cargar_checklists(ruta)


def test_checklist_con_fase_invalida_se_rechaza_al_cargar(tmp_path):
    ruta = tmp_path / "checklist.yaml"
    ruta.write_text(
        "tipos_cancer:\n  x:\n    items:\n      - id: a\n        fases: [seguimiento]\n"
        "        evidencias:\n          - variable: v\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        cargar_checklists(ruta)


def test_checklist_por_defecto_es_valido():
    assert "breast" in cargar_checklists()["tipos_cancer"]


def test_fase_desconocida_es_error(conn):
    paciente_id = insertar_paciente(conn, cancer_type="breast")
    with pytest.raises(ValueError):
        evaluar_informacion_faltante(conn, paciente_id, fases=["seguimiento"])


def test_paciente_inexistente_es_error(conn):
    with pytest.raises(ValueError):
        evaluar_informacion_faltante(conn, 999)
