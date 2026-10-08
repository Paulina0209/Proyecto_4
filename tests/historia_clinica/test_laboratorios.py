"""HC-02 — Integración de resultados de laboratorio (tres criterios de aceptación)."""

from datetime import date, time, timedelta

import pytest

from expediente.repository import laboratorios_de_paciente
from historia_clinica.integracion_externa import importar_bundle_fhir, importar_mensaje_hl7, listar_sincronizaciones
from historia_clinica.laboratorios import (
    ErrorConfiguracionLaboratorio,
    ErrorLaboratorio,
    IdentidadNoCoincideError,
    alertas_activas,
    alertas_de_paciente,
    cargar_rangos_criticos,
    conflictos_de_paciente,
    conflictos_pendientes,
    evaluar_critico,
    marcadores_de_paciente,
    marcar_alerta_revisada,
    nombres_coinciden,
    registrar_resultado_laboratorio,
    resolver_conflicto,
    tendencia_marcador,
    validar_rangos,
)

from .conftest import insertar_paciente

ID = "EXT-1"
NOMBRE = "Paciente de prueba (sintético)"
HOY = date(2026, 3, 10)


def _registrar(conn, paciente_id, prueba="Potasio", valor="4.2", unidad="mmol/L", fecha=HOY, hora=None, **kw):
    datos = dict(identificacion=ID, nombre="Prueba Paciente")
    datos.update(kw)
    return registrar_resultado_laboratorio(
        conn, paciente_id, prueba=prueba, valor=valor, unidad=unidad, fecha=fecha, hora=hora, **datos
    )


def _hl7(obx, identificacion=ID, nombre="Prueba^Paciente", control="MSG1"):
    return "\r".join([
        f"MSH|^~\\&|LIS|HOSP|COPILOTO|ONCO|20260310080000||ORU^R01|{control}|P|2.5",
        f"PID|1||{identificacion}^^^HOSP||{nombre}||19700101|F",
        "OBR|1|||BMP^Química|||20260310073000",
        *obx,
    ])


@pytest.fixture
def paciente(conn):
    return insertar_paciente(conn, identificacion=ID, nombre=NOMBRE)


# --- AC1: asociado al paciente correcto y a su fecha -----------------------


def test_registro_manual_queda_en_el_expediente_con_su_fecha(conn, paciente):
    r = _registrar(conn, paciente, fecha=HOY, hora=time(7, 45))

    lab = laboratorios_de_paciente(conn, paciente)[0]
    assert (lab.id, lab.paciente_id, lab.fecha, lab.prueba, lab.valor) == (r.laboratorio_id, paciente, "2026-03-10", "Potasio", "4.2")
    recepcion = conn.execute("SELECT * FROM recepcion_laboratorio WHERE laboratorio_id = ?", (r.laboratorio_id,)).fetchone()
    assert (recepcion["fecha_hora"], recepcion["origen"]) == ("2026-03-10T07:45", "manual")


def test_hl7_queda_asociado_al_paciente_y_a_la_hora_de_la_toma(conn, paciente):
    mensaje = _hl7(["OBX|1|NM|2823-3^Potasio||4.1|mmol/L|3.5-5.1|N|||F|||20260310074500"])

    resultado = importar_mensaje_hl7(conn, paciente, mensaje, "LIS")

    assert resultado.exito
    lab = laboratorios_de_paciente(conn, paciente)[0]
    assert lab.fecha == "2026-03-10"
    fila = conn.execute("SELECT fecha_hora, origen FROM recepcion_laboratorio WHERE laboratorio_id = ?", (lab.id,)).fetchone()
    assert tuple(fila) == ("2026-03-10T07:45", "hl7v2")


def test_hl7_sin_hora_en_obx_usa_la_del_obr(conn, paciente):
    importar_mensaje_hl7(conn, paciente, _hl7(["OBX|1|NM|2823-3^Potasio||4.1|mmol/L|3.5-5.1|N|||F"]), "LIS")

    assert conn.execute("SELECT fecha_hora FROM recepcion_laboratorio").fetchone()[0] == "2026-03-10T07:30"


