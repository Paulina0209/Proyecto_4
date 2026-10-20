"""CFG-02: preferencias de notificación del oncólogo y su bandeja (datos sintéticos)."""
from __future__ import annotations

from datetime import date

import pytest

from configuracion import notificaciones as cfg02
from historia_clinica import laboratorios as hc02
from historia_clinica.db import crear_conexion
from patients import db as pdb
from patients.expediente import paciente_en_expediente

ONCO, OTRO = 1, 2


@pytest.fixture
def bases():
    conn = pdb.conectar(":memory:")
    pdb.inicializar(conn)
    for pid, nombre, doc, onco in ((1, "Ana Sintética", "111", ONCO), (2, "Beto Sintético", "222", ONCO), (3, "Caro Ajena", "333", OTRO)):
        conn.execute("INSERT INTO pacientes (id, nombre_completo, sexo, tipo_identificacion, numero_identificacion, oncologo_id, fecha_registro) "
                     "VALUES (?, ?, 'otro', 'cedula', ?, ?, '2026-01-01')", (pid, nombre, doc, onco))
    alertas = ((1, "estudio_pendiente", "media", "Ecocardiograma pendiente", "2026-03-01", 0),
               (2, "interaccion", "alta", "Warfarina y capecitabina", "2026-03-02", 0),
               (2, "interaccion", "media", "Ya resuelta", "2026-02-01", 1),
               (3, "interaccion", "alta", "De otro oncólogo", "2026-03-03", 0))
    conn.executemany("INSERT INTO alertas (paciente_id, tipo, severidad, descripcion, fecha, resuelta) VALUES (?, ?, ?, ?, ?, ?)", alertas)
    conn.commit()
    conn_exp = crear_conexion(":memory:")
    yield conn, conn_exp
    conn_exp.close()
    conn.close()


def _potasio_critico(conn, conn_exp, paciente_id=1, doc="111", nombre="Ana Sintética"):
    exp = paciente_en_expediente(conn, conn_exp, paciente_id, crear=True)
    r = hc02.registrar_resultado_laboratorio(conn_exp, exp, identificacion=doc, nombre=nombre, prueba="Potasio", valor="7.2",
                                             unidad="mmol/L", fecha=date(2026, 3, 4), rango_referencia="3.5-5.1")
    return exp, r.alerta


def test_por_defecto_todo_avisa_en_la_aplicacion(bases):
    conn, _ = bases
    config = cfg02.obtener_preferencias(conn, ONCO)
    assert {p.evento: (p.activo, p.canales) for p in config.preferencias} == {
        e: (True, ("en_aplicacion",)) for e in ("resultado_critico", "estudio_pendiente", "interaccion_detectada")}
    assert config.a_dict()["es_por_defecto"] is True


def test_la_bandeja_reune_criticos_estudios_e_interacciones_de_mis_pacientes(bases):
    conn, conn_exp = bases
    _, alerta = _potasio_critico(conn, conn_exp)

    bandeja = cfg02.notificaciones_de(conn, conn_exp, ONCO)

    assert [(n.id, n.evento, n.paciente) for n in bandeja] == [
        (f"lab-{alerta.id}", "resultado_critico", "Ana Sintética"),
        ("alerta-2", "interaccion_detectada", "Beto Sintético"),
        ("alerta-1", "estudio_pendiente", "Ana Sintética"),
    ]
    assert "Potasio 7.2 mmol/L" in bandeja[0].mensaje
    assert all("De otro oncólogo" != n.mensaje and "Ya resuelta" != n.mensaje for n in bandeja)


def test_un_evento_desactivado_o_sin_canal_en_la_aplicacion_no_llega_a_la_bandeja(bases):
    conn, conn_exp = bases
    _potasio_critico(conn, conn_exp)

    cfg02.guardar_preferencias(conn, ONCO, [{"evento": "estudio_pendiente", "activo": False, "canales": []},
                                            {"evento": "resultado_critico", "activo": False, "canales": ["en_aplicacion"]}])

    assert [n.evento for n in cfg02.notificaciones_de(conn, conn_exp, ONCO)] == ["interaccion_detectada"]
    assert len(cfg02.notificaciones_de(conn, conn_exp, OTRO)) == 1        # las preferencias son de cada quien


