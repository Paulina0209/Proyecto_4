"""HC-06: línea de tiempo cronológica del paciente (datos sintéticos)."""
from __future__ import annotations

import pytest

from historia_clinica import laboratorios as hc02
from historia_clinica.db import crear_conexion
from historia_clinica.linea_tiempo import TIPOS_EVENTO, TipoEventoDesconocido, linea_de_tiempo, normalizar_fecha
from patients import db as pdb
from patients.busqueda import registrar_consulta, registrar_diagnostico, registrar_tratamiento
from patients.expediente import paciente_en_expediente
from patients.models import EstadoTratamiento

DOC, NOMBRE = "55443322", "Paciente Línea de Tiempo (sintético)"


@pytest.fixture
def bases():
    conn = pdb.conectar(":memory:")
    pdb.inicializar(conn)
    conn.execute(
        "INSERT INTO pacientes (nombre_completo, sexo, tipo_identificacion, numero_identificacion, oncologo_id, fecha_registro) "
        "VALUES (?, 'femenino', 'cedula', ?, 1, '2026-01-01')", (NOMBRE, DOC))
    conn.commit()
    conn_exp = crear_conexion(":memory:")
    yield conn, conn_exp
    conn_exp.close()
    conn.close()


def _con_historia(conn, conn_exp):
    from datetime import date

    registrar_diagnostico(conn, 1, "Adenocarcinoma de colon", date(2025, 3, 10), "III")
    registrar_tratamiento(conn, 1, EstadoTratamiento.EN_TRATAMIENTO, date(2025, 4, 1), "FOLFOX")
    registrar_consulta(conn, 1, date(2025, 5, 20), "Tolera bien el ciclo 3.")
    exp = paciente_en_expediente(conn, conn_exp, 1, crear=True)
    conn_exp.execute("INSERT INTO imagenologia (paciente_id, fecha, modalidad, region, hallazgos) VALUES (?, '2025-03-01', 'TC', 'Abdomen', 'Masa en colon sigmoide')", (exp,))
    conn_exp.execute("INSERT INTO antecedentes_externos (paciente_id, tipo, descripcion, fecha, fuente) VALUES (?, 'procedimiento', 'Apendicectomía', '2012-08', 'FHIR')", (exp,))
    conn_exp.execute("INSERT INTO antecedentes_externos (paciente_id, tipo, descripcion, fecha, fuente) VALUES (?, 'condicion', 'Hipertensión arterial', '2008', 'FHIR')", (exp,))
    conn_exp.execute("INSERT INTO antecedentes_externos (paciente_id, tipo, descripcion, fecha, fuente) VALUES (?, 'medicacion', 'Losartán', NULL, 'FHIR')", (exp,))
    conn_exp.commit()
    return exp


def test_los_eventos_salen_en_orden_cronologico_de_las_dos_bases(bases):
    conn, conn_exp = bases
    exp = _con_historia(conn, conn_exp)

    eventos = linea_de_tiempo(conn, 1, conn_exp, exp)

    assert [(e.fecha, e.tipo) for e in eventos] == [
        ("2008", "diagnostico"), ("2012-08", "procedimiento"), ("2025-03-01", "estudio_imagen"),
        ("2025-03-10", "diagnostico"), ("2025-04-01", "tratamiento"), ("2025-05-20", "consulta"), (None, "tratamiento"),
    ]
    assert eventos[3].descripcion == "Adenocarcinoma de colon (estadio III)"
    assert eventos[3].tipo_etiqueta == "Diagnóstico"


def test_se_puede_filtrar_por_tipo_de_evento(bases):
    conn, conn_exp = bases
    exp = _con_historia(conn, conn_exp)

    solo = linea_de_tiempo(conn, 1, conn_exp, exp, tipos=["diagnostico"])
    varios = linea_de_tiempo(conn, 1, conn_exp, exp, tipos=["consulta", "estudio_imagen"])

    assert [e.fecha for e in solo] == ["2008", "2025-03-10"]
    assert {e.tipo for e in varios} == {"consulta", "estudio_imagen"} and len(varios) == 2


def test_un_tipo_desconocido_es_un_error_y_no_una_lista_vacia(bases):
    conn, _ = bases
    with pytest.raises(TipoEventoDesconocido, match="consultas"):
        linea_de_tiempo(conn, 1, tipos=["consultas"])


