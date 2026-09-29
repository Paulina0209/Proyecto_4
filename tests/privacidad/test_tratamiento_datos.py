"""NFR-06 — Cumplimiento de datos personales y gestión de derechos (cinco AC)."""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from auditoria.models import TipoAccion
from auditoria.registro_acceso import obtener_eventos_de_paciente, obtener_eventos_de_usuario
from historia_clinica.db import crear_conexion as crear_conexion_expediente
from historia_clinica_mock.seed import sembrar_datos_sinteticos
from privacidad.models import EstadoAutorizacion, EstadoSolicitud, Finalidad
from privacidad.tratamiento_datos import (
    actualizar_solicitud,
    configurar_politica,
    crear_conexion,
    estado_autorizacion,
    historial_politica,
    obtener_solicitud,
    politica_de_autorizacion,
    politica_vigente,
    politicas_vigentes,
    recopilar_informacion_titular,
    registrar_autorizacion,
    registrar_solicitud_derechos,
    solicitudes_abiertas,
    verificar_tratamiento_permitido,
)

ADMIN = 1
OPERADOR = 2
PACIENTE = 1
T0 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)

FINALIDADES = (
    Finalidad("atencion_clinica", "Prestación del servicio de salud y seguimiento oncológico", False),
    Finalidad("investigacion", "Uso de datos seudonimizados en estudios de investigación", True),
    Finalidad("recordatorios", "Envío de recordatorios de citas por mensaje de texto", True),
)


@pytest.fixture
def conn():
    connection = crear_conexion()
    yield connection
    connection.close()


def _politica(conn, codigo="co-pacientes", jurisdiccion="Colombia", **cambios):
    datos = dict(
        codigo=codigo,
        jurisdiccion=jurisdiccion,
        nombre="Política de tratamiento de datos de pacientes",
        marco_normativo="Referencia definida por la institución",
        finalidades=FINALIDADES,
        bases_legales=("autorizacion_titular", "prestacion_servicio_salud"),
        derechos=("acceso", "rectificacion", "supresion", "revocacion"),
        plazo_respuesta_dias=15,
        ahora=T0,
    )
    datos.update(cambios)
    resultado = configurar_politica(conn, ADMIN, **datos)
    assert resultado.exito, resultado.motivo_rechazo
    return resultado.registro


def _autorizar(conn, finalidad="investigacion", **cambios):
    datos = dict(
        paciente_id=PACIENTE,
        codigo_politica="co-pacientes",
        finalidad=finalidad,
        base_legal="autorizacion_titular",
        medio="escrito",
        evidencia_ref="documento-42",
        ahora=T0,
    )
    datos.update(cambios)
    return registrar_autorizacion(conn, OPERADOR, **datos)


# --- AC1: la institución configura sus políticas y normas aplicables ---


def test_configurar_politica_por_jurisdiccion(conn):
    politica = _politica(conn)

    assert politica.version == 1
    assert politica.jurisdiccion == "Colombia"
    assert politica.marco_normativo == "Referencia definida por la institución"
    assert politica.finalidad("investigacion").requiere_autorizacion
    assert politica_vigente(conn, "co-pacientes") == politica


def test_varias_jurisdicciones_conviven(conn):
    _politica(conn)
    _politica(conn, codigo="eu-pacientes", jurisdiccion="Unión Europea", plazo_respuesta_dias=30,
              derechos=("acceso", "rectificacion", "supresion", "portabilidad", "oposicion"))

    assert [p.codigo for p in politicas_vigentes(conn)] == ["co-pacientes", "eu-pacientes"]
    europea = politicas_vigentes(conn, jurisdiccion="unión europea")
    assert [p.codigo for p in europea] == ["eu-pacientes"]
    assert "portabilidad" in europea[0].derechos