def test_guardar_es_todo_o_nada_y_explica_que_falla(bases):
    conn, _ = bases
    with pytest.raises(cfg02.ErrorPreferencias) as exc:
        cfg02.guardar_preferencias(conn, ONCO, [{"evento": "estudio_pendiente", "activo": False, "canales": []},
                                                {"evento": "resultado_critico", "activo": True, "canales": []},
                                                {"evento": "interaccion_detectada", "canales": ["paloma"]},
                                                {"evento": "inventado", "canales": ["en_aplicacion"]}])
    campos = [c for c, _m in exc.value.errores]
    assert campos == ["canales.resultado_critico", "canales.interaccion_detectada", "evento"]
    assert cfg02.obtener_preferencias(conn, ONCO).a_dict()["es_por_defecto"] is True   # no se guardó nada


def test_los_eventos_que_no_se_envian_quedan_como_estaban(bases):
    conn, _ = bases
    cfg02.guardar_preferencias(conn, ONCO, [{"evento": "interaccion_detectada", "activo": False, "canales": ["en_aplicacion"]}])
    cfg02.guardar_preferencias(conn, ONCO, [{"evento": "estudio_pendiente", "activo": False, "canales": []}])

    config = cfg02.obtener_preferencias(conn, ONCO)
    assert not config.de("interaccion_detectada").activo
    assert not config.de("estudio_pendiente").activo
    assert config.actualizado_en is not None


def test_marcar_como_leida_no_resuelve_el_origen_y_es_solo_de_quien_lee(bases):
    conn, conn_exp = bases

    leida = cfg02.marcar_leida(conn, conn_exp, ONCO, "alerta-1")
    otra_vez = cfg02.marcar_leida(conn, conn_exp, ONCO, "alerta-1")

    assert leida.leida and otra_vez.leida
    bandeja = cfg02.notificaciones_de(conn, conn_exp, ONCO)
    assert bandeja[-1].id == "alerta-1" and bandeja[-1].leida        # sigue ahí, al final
    assert conn.execute("SELECT resuelta FROM alertas WHERE id = 1").fetchone()[0] == 0
    with pytest.raises(cfg02.NotificacionNoEncontrada):
        cfg02.marcar_leida(conn, conn_exp, OTRO, "alerta-1")         # no es de su bandeja


def test_la_alerta_critica_revisada_sale_de_la_bandeja(bases):
    conn, conn_exp = bases
    exp, alerta = _potasio_critico(conn, conn_exp)

    hc02.marcar_alerta_revisada(conn_exp, exp, alerta.id, "dra.prueba")

    assert all(n.evento != "resultado_critico" for n in cfg02.notificaciones_de(conn, conn_exp, ONCO))


def test_sin_expediente_la_bandeja_funciona_igual(bases):
    conn, _ = bases
    assert [n.id for n in cfg02.notificaciones_de(conn, None, ONCO)] == ["alerta-2", "alerta-1"]
    assert cfg02.notificaciones_de(conn, None, 99) == []


# --- Casos que la historia no escribe, pero que hay que cubrir ----------------


def test_canales_repetidos_se_guardan_una_vez_y_desactivar_conserva_los_elegidos(bases):
    conn, _ = bases
    cfg02.guardar_preferencias(conn, ONCO, [{"evento": "interaccion_detectada", "activo": True,
                                             "canales": ["en_aplicacion", "en_aplicacion"]}])
    assert cfg02.obtener_preferencias(conn, ONCO).de("interaccion_detectada").canales == ("en_aplicacion",)

    cfg02.guardar_preferencias(conn, ONCO, [{"evento": "interaccion_detectada", "activo": False, "canales": ["en_aplicacion"]}])

    pref = cfg02.obtener_preferencias(conn, ONCO).de("interaccion_detectada")
    assert (pref.activo, pref.canales) == (False, ("en_aplicacion",))      # al reactivarlo no hay que volver a elegir


def test_sin_preferencias_no_se_guarda_nada(bases):
    conn, _ = bases
    with pytest.raises(cfg02.ErrorPreferencias) as exc:
        cfg02.guardar_preferencias(conn, ONCO, [])
    assert [c for c, _m in exc.value.errores] == ["preferencias"]


def test_el_correo_ya_no_es_un_canal_y_lo_guardado_con_el_vuelve_a_la_aplicacion(bases):
    conn, conn_exp = bases
    assert list(cfg02.CANALES) == ["en_aplicacion"]
    with pytest.raises(cfg02.ErrorPreferencias):
        cfg02.guardar_preferencias(conn, ONCO, [{"evento": "estudio_pendiente", "activo": True, "canales": ["correo"]}])

    conn.execute("INSERT INTO preferencias_notificacion (usuario_id, evento, activo, canales, actualizado_en) "
                 "VALUES (?, 'estudio_pendiente', 1, 'correo', '2026-01-01T00:00:00+00:00')", (ONCO,))
    assert cfg02.obtener_preferencias(conn, ONCO).de("estudio_pendiente").canales == ("en_aplicacion",)
    assert "estudio_pendiente" in {n.evento for n in cfg02.notificaciones_de(conn, conn_exp, ONCO)}