def test_doble_validacion_rechaza_un_nombre_distinto_sin_guardar_nada(conn, paciente):
    with pytest.raises(IdentidadNoCoincideError):
        _registrar(conn, paciente, nombre="Gómez María")

    assert laboratorios_de_paciente(conn, paciente) == []


def test_doble_validacion_rechaza_otra_identificacion(conn, paciente):
    with pytest.raises(IdentidadNoCoincideError):
        _registrar(conn, paciente, identificacion="EXT-2")
    assert laboratorios_de_paciente(conn, paciente) == []


def test_hl7_con_el_id_correcto_pero_otro_nombre_se_rechaza_completo(conn, paciente):
    mensaje = _hl7(["OBX|1|NM|2823-3^Potasio||7.2|mmol/L|3.5-5.1|HH|||F"], nombre="Gomez^Maria")

    resultado = importar_mensaje_hl7(conn, paciente, mensaje, "LIS")

    assert not resultado.exito
    assert "no coincide" in resultado.mensaje
    assert laboratorios_de_paciente(conn, paciente) == []
    assert alertas_de_paciente(conn, paciente) == []
    assert listar_sincronizaciones(conn, paciente)[0].estado == "fallida"


def test_hl7_sin_nombre_no_se_importa(conn, paciente):
    resultado = importar_mensaje_hl7(conn, paciente, _hl7(["OBX|1|NM|2823-3^Potasio||4.1|mmol/L||N|||F"], nombre=""), "LIS")

    assert not resultado.exito
    assert laboratorios_de_paciente(conn, paciente) == []


def test_fhir_con_laboratorios_exige_el_nombre(conn, paciente):
    bundle = {
        "resourceType": "Bundle",
        "entry": [
            {"resource": {"resourceType": "Patient", "identifier": [{"value": ID}]}},
            {"resource": {
                "resourceType": "Observation", "id": "o1", "category": [{"coding": [{"code": "laboratory"}]}],
                "code": {"text": "Potasio"}, "effectiveDateTime": "2026-03-10T07:45:00Z",
                "valueQuantity": {"value": 4.0, "unit": "mmol/L"},
            }},
        ],
    }
    assert not importar_bundle_fhir(conn, paciente, bundle, "HIS").exito

    bundle["entry"][0]["resource"]["name"] = [{"text": "Paciente Prueba"}]
    assert importar_bundle_fhir(conn, paciente, bundle, "HIS").exito
    lab_id = laboratorios_de_paciente(conn, paciente)[0].id
    assert conn.execute("SELECT fecha_hora FROM recepcion_laboratorio WHERE laboratorio_id = ?", (lab_id,)).fetchone()[0] == "2026-03-10T07:45"


@pytest.mark.parametrize(
    ("expediente", "recibido", "coincide"),
    [
        ("Juan Carlos Pérez", "PEREZ^JUAN", True),
        ("Juan Carlos Pérez", "Juan Pérez", True),
        ("Juan Carlos Pérez", "Gómez^Juan", False),
        ("Juan Carlos Pérez", "Juan", False),  # una sola palabra no basta
        ("Juan Carlos Pérez", "", False),
    ],
)
def test_comparacion_de_nombres(expediente, recibido, coincide):
    assert nombres_coinciden(expediente, recibido) is coincide


def test_datos_invalidos_no_se_guardan(conn, paciente):
    with pytest.raises(ErrorLaboratorio):
        _registrar(conn, paciente, valor="  ")
    with pytest.raises(ErrorLaboratorio):
        _registrar(conn, paciente, fecha=date.today() + timedelta(days=1))
    with pytest.raises(ErrorLaboratorio):
        _registrar(conn, paciente, rango_referencia="normal")
    assert laboratorios_de_paciente(conn, paciente) == []


# --- AC2: valor crítico -> alerta visible -----------------------------------


