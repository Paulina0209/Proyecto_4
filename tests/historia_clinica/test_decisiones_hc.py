"""Lo que el médico confirma o corrige de la IA queda en la historia clínica (ficha y consulta del día)."""
from datetime import date

import pytest

from historia_clinica.db import crear_conexion
from historia_clinica.decisiones_hc import incorporar_decision
from patients import db as db_pacientes

HOY = date(2026, 10, 27)
ID = "CBIO:msk_chord_2024:P-0000001"
AUTORA = "Dra. Ana Gómez (dra.gomez)"


@pytest.fixture
def bases():
    exp = crear_conexion()
    exp.execute("INSERT INTO pacientes (nombre, fecha_nacimiento, sexo, identificacion, diagnostico_principal, estadio) "
                "VALUES ('Paciente', '1970-01-01', 'femenino', ?, 'Carcinoma ductal', 'II')", (ID,))
    pac = db_pacientes.conectar(":memory:")
    db_pacientes.inicializar(pac)
    pac.execute("INSERT INTO pacientes (nombre_completo, sexo, tipo_identificacion, numero_identificacion, oncologo_id, fecha_registro) "
                "VALUES ('Paciente', 'femenino', 'externo', ?, 2, '2024-01-01')", (ID,))
    pac.execute("INSERT INTO diagnosticos (paciente_id, descripcion, estadio, fecha) VALUES (1, 'Carcinoma ductal', 'II', '2024-01-01')")
    pac.commit()
    return exp, pac


def _ficha(exp):
    return tuple(exp.execute("SELECT diagnostico_principal, estadio FROM pacientes WHERE id = 1").fetchone())


def _consulta_de_hoy(exp):
    return exp.execute("SELECT motivo, notas_libres FROM consultas WHERE paciente_id = 1 AND fecha = ?", (HOY.isoformat(),)).fetchall()


def test_corregir_el_diagnostico_reemplaza_la_ficha_y_conserva_el_historial(bases):
    exp, pac = bases
    inc = incorporar_decision(exp, 1, tipo="diagnostico", valor="Carcinoma lobulillar infiltrante", sugerencia="Carcinoma ductal",
                              autor=AUTORA, conn_pacientes=pac, hoy=HOY)
    assert inc.corregido and _ficha(exp)[0] == "Carcinoma lobulillar infiltrante"
    historial = [f[0] for f in pac.execute("SELECT descripcion FROM diagnosticos WHERE paciente_id = 1 ORDER BY fecha DESC, id DESC")]
    assert historial == ["Carcinoma lobulillar infiltrante", "Carcinoma ductal"]          # el vigente arriba, el anterior no se borra
    ((motivo, notas),) = _consulta_de_hoy(exp)
    assert "Diagnóstico corregido: Carcinoma lobulillar infiltrante" in notas and "la IA había sugerido: Carcinoma ductal" in notas and "Responsable: Dra. Ana Gómez" in notas
    assert "antes en la ficha: Carcinoma ductal" in notas


def test_confirmar_lo_sugerido_lo_dice(bases):
    exp, pac = bases
    inc = incorporar_decision(exp, 1, tipo="diagnostico", valor="Carcinoma ductal", sugerencia="carcinoma  ductal",
                              autor=AUTORA, conn_pacientes=pac, hoy=HOY)
    assert not inc.corregido and "confirmado" in inc.linea and "coincide con la sugerencia de la IA" in inc.linea


def test_el_estadio_va_a_la_ficha_y_a_la_misma_consulta_del_dia(bases):
    exp, pac = bases
    incorporar_decision(exp, 1, tipo="diagnostico", valor="Carcinoma ductal", autor=AUTORA, conn_pacientes=pac, hoy=HOY)
    incorporar_decision(exp, 1, tipo="estadio", valor="IIIA", sugerencia="IIB", autor=AUTORA, detalle="Justificación: N2 en PET",
                        conn_pacientes=pac, hoy=HOY)
    assert _ficha(exp) == ("Carcinoma ductal", "IIIA")
    consultas = _consulta_de_hoy(exp)
    assert len(consultas) == 1 and "Estadio corregido" in consultas[0][1] and "N2 en PET" in consultas[0][1]
    assert pac.execute("SELECT estadio FROM diagnosticos ORDER BY fecha DESC, id DESC LIMIT 1").fetchone()[0] == "IIIA"


def test_tratamiento_aceptado_queda_en_curso_y_el_rechazo_solo_en_la_consulta(bases):
    exp, pac = bases
    incorporar_decision(exp, 1, tipo="tratamiento", valor="pembro_monotherapy (pembrolizumab)",
                        sugerencia="pembro_monotherapy (pembrolizumab)", autor=AUTORA, conn_pacientes=pac, hoy=HOY)
    assert [tuple(f) for f in pac.execute("SELECT estado, regimen FROM tratamientos")] == [("en_tratamiento", "pembro_monotherapy (pembrolizumab)")]
    incorporar_decision(exp, 1, tipo="tratamiento", valor="rechazado", sugerencia="x", detalle="Prefiere esperar", autor=AUTORA,
                        conn_pacientes=pac, hoy=HOY)
    assert pac.execute("SELECT COUNT(*) FROM tratamientos").fetchone()[0] == 1
    notas = _consulta_de_hoy(exp)[0][1]
    assert "coincide con la sugerencia de la IA" in notas and "Tratamiento sugerido por la IA rechazado" in notas and "Prefiere esperar" in notas
    nota_pac = pac.execute("SELECT nota FROM consultas WHERE fecha = ?", (HOY.isoformat(),)).fetchone()[0]
    assert "rechazado" in nota_pac                                                         # también en la base de pacientes (resumen 360)


def test_una_consulta_existente_de_hoy_se_completa_no_se_duplica(bases):
    exp, pac = bases
    exp.execute("INSERT INTO consultas (paciente_id, fecha, motivo, notas_libres) VALUES (1, ?, 'Control', 'Refiere fatiga.')", (HOY.isoformat(),))
    incorporar_decision(exp, 1, tipo="estadio", valor="II", autor=AUTORA, conn_pacientes=pac, hoy=HOY)
    ((motivo, notas),) = _consulta_de_hoy(exp)
    assert motivo == "Control" and notas.startswith("Refiere fatiga.\n") and "Estadio confirmado: II" in notas


def test_valores_invalidos(bases):
    exp, pac = bases
    with pytest.raises(ValueError):
        incorporar_decision(exp, 1, tipo="otra_cosa", valor="x", autor=AUTORA, conn_pacientes=pac)
    with pytest.raises(ValueError):
        incorporar_decision(exp, 1, tipo="diagnostico", valor="  ", autor=AUTORA, conn_pacientes=pac)


def test_sin_sugerencia_de_la_ia_el_verbo_dice_lo_que_paso(bases):
    exp, pac = bases
    assert "Diagnóstico actualizado: Sarcoma" in incorporar_decision(exp, 1, tipo="diagnostico", valor="Sarcoma", autor=AUTORA,
                                                                conn_pacientes=pac, hoy=HOY).linea
    assert "Estadio actualizado: IV" in incorporar_decision(exp, 1, tipo="estadio", valor="IV", autor=AUTORA,
                                                               conn_pacientes=pac, hoy=HOY).linea   # ya había estadio: «actualizado»