def test_reconfigurar_crea_una_version_nueva_sin_perder_la_anterior(conn):
    _politica(conn)
    _politica(conn, plazo_respuesta_dias=10)

    historial = historial_politica(conn, "co-pacientes")
    assert [p.version for p in historial] == [2, 1]
    assert politica_vigente(conn, "co-pacientes").plazo_respuesta_dias == 10


@pytest.mark.parametrize(
    "cambio",
    [
        {"codigo": "Con Espacios"},
        {"jurisdiccion": " "},
        {"finalidades": ()},
        {"finalidades": (Finalidad("x", "a"), Finalidad("x", "b"))},
        {"bases_legales": ()},
        {"derechos": ()},
        {"plazo_respuesta_dias": 0},
    ],
)
def test_politica_invalida_se_rechaza(conn, cambio):
    datos = dict(
        codigo="co", jurisdiccion="CO", nombre="P", finalidades=FINALIDADES,
        bases_legales=("b",), derechos=("acceso",), plazo_respuesta_dias=15,
    )
    datos.update(cambio)

    resultado = configurar_politica(conn, ADMIN, **datos)

    assert not resultado.exito
    assert politicas_vigentes(conn) == ()


def test_las_politicas_no_se_pueden_editar_ni_borrar(conn):
    _politica(conn)
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE politicas_tratamiento SET plazo_respuesta_dias = 99")
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("DELETE FROM politicas_tratamiento")


# --- AC2: la autorización queda con evidencia de existencia y estado ---


def test_autorizacion_registrada_conserva_evidencia_y_estado(conn):
    _politica(conn)

    resultado = _autorizar(conn)

    assert resultado.exito
    vigente = estado_autorizacion(conn, PACIENTE, "co-pacientes", "investigacion")
    assert vigente.estado is EstadoAutorizacion.OTORGADA
    assert (vigente.medio, vigente.evidencia_ref) == ("escrito", "documento-42")
    assert vigente.registrado_por == OPERADOR


def test_politica_que_exige_soporte_rechaza_autorizacion_sin_evidencia(conn):
    _politica(conn)

    resultado = _autorizar(conn, evidencia_ref=None)

    assert not resultado.exito
    assert "evidencia" in resultado.motivo_rechazo


def test_politica_sin_exigencia_de_soporte_acepta_autorizacion_sin_evidencia(conn):
    _politica(conn, requiere_evidencia_autorizacion=False)

    assert _autorizar(conn, medio=None, evidencia_ref=None).exito


def test_revocar_deja_nuevo_registro_y_conserva_el_anterior(conn):
    _politica(conn)
    _autorizar(conn)

    revocacion = _autorizar(conn, estado=EstadoAutorizacion.REVOCADA, ahora=T0 + timedelta(days=3))

    assert revocacion.exito
    assert estado_autorizacion(conn, PACIENTE, "co-pacientes", "investigacion").estado is EstadoAutorizacion.REVOCADA
    estados = [
        f["estado"] for f in conn.execute("SELECT estado FROM autorizaciones_tratamiento ORDER BY id").fetchall()
    ]
    assert estados == ["otorgada", "revocada"]


def test_no_se_revoca_lo_que_no_esta_otorgado(conn):
    _politica(conn)

    assert not _autorizar(conn, estado=EstadoAutorizacion.REVOCADA).exito


def test_finalidad_o_base_legal_no_declaradas_se_rechazan(conn):
    _politica(conn)

    assert not _autorizar(conn, finalidad="publicidad").exito
    assert not _autorizar(conn, base_legal="interes_legitimo").exito