@pytest.mark.parametrize(
    ("prueba", "valor", "unidad", "limite"),
    [
        ("Potasio", "7.1", "mmol/L", "> 6.5 mmol/L (crítico alto)"),
        ("K", "2.1", "mEq/L", "< 2.5 mEq/L (crítico bajo)"),
        ("Hemoglobina", "6.2", "g/dL", "< 7 g/dL (crítico bajo)"),
        ("Neutrófilos absolutos", "0.3", "10^3/µL", "< 0.5 10^3/µL (crítico bajo)"),
    ],
)
def test_valor_critico_genera_alerta(conn, paciente, prueba, valor, unidad, limite):
    r = _registrar(conn, paciente, prueba=prueba, valor=valor, unidad=unidad)

    assert r.alerta is not None
    assert r.alerta.limite_superado == limite
    assert [a.laboratorio_id for a in alertas_activas(conn, paciente)] == [r.laboratorio_id]


def test_valor_normal_o_solo_fuera_de_rango_no_genera_alerta(conn, paciente):
    r = _registrar(conn, paciente, valor="5.4", rango_referencia="3.5-5.1")  # alterado, pero no crítico

    assert r.alerta is None
    assert laboratorios_de_paciente(conn, paciente)[0].alterado is True


@pytest.mark.parametrize(
    ("prueba", "valor", "unidad"),
    [
        ("Potasio", "7.1", "mg/dL"),  # otra unidad: no se convierte ni se evalúa
        ("CEA", "250", "ng/ml"),  # marcador tumoral: sin rango crítico
        ("Hemoglobina glicosilada", "4", "g/dL"),  # alias exacto, no parcial
        ("Potasio", "hemolizada", "mmol/L"),  # no numérico
    ],
)
def test_sin_rango_aplicable_no_se_genera_alerta(conn, paciente, prueba, valor, unidad):
    assert _registrar(conn, paciente, prueba=prueba, valor=valor, unidad=unidad).alerta is None


def test_hl7_con_valor_critico_genera_alerta_en_la_misma_importacion(conn, paciente):
    importar_mensaje_hl7(conn, paciente, _hl7(["OBX|1|NM|777-3^Plaquetas||12|10\\S\\3/uL|150-450|LL|||F"]), "LIS")

    (alerta,) = alertas_activas(conn, paciente)
    assert (alerta.prueba, alerta.valor) == ("Plaquetas", "12")


def test_la_alerta_sigue_activa_hasta_que_se_revisa(conn, paciente):
    r = _registrar(conn, paciente, valor="7.1")

    revisada = marcar_alerta_revisada(conn, paciente, r.alerta.id, "dra.ruiz")

    assert (revisada.estado, revisada.revisada_por) == ("revisada", "dra.ruiz")
    assert alertas_activas(conn, paciente) == []
    assert len(alertas_de_paciente(conn, paciente)) == 1  # la constancia queda


def test_no_se_revisa_una_alerta_de_otro_paciente(conn, paciente):
    otro = insertar_paciente(conn, identificacion="EXT-9", nombre="Otra Persona Distinta")
    r = _registrar(conn, paciente, valor="7.1")

    with pytest.raises(ErrorLaboratorio):
        marcar_alerta_revisada(conn, otro, r.alerta.id, "dra.ruiz")


# --- AC3: mismo marcador y mismo momento con valores distintos --------------


def test_mismo_momento_y_valor_distinto_marca_conflicto_sin_sobrescribir(conn, paciente):
    a = _registrar(conn, paciente, valor="4.2", hora=time(7, 30))
    b = _registrar(conn, paciente, prueba="K", valor="5.9", hora=time(7, 30))

    assert {l.valor for l in laboratorios_de_paciente(conn, paciente)} == {"4.2", "5.9"}
    (conflicto,) = conflictos_pendientes(conn, paciente)
    assert {conflicto.laboratorio_a_id, conflicto.laboratorio_b_id} == {a.laboratorio_id, b.laboratorio_id}
    assert conflicto.prueba_normalizada == "potasio"
    assert b.conflictos and b.conflictos[0].id == conflicto.id


