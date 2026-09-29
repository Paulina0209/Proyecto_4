"""Importación al expediente por el camino de HC-01, e integración con HC-05."""

from cbioportal import importar_estudio, importar_paciente, seleccionar_pacientes
from historia_clinica.informacion_faltante import EstadoCompletitud, evaluar_informacion_faltante
from historia_clinica.integracion_externa import listar_sincronizaciones, sincronizar_paciente
from expediente.repository import (
    biomarcadores_de_paciente,
    facts_estructurados_de_paciente,
    laboratorios_de_paciente,
    obtener_paciente,
)

from .conftest import ESTUDIO


def _contar(conn, tabla, paciente_id):
    return conn.execute(f"SELECT COUNT(*) FROM {tabla} WHERE paciente_id = ?", (paciente_id,)).fetchone()[0]


def test_crea_el_paciente_y_carga_su_expediente(conn, fuente):
    r = importar_paciente(conn, fuente, ESTUDIO, "P-0000015")

    assert r.sincronizacion.exito and r.paciente_nuevo
    paciente = obtener_paciente(conn, r.paciente_id)
    assert paciente.identificacion == "CBIO:msk_chord_2024:P-0000015"
    assert paciente.estadio == "I"
    assert facts_estructurados_de_paciente(conn, r.paciente_id)["cancer_type"] == "breast"
    assert len(laboratorios_de_paciente(conn, r.paciente_id)) == 2
    assert _contar(conn, "imagenologia", r.paciente_id) == 1

    [sincronizacion] = listar_sincronizaciones(conn, r.paciente_id)
    assert sincronizacion.formato == "cbioportal" and sincronizacion.estado == "exitosa"
    assert sincronizacion.registros_importados == r.sincronizacion.registros_importados > 0


def test_reimportar_no_duplica(conn, fuente):
    primera = importar_paciente(conn, fuente, ESTUDIO, "P-0000015")
    antes = _contar(conn, "biomarcadores", primera.paciente_id)

    segunda = importar_paciente(conn, fuente, ESTUDIO, "P-0000015")

    assert segunda.paciente_id == primera.paciente_id and not segunda.paciente_nuevo
    assert segunda.sincronizacion.registros_importados == 0
    assert _contar(conn, "biomarcadores", primera.paciente_id) == antes
    assert conn.execute("SELECT COUNT(*) FROM pacientes").fetchone()[0] == 1


def test_reimportar_agrega_solo_lo_nuevo(conn, cliente, fuente):
    primera = importar_paciente(conn, fuente, ESTUDIO, "P-0000015")
    cliente.pacientes["P-0000015"]["eventos"].append(
        {"tipo": "Lab_Test", "inicio": 415, "fin": None,
         "atributos": {"TEST": "CEA", "LR_UNIT_MEASURE": "ng/ml", "RESULT": "9.1"}}
    )
    segunda = importar_paciente(conn, fuente, ESTUDIO, "P-0000015")
    assert segunda.sincronizacion.registros_importados == 1
    assert len(laboratorios_de_paciente(conn, primera.paciente_id)) == 3


def test_fallo_de_red_con_paciente_nuevo_no_crea_nada(conn, cliente, fuente):
    cliente.falla_en.add("P-0000015")
    r = importar_paciente(conn, fuente, ESTUDIO, "P-0000015")
    assert not r.sincronizacion.exito and r.paciente_id is None
    assert "No se creó el paciente" in r.sincronizacion.mensaje
    assert conn.execute("SELECT COUNT(*) FROM pacientes").fetchone()[0] == 0


def test_fallo_de_red_con_paciente_existente_queda_registrado_sin_tocar_el_expediente(conn, cliente, fuente):
    primera = importar_paciente(conn, fuente, ESTUDIO, "P-0000015")
    labs = len(laboratorios_de_paciente(conn, primera.paciente_id))
    cliente.falla_en.add("P-0000015")

    r = importar_paciente(conn, fuente, ESTUDIO, "P-0000015")

    assert not r.sincronizacion.exito
    assert "El resto del expediente sigue disponible" in r.sincronizacion.mensaje
    assert [s.estado for s in listar_sincronizaciones(conn, primera.paciente_id)] == ["fallida", "exitosa"]
    assert len(laboratorios_de_paciente(conn, primera.paciente_id)) == labs


def test_la_fuente_sirve_para_sincronizar_paciente_de_hc01(conn, fuente):
    paciente_id = importar_paciente(conn, fuente, ESTUDIO, "P-0000036").paciente_id
    r = sincronizar_paciente(conn, paciente_id, fuente)
    assert r.exito and r.registros_importados == 0


def test_seleccion_por_tipo_excluye_pacientes_con_varios_canceres(cliente):
    assert seleccionar_pacientes(cliente, ESTUDIO, ["Breast Cancer"], 10) == ["P-0000015"]
    assert seleccionar_pacientes(cliente, ESTUDIO, ["Non-Small Cell Lung Cancer"], 10) == ["P-0000036"]
    assert seleccionar_pacientes(cliente, ESTUDIO, ["Breast Cancer", "Non-Small Cell Lung Cancer"], 0) == []


def test_importar_estudio_sigue_aunque_falle_un_paciente(conn, cliente, fuente):
    cliente.falla_en.add("P-0000015")
    avance = []
    resultados = importar_estudio(
        conn, fuente, ESTUDIO, ["P-0000015", "P-0000036"], al_importar=lambda i, n, r: avance.append((i, n))
    )
    assert [r.sincronizacion.exito for r in resultados] == [False, True]
    assert avance == [(1, 2), (2, 2)]


# --- HC-05 sobre pacientes importados -----------------------------------------


def test_hc05_mama_importada_no_se_marca_completa_sin_tnm(conn, fuente):
    paciente_id = importar_paciente(conn, fuente, ESTUDIO, "P-0000015").paciente_id
    evaluacion = evaluar_informacion_faltante(conn, paciente_id)

    assert evaluacion.estado is EstadoCompletitud.INCOMPLETA
    faltantes = {f.id for f in evaluacion.faltantes}
    # HR/HER2 "No" de MSK-CHORD no es un negativo confirmado: el oncólogo
    # debe registrar RE, RP y HER2 (ver mapeo).
    assert {"receptor_estrogeno", "receptor_progesterona", "her2", "categoria_t", "categoria_n"} <= faltantes


def test_hc05_pulmon_pide_tps_aunque_haya_pdl1_binario(conn, fuente):
    paciente_id = importar_paciente(conn, fuente, ESTUDIO, "P-0000036").paciente_id
    evaluacion = evaluar_informacion_faltante(conn, paciente_id)
    faltantes = {f.id for f in evaluacion.faltantes}
    presentes = {p[0] for p in evaluacion.presentes}
    assert "pdl1" in faltantes
    assert {"egfr", "alk", "histologia", "imagen_torax"} <= presentes


def test_hc05_no_evalua_paciente_con_dos_canceres(conn, fuente):
    paciente_id = importar_paciente(conn, fuente, ESTUDIO, "P-0000012").paciente_id
    assert evaluar_informacion_faltante(conn, paciente_id).estado is EstadoCompletitud.NO_EVALUABLE


def test_biomarcadores_quedan_consultables_por_el_repositorio(conn, fuente):
    paciente_id = importar_paciente(conn, fuente, ESTUDIO, "P-0000036").paciente_id
    nombres = {b.biomarcador for b in biomarcadores_de_paciente(conn, paciente_id)}
    assert {"EGFR", "ALK", "KRAS"} <= nombres