def test_desactivar_y_volver_a_activar_trae_las_mismas_notificaciones_con_su_estado_de_lectura(bases):
    conn, conn_exp = bases
    cfg02.marcar_leida(conn, conn_exp, ONCO, "alerta-1")
    cfg02.guardar_preferencias(conn, ONCO, [{"evento": "estudio_pendiente", "activo": False, "canales": []}])
    assert all(n.id != "alerta-1" for n in cfg02.notificaciones_de(conn, conn_exp, ONCO))
    with pytest.raises(cfg02.NotificacionNoEncontrada):
        cfg02.marcar_leida(conn, conn_exp, ONCO, "alerta-1")        # oculta: no se puede marcar

    cfg02.guardar_preferencias(conn, ONCO, [{"evento": "estudio_pendiente", "activo": True, "canales": ["en_aplicacion"]}])

    vuelta = next(n for n in cfg02.notificaciones_de(conn, conn_exp, ONCO) if n.id == "alerta-1")
    assert vuelta.leida


def test_alertas_de_tipos_que_no_son_eventos_no_aparecen(bases):
    conn, conn_exp = bases
    conn.execute("INSERT INTO alertas (paciente_id, tipo, severidad, descripcion, fecha) VALUES (1, 'alergia', 'alta', 'Alergia a penicilina', '2026-03-05')")
    conn.commit()
    assert all("penicilina" not in n.mensaje for n in cfg02.notificaciones_de(conn, conn_exp, ONCO))


def test_el_critico_de_un_paciente_ajeno_va_solo_a_la_bandeja_de_su_oncologo(bases):
    conn, conn_exp = bases
    _, alerta = _potasio_critico(conn, conn_exp, paciente_id=3, doc="333", nombre="Caro Ajena")

    assert all(n.evento != "resultado_critico" for n in cfg02.notificaciones_de(conn, conn_exp, ONCO))
    ajena = [n for n in cfg02.notificaciones_de(conn, conn_exp, OTRO) if n.evento == "resultado_critico"]
    assert [(n.id, n.paciente_id) for n in ajena] == [(f"lab-{alerta.id}", 3)]


def test_lo_leido_es_de_cada_usuario(bases):
    conn, conn_exp = bases
    cfg02.marcar_leida(conn, conn_exp, ONCO, "alerta-1", usuario_id=50)     # p. ej. alguien que revisa la bandeja de ONCO

    assert not next(n for n in cfg02.notificaciones_de(conn, conn_exp, ONCO) if n.id == "alerta-1").leida
    assert next(n for n in cfg02.notificaciones_de(conn, conn_exp, ONCO, usuario_id=50) if n.id == "alerta-1").leida


def test_orden_mas_grave_primero_y_a_igual_gravedad_la_mas_reciente(bases):
    conn, conn_exp = bases
    conn.executemany("INSERT INTO alertas (paciente_id, tipo, severidad, descripcion, fecha) VALUES (?, ?, ?, ?, ?)",
                     ((1, "interaccion", "alta", "Más reciente", "2026-03-09"), (1, "estudio_pendiente", "baja", "Leve", "2026-03-10")))
    conn.commit()
    _potasio_critico(conn, conn_exp)

    bandeja = cfg02.notificaciones_de(conn, conn_exp, ONCO)

    assert [n.severidad for n in bandeja] == ["critica", "alta", "alta", "media", "baja"]
    assert [n.mensaje for n in bandeja if n.severidad == "alta"] == ["Más reciente", "Warfarina y capecitabina"]


def test_las_preferencias_sobreviven_a_cerrar_y_abrir_la_base(tmp_path):
    ruta = tmp_path / "pacientes.db"
    conn = pdb.conectar(ruta)
    pdb.inicializar(conn)
    cfg02.guardar_preferencias(conn, ONCO, [{"evento": "resultado_critico", "activo": True, "canales": ["en_aplicacion"]}])
    conn.close()

    conn = pdb.conectar(ruta)
    try:
        assert cfg02.obtener_preferencias(conn, ONCO).de("resultado_critico").canales == ("en_aplicacion",)
    finally:
        conn.close()