def test_verificar_tratamiento_segun_politica(conn):
    _politica(conn)

    assert not verificar_tratamiento_permitido(conn, PACIENTE, "co-pacientes", "investigacion").permitido
    _autorizar(conn)
    assert verificar_tratamiento_permitido(conn, PACIENTE, "co-pacientes", "investigacion").permitido
    _autorizar(conn, estado=EstadoAutorizacion.REVOCADA)
    decision = verificar_tratamiento_permitido(conn, PACIENTE, "co-pacientes", "investigacion")
    assert not decision.permitido and "revocada" in decision.motivo
    # Finalidad que la política ampara sin autorización.
    assert verificar_tratamiento_permitido(conn, PACIENTE, "co-pacientes", "atencion_clinica").permitido
    # Fail-closed.
    assert not verificar_tratamiento_permitido(conn, PACIENTE, "co-pacientes", "publicidad").permitido
    assert not verificar_tratamiento_permitido(conn, PACIENTE, "no-existe", "investigacion").permitido


def test_autorizaciones_no_se_pueden_editar(conn):
    _politica(conn)
    _autorizar(conn)
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE autorizaciones_tratamiento SET estado = 'otorgada'")


# --- AC3: se identifica la finalidad de lo registrado ---


def test_finalidad_identificable_con_la_version_de_politica_vigente_entonces(conn):
    _politica(conn)
    autorizacion = _autorizar(conn).registro
    _politica(
        conn,
        finalidades=(Finalidad("investigacion", "Descripción nueva, posterior a la autorización", True),),
    )

    politica = politica_de_autorizacion(conn, autorizacion)

    assert autorizacion.finalidad == "investigacion"
    assert politica.version == 1
    assert politica.finalidad("investigacion").descripcion.startswith("Uso de datos seudonimizados")
    assert autorizacion.base_legal == "autorizacion_titular"


# --- AC4: solicitudes de derechos -> identificar y recuperar la información ---


def test_solicitud_de_derechos_con_plazo_de_la_politica(conn):
    _politica(conn)

    resultado = registrar_solicitud_derechos(
        conn, OPERADOR, paciente_id=PACIENTE, codigo_politica="co-pacientes", tipo_derecho="acceso",
        descripcion="Solicita copia de sus datos", solicitante="Titular", ahora=T0,
    )

    solicitud = resultado.registro
    assert solicitud.estado is EstadoSolicitud.RECIBIDA
    assert solicitud.fecha_limite == (T0 + timedelta(days=15)).isoformat()
    assert not solicitud.vencida


def test_derecho_no_reconocido_por_la_politica_se_rechaza(conn):
    _politica(conn)

    resultado = registrar_solicitud_derechos(
        conn, OPERADOR, paciente_id=PACIENTE, codigo_politica="co-pacientes", tipo_derecho="portabilidad",
        descripcion="x", solicitante="Titular",
    )

    assert not resultado.exito
    assert "portabilidad" in resultado.motivo_rechazo


def test_ciclo_de_vida_de_la_solicitud(conn):
    _politica(conn)
    solicitud = registrar_solicitud_derechos(
        conn, OPERADOR, paciente_id=PACIENTE, codigo_politica="co-pacientes", tipo_derecho="acceso",
        descripcion="Copia de datos", solicitante="Titular", ahora=T0,
    ).registro

    assert actualizar_solicitud(conn, OPERADOR, solicitud.id, EstadoSolicitud.EN_TRAMITE, ahora=T0).exito
    assert not actualizar_solicitud(conn, OPERADOR, solicitud.id, EstadoSolicitud.ATENDIDA).exito  # sin detalle
    assert actualizar_solicitud(
        conn, OPERADOR, solicitud.id, EstadoSolicitud.ATENDIDA, "Se entregó copia en JSON", ahora=T0
    ).exito
    assert not actualizar_solicitud(conn, OPERADOR, solicitud.id, EstadoSolicitud.EN_TRAMITE).exito  # ya cerrada

    final = obtener_solicitud(conn, solicitud.id)
    assert final.estado is EstadoSolicitud.ATENDIDA
    assert [e.estado for e in final.historial] == [
        EstadoSolicitud.RECIBIDA, EstadoSolicitud.EN_TRAMITE, EstadoSolicitud.ATENDIDA,
    ]