def test_la_fecha_con_solo_mes_y_anio_o_solo_anio_se_marca_aproximada(bases):
    conn, conn_exp = bases
    exp = _con_historia(conn, conn_exp)

    por_fecha = {e.descripcion.split(" (")[0]: e for e in linea_de_tiempo(conn, 1, conn_exp, exp)}

    assert (por_fecha["Apendicectomía"].precision, por_fecha["Apendicectomía"].fecha_aproximada) == ("mes", True)
    assert (por_fecha["Hipertensión arterial"].precision, por_fecha["Hipertensión arterial"].fecha_aproximada) == ("anio", True)
    assert (por_fecha["Adenocarcinoma de colon"].precision, por_fecha["Adenocarcinoma de colon"].fecha_aproximada) == ("dia", False)
    sin_fecha = por_fecha["Losartán"]
    assert sin_fecha.fecha is None and sin_fecha.precision == "desconocida" and not sin_fecha.fecha_aproximada


@pytest.mark.parametrize("cruda, esperado", [
    ("2024-03-05", ("2024-03-05", "dia")), ("2024-03-05T08:30:00", ("2024-03-05", "dia")),
    ("2024-03", ("2024-03", "mes")), ("2024", ("2024", "anio")), (None, (None, "desconocida")),
    ("", (None, "desconocida")), ("desconocida", (None, "desconocida")),
])
def test_normalizar_fecha(cruda, esperado):
    assert normalizar_fecha(cruda) == esperado


def test_los_laboratorios_de_un_dia_son_un_solo_evento_con_lo_critico_primero(bases):
    from datetime import date

    conn, conn_exp = bases
    exp = paciente_en_expediente(conn, conn_exp, 1, crear=True)
    for prueba, valor, unidad, rango in (("Hemoglobina", "13.1", "g/dL", "12.0-16.0"), ("Sodio", "139", "mmol/L", "135-145"),
                                         ("Potasio", "7.0", "mmol/L", "3.5-5.1")):
        hc02.registrar_resultado_laboratorio(conn_exp, exp, identificacion=DOC, nombre=NOMBRE, prueba=prueba, valor=valor,
                                             unidad=unidad, fecha=date(2025, 6, 2), rango_referencia=rango)

    eventos = linea_de_tiempo(conn, 1, conn_exp, exp, tipos=["laboratorio"])

    assert len(eventos) == 1
    assert eventos[0].fecha == "2025-06-02"
    assert eventos[0].descripcion.startswith("3 resultados: Potasio 7.0 mmol/L (crítico)")


def test_lo_mismo_visto_desde_dos_lugares_no_se_duplica(bases):
    from datetime import date

    from historia_clinica import biopsias_biomarcadores as hc04

    conn, conn_exp = bases
    registrar_diagnostico(conn, 1, "Adenocarcinoma de colon", date(2025, 3, 10), "III")
    exp = paciente_en_expediente(conn, conn_exp, 1, crear=True)
    hc04.registrar_episodio(conn_exp, exp, "Adenocarcinoma de colon", "colorectal", date(2025, 3, 10))
    conn.execute("INSERT INTO estudios (paciente_id, tipo, nombre, resumen, fecha) VALUES (1, 'imagen', 'TC abdomen', 'Masa', '2025-03-01')")
    conn.commit()
    conn_exp.execute("INSERT INTO imagenologia (paciente_id, fecha, modalidad, region, hallazgos) VALUES (?, '2025-03-01', 'TC', 'Abdomen', 'Masa en colon sigmoide')", (exp,))
    conn_exp.commit()

    eventos = linea_de_tiempo(conn, 1, conn_exp, exp)

    assert [(e.tipo, e.fuente) for e in eventos] == [("estudio_imagen", "imagenologia"), ("diagnostico", "diagnosticos")]


def test_sin_expediente_muestra_lo_de_la_base_de_pacientes(bases):
    from datetime import date

    conn, _ = bases
    registrar_consulta(conn, 1, date(2025, 1, 5), "Primera consulta.")
    conn.execute("INSERT INTO estudios (paciente_id, tipo, nombre, resumen, fecha) VALUES (1, 'laboratorio', 'CEA', '8.2 ng/mL', '2025-01-04')")
    conn.commit()

    eventos = linea_de_tiempo(conn, 1)

    assert [(e.fecha, e.tipo) for e in eventos] == [("2025-01-04", "laboratorio"), ("2025-01-05", "consulta")]


def test_los_tipos_tienen_etiqueta_legible():
    assert set(TIPOS_EVENTO) >= {"diagnostico", "tratamiento", "consulta", "estudio_imagen", "laboratorio"}
    assert all(etiqueta[0].isupper() for etiqueta in TIPOS_EVENTO.values())
