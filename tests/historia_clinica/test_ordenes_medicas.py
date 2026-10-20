"""Órdenes médicas de medicamentos y su horario de administración."""
import sqlite3
from datetime import date, datetime

import pytest

from historia_clinica import ordenes_medicas as om


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    om.inicializar_esquema(c)
    return c


def _orden(conn, **cambios):
    datos = {"medicamento": "Ondansetrón", "dosis": "8 mg", "via": "VO", "intervalo_horas": 8, "fecha_inicio": "2026-10-20",
             "hora_inicio": "08:00", "ordenado_por": "Dra. Ana Gómez (dra.gomez)", **cambios}
    return om.prescribir(conn, 1, **datos)


def test_prescribir_y_leer_la_orden(conn):
    o = _orden(conn, indicaciones="Antes de la quimioterapia")
    assert o.activa or o.fecha_inicio > date.today().isoformat()
    assert (o.frecuencia, o.via_etiqueta) == ("Cada 8 horas", "Oral")
    assert "Ondansetrón 8 mg, vía oral, cada 8 horas" in o.texto() and "Antes de la quimioterapia" in o.texto()
    assert [x.id for x in om.ordenes_de(conn, 1)] == [o.id] and om.ordenes_de(conn, 2) == []


@pytest.mark.parametrize("cambio,campo", [({"medicamento": ""}, "medicamento"), ({"dosis": "mucho"}, "dosis"), ({"via": "XX"}, "via"),
                                          ({"intervalo_horas": "nunca"}, "intervalo_horas"), ({"hora_inicio": "8am"}, "hora_inicio"),
                                          ({"fecha_inicio": "ayer"}, "fecha_inicio"), ({"fecha_fin": "2026-10-01"}, "fecha_fin")])
def test_una_orden_incompleta_dice_que_falta(conn, cambio, campo):
    with pytest.raises(om.ErrorOrden) as exc:
        _orden(conn, **cambio)
    assert campo in {c for c, _m in exc.value.errores}


def test_horario_cada_8_horas_en_un_dia(conn):
    o = _orden(conn)
    dosis = om.dosis_programadas([o], datetime(2026, 10, 21, 0, 0), datetime(2026, 10, 22, 0, 0))
    assert [d.momento for d in dosis] == ["2026-10-21T00:00", "2026-10-21T08:00", "2026-10-21T16:00"]


def test_ciclo_cada_21_dias_y_dosis_unica(conn):
    pembro = _orden(conn, medicamento="Pembrolizumab", dosis="200 mg", via="IV", intervalo_horas=504, hora_inicio="09:00")
    unica = _orden(conn, medicamento="Filgrastim", dosis="300 mcg", via="SC", intervalo_horas=0, fecha_inicio="2026-10-25", hora_inicio="10:00")
    dosis = om.dosis_programadas([pembro, unica], datetime(2026, 10, 20), datetime(2026, 11, 20))
    assert [(d.medicamento, d.momento) for d in dosis] == [("Pembrolizumab", "2026-10-20T09:00"), ("Filgrastim", "2026-10-25T10:00"),
                                                            ("Pembrolizumab", "2026-11-10T09:00")]


def test_la_fecha_de_fin_corta_el_horario(conn):
    o = _orden(conn, intervalo_horas=24, fecha_fin="2026-10-21")
    dosis = om.dosis_programadas([o], datetime(2026, 10, 20), datetime(2026, 10, 25))
    assert [d.momento[:10] for d in dosis] == ["2026-10-20", "2026-10-21"]


def test_suspender_exige_motivo_no_borra_y_saca_del_horario(conn):
    o = _orden(conn, fecha_inicio=date.today().isoformat())
    with pytest.raises(om.ErrorOrden):
        om.suspender(conn, 1, o.id, suspendida_por="Dra. Gómez", motivo=" ")
    s = om.suspender(conn, 1, o.id, suspendida_por="Dra. Gómez", motivo="Náuseas controladas")
    assert not s.activa and "SUSPENDIDA" in s.texto() and om.ordenes_de(conn, 1)[0].id == o.id
    assert om.horario(conn, [1], desde=datetime.combine(date.today(), datetime.min.time()).replace(hour=23)) == []
    with pytest.raises(om.ErrorOrden):
        om.suspender(conn, 1, o.id, suspendida_por="Dra. Gómez", motivo="otra vez")
    with pytest.raises(om.ErrorOrden):
        om.suspender(conn, 2, o.id, suspendida_por="Dra. Gómez", motivo="no es suyo")