def test_solicitudes_abiertas_marcan_las_vencidas(conn):
    _politica(conn)
    registrar_solicitud_derechos(
        conn, OPERADOR, paciente_id=PACIENTE, codigo_politica="co-pacientes", tipo_derecho="supresion",
        descripcion="Borrar teléfono", solicitante="Titular", ahora=T0,
    )

    abiertas = solicitudes_abiertas(conn, ahora=T0 + timedelta(days=16))

    assert len(abiertas) == 1 and abiertas[0].vencida


def test_recopilar_informacion_del_titular_en_todas_las_fuentes(conn):
    expediente = crear_conexion_expediente()
    ids = sembrar_datos_sinteticos(expediente)
    paciente_id = ids["paciente_maria"]
    _politica(conn)
    _autorizar(conn, paciente_id=paciente_id)
    solicitud = registrar_solicitud_derechos(
        conn, OPERADOR, paciente_id=paciente_id, codigo_politica="co-pacientes", tipo_derecho="acceso",
        descripcion="Copia de datos", solicitante="Titular",
    ).registro

    info = recopilar_informacion_titular(
        conn, OPERADOR, paciente_id, conn_expediente=expediente, solicitud_id=solicitud.id
    )

    assert info.secciones["expediente.pacientes"][0]["identificacion"] == "SINT-0001"
    assert len(info.secciones["expediente.laboratorios"]) == 1
    assert info.secciones["expediente.biomarcadores"][0]["biomarcador"] == "HER2"
    assert len(info.secciones["privacidad.autorizaciones_tratamiento"]) == 1
    assert len(info.secciones["privacidad.solicitudes_derechos"]) == 1
    # Solo datos de este titular: ninguna fila de otro paciente.
    for nombre, filas in info.secciones.items():
        for fila in filas:
            assert fila.get("paciente_id", paciente_id) == paciente_id, nombre
    assert '"identificacion": "SINT-0001"' in info.a_json()


# --- AC5: toda acción de consentimiento/derechos queda en la auditoría ---


def test_cada_operacion_queda_en_la_traza_de_auditoria(conn):
    _politica(conn)
    _autorizar(conn)
    _autorizar(conn, estado=EstadoAutorizacion.REVOCADA)
    solicitud = registrar_solicitud_derechos(
        conn, OPERADOR, paciente_id=PACIENTE, codigo_politica="co-pacientes", tipo_derecho="acceso",
        descripcion="Copia", solicitante="Titular",
    ).registro
    actualizar_solicitud(conn, OPERADOR, solicitud.id, EstadoSolicitud.EN_TRAMITE)
    recopilar_informacion_titular(conn, OPERADOR, PACIENTE, solicitud_id=solicitud.id)

    eventos_admin = obtener_eventos_de_usuario(conn, ADMIN)
    assert [e.accion for e in eventos_admin] == [TipoAccion.CONFIGURAR_POLITICA_DATOS]
    assert eventos_admin[0].paciente_id is None

    eventos = list(reversed(obtener_eventos_de_paciente(conn, PACIENTE)))
    assert [e.accion for e in eventos] == [
        TipoAccion.REGISTRAR_AUTORIZACION,
        TipoAccion.REGISTRAR_AUTORIZACION,
        TipoAccion.GESTIONAR_DERECHOS_TITULAR,
        TipoAccion.GESTIONAR_DERECHOS_TITULAR,
        TipoAccion.GESTIONAR_DERECHOS_TITULAR,
    ]
    assert all(e.usuario_id == OPERADOR for e in eventos)
    assert "otorgada" in eventos[0].detalle and "revocada" in eventos[1].detalle
    assert "en_tramite" in eventos[3].detalle


def test_operacion_rechazada_no_deja_registro_ni_evento(conn):
    _politica(conn)

    _autorizar(conn, finalidad="publicidad")

    assert conn.execute("SELECT COUNT(*) FROM autorizaciones_tratamiento").fetchone()[0] == 0
    assert obtener_eventos_de_paciente(conn, PACIENTE) == ()