def test_mismo_valor_no_es_conflicto(conn, paciente):
    _registrar(conn, paciente, valor="4.2", hora=time(7, 30))
    _registrar(conn, paciente, valor="4.20", hora=time(7, 30))

    assert conflictos_pendientes(conn, paciente) == []


def test_horas_distintas_no_son_conflicto(conn, paciente):
    _registrar(conn, paciente, valor="4.2", hora=time(7, 30))
    _registrar(conn, paciente, valor="5.0", hora=time(18, 0))

    assert conflictos_pendientes(conn, paciente) == []


def test_sin_hora_se_compara_por_dia(conn, paciente):
    _registrar(conn, paciente, valor="4.2", hora=time(7, 30))
    _registrar(conn, paciente, valor="5.0")  # sin hora: no se puede descartar

    assert len(conflictos_pendientes(conn, paciente)) == 1


def test_conflicto_entre_dos_mensajes_hl7(conn, paciente):
    importar_mensaje_hl7(conn, paciente, _hl7(["OBX|1|NM|2823-3^Potasio||4.1|mmol/L|||||F|||20260310074500"], control="A"), "LIS")
    importar_mensaje_hl7(conn, paciente, _hl7(["OBX|1|NM|2823-3^Potasio||6.0|mmol/L|||||F|||20260310074500"], control="B"), "LIS")

    assert len(conflictos_pendientes(conn, paciente)) == 1
    assert len(laboratorios_de_paciente(conn, paciente)) == 2


def test_resolver_conflicto_conserva_ambos_resultados(conn, paciente):
    _registrar(conn, paciente, valor="4.2", hora=time(7, 30))
    _registrar(conn, paciente, valor="5.9", hora=time(7, 30))
    (conflicto,) = conflictos_pendientes(conn, paciente)

    resuelto = resolver_conflicto(conn, paciente, conflicto.id, "valido_a", "dra.ruiz", "La B estaba hemolizada.")

    assert (resuelto.estado, resuelto.resolucion, resuelto.nota) == ("resuelto", "valido_a", "La B estaba hemolizada.")
    assert conflictos_pendientes(conn, paciente) == []
    assert len(laboratorios_de_paciente(conn, paciente)) == 2
    with pytest.raises(ErrorLaboratorio):
        resolver_conflicto(conn, paciente, conflicto.id, "valido_b", "dra.ruiz")


def test_resolucion_invalida_se_rechaza(conn, paciente):
    _registrar(conn, paciente, valor="4.2", hora=time(7, 30))
    _registrar(conn, paciente, valor="5.9", hora=time(7, 30))
    (conflicto,) = conflictos_pendientes(conn, paciente)

    with pytest.raises(ErrorLaboratorio):
        resolver_conflicto(conn, paciente, conflicto.id, "borrar_b", "dra.ruiz")
    assert conflictos_de_paciente(conn, paciente)[0].estado == "pendiente"


# --- Tendencias -------------------------------------------------------------


def test_tendencia_ordenada_y_con_marcas(conn, paciente):
    _registrar(conn, paciente, prueba="CEA", valor="3.1", unidad="ng/ml", fecha=HOY - timedelta(days=60))
    _registrar(conn, paciente, prueba="CEA", valor="7.8", unidad="ng/ml", fecha=HOY - timedelta(days=30), rango_referencia="0-5.0")
    _registrar(conn, paciente, prueba="Potasio", valor="7.1")

    tendencia = tendencia_marcador(conn, paciente, "cea")

    (serie,) = tendencia.series
    assert [p.valor_numerico for p in serie.puntos] == [3.1, 7.8]
    assert [p.alterado for p in serie.puntos] == [False, True]
    assert tendencia.advertencias == ()
    potasio = tendencia_marcador(conn, paciente, "K").series[0].puntos[0]
    assert potasio.critico is True


def test_tendencia_agrupa_alias_y_separa_unidades(conn, paciente):
    _registrar(conn, paciente, prueba="Hemoglobina", valor="11", unidad="g/dL", fecha=HOY - timedelta(days=10))
    _registrar(conn, paciente, prueba="Hb", valor="12", unidad="g/dL", fecha=HOY - timedelta(days=5))
    _registrar(conn, paciente, prueba="HGB", valor="120", unidad="g/L")

    tendencia = tendencia_marcador(conn, paciente, "hemoglobina")

    assert tendencia.prueba == "Hemoglobina"
    assert [(s.unidad, len(s.puntos)) for s in tendencia.series] == [("g/dL", 2), ("g/L", 1)]
    assert "unidades distintas" in tendencia.advertencias[0]


def test_tendencia_avisa_si_hay_conflictos(conn, paciente):
    _registrar(conn, paciente, valor="4.2", hora=time(7, 30))
    _registrar(conn, paciente, valor="5.9", hora=time(7, 30))

    tendencia = tendencia_marcador(conn, paciente, "potasio")

    assert all(p.en_conflicto for p in tendencia.series[0].puntos)
    assert any("conflicto" in a for a in tendencia.advertencias)


def test_lista_de_marcadores(conn, paciente):
    _registrar(conn, paciente, prueba="CEA", valor="3.1", unidad="ng/ml", fecha=HOY - timedelta(days=60))
    _registrar(conn, paciente, prueba="CEA", valor="7.8", unidad="ng/ml", fecha=HOY - timedelta(days=30))
    _registrar(conn, paciente, prueba="K", valor="4.0")

    marcadores = marcadores_de_paciente(conn, paciente)

    assert [(m.prueba, m.cantidad, m.ultimo_valor) for m in marcadores] == [("Potasio", 1, "4.0"), ("CEA", 2, "7.8")]


def test_paciente_sin_resultados_tiene_tendencia_vacia(conn, paciente):
    assert tendencia_marcador(conn, paciente, "CEA").vacia
    assert marcadores_de_paciente(conn, paciente) == []


# --- Configuración ------------------------------------------------------------


def test_el_yaml_incluido_es_valido():
    rangos = cargar_rangos_criticos()
    assert {"potasio", "hemoglobina", "plaquetas", "neutrofilos"} <= set(rangos)


@pytest.mark.parametrize(
    "datos",
    [
        {},
        {"pruebas": {"k": {"nombre": "K", "alias": ["k"], "unidades": ["mmol/L"]}}},  # sin límites
        {"pruebas": {"k": {"nombre": "K", "alias": ["k"], "unidades": ["mmol/L"], "critico_bajo": 7, "critico_alto": 2}}},
        {"pruebas": {"k": {"nombre": "K", "alias": [], "unidades": ["mmol/L"], "critico_alto": 6}}},
        {"pruebas": {
            "a": {"nombre": "A", "alias": ["x"], "unidades": ["u"], "critico_alto": 1},
            "b": {"nombre": "B", "alias": ["x"], "unidades": ["u"], "critico_alto": 1},
        }},  # alias repetido
    ],
)
def test_configuracion_invalida_se_rechaza(datos):
    with pytest.raises(ErrorConfiguracionLaboratorio):
        validar_rangos(datos)


def test_evaluacion_con_rangos_propios_de_la_institucion():
    rangos = validar_rangos({"pruebas": {"k": {"nombre": "K", "alias": ["potasio"], "unidades": ["mmol/L"], "critico_alto": 6.0}}})
    assert evaluar_critico("Potasio", "6.2", "mmol/L", rangos) == "> 6 mmol/L (crítico alto)"


# --- Atomicidad -----------------------------------------------------------------


def test_si_falla_el_procesamiento_no_queda_el_resultado(conn, paciente, monkeypatch):
    import historia_clinica.laboratorios as modulo

    def falla(*args, **kwargs):
        raise RuntimeError("fallo simulado")

    monkeypatch.setattr(modulo, "procesar_resultados", falla)
    with pytest.raises(RuntimeError):
        _registrar(conn, paciente, valor="7.1")
    assert laboratorios_de_paciente(conn, paciente) == []
    assert conn.execute("SELECT COUNT(*) FROM recepcion_laboratorio").fetchone()[0] == 0
