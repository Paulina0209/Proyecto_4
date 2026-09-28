"""HC-01 · Registro de paciente: dominio (patients/registro.py) y API."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

import patients.registro as registro_module
from patients.models import AntecedentesMedicos, DatosContacto, Paciente, Sexo, TipoIdentificacion
from patients.registro import (
    buscar_por_id,
    completar_registro,
    generar_identificador_temporal,
    listar_pacientes_de_oncologo,
    registrar_paciente,
    validar_formato_y_longitud,
)


def _paciente_base(**overrides) -> Paciente:
    datos = dict(
        nombre_completo="María Restrepo",
        fecha_nacimiento=date(1975, 3, 12),
        sexo=Sexo.FEMENINO,
        tipo_identificacion=TipoIdentificacion.CEDULA,
        numero_identificacion="43112233",
        contacto=DatosContacto(telefono="3001234567"),
        oncologo_id=1,
    )
    datos.update(overrides)
    return Paciente(**datos)


def _payload(**overrides) -> dict:
    base = {
        "nombre_completo": "Ana Pérez",
        "fecha_nacimiento": "1980-05-10",
        "sexo": "femenino",
        "tipo_identificacion": "cedula",
        "numero_identificacion": "1234567",
        "contacto": {"telefono": "3000000000"},
        "oncologo_id": 1,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# AC1: campos obligatorios completos → registrado y en la lista del oncólogo
# ---------------------------------------------------------------------------

def test_registro_exitoso_con_campos_obligatorios_completos(conn):
    resultado = registrar_paciente(conn, _paciente_base())
    assert resultado.exito
    assert resultado.paciente.id is not None
    assert resultado.errores == []


def test_paciente_registrado_aparece_en_lista_del_oncologo(conn):
    registrar_paciente(conn, _paciente_base(oncologo_id=7))
    pacientes = listar_pacientes_de_oncologo(conn, 7)
    assert len(pacientes) == 1
    assert pacientes[0].nombre_completo == "María Restrepo"


def test_api_paciente_registrado_aparece_en_la_lista(client):
    creado = client.post("/pacientes", json=_payload())
    assert creado.status_code == 201, creado.text

    lista = client.get("/pacientes", params={"oncologo_id": 1}).json()
    assert [p["id"] for p in lista] == [creado.json()["id"]]
    assert client.get("/pacientes", params={"oncologo_id": 2}).json() == []


# ---------------------------------------------------------------------------
# AC2: campo obligatorio vacío → indica cuál falta y no guarda
# ---------------------------------------------------------------------------

def test_campo_obligatorio_vacio_no_guarda_e_indica_cual_falta(conn):
    paciente = _paciente_base(nombre_completo="")
    resultado = registrar_paciente(conn, paciente)
    assert not resultado.exito
    assert "nombre_completo" in {e.campo for e in resultado.errores}
    assert listar_pacientes_de_oncologo(conn, paciente.oncologo_id) == []


def test_sin_telefono_ni_email_no_guarda(conn):
    resultado = registrar_paciente(conn, _paciente_base(contacto=DatosContacto()))
    assert not resultado.exito
    assert any(e.campo == "contacto" for e in resultado.errores)


def test_api_campo_obligatorio_faltante_devuelve_400_con_el_campo(client):
    r = client.post("/pacientes", json=_payload(nombre_completo=""))
    assert r.status_code == 400, r.text
    assert any(e["campo"] == "nombre_completo" for e in r.json()["detail"]["errores"])
    assert client.get("/pacientes", params={"oncologo_id": 1}).json() == []


def test_api_valor_mal_tipado_usa_el_mismo_formato_de_error(client):
    """Un enum o fecha inválidos (validación de FastAPI) responden igual
    que los errores propios: {"detail": {"errores": [{campo, mensaje}]}}."""
    r = client.post("/pacientes", json=_payload(sexo="no_es_un_sexo_valido"))
    assert r.status_code == 400, r.text
    assert any(e["campo"] == "sexo" for e in r.json()["detail"]["errores"])

    r = client.post("/pacientes", json=_payload(fecha_nacimiento="no-es-una-fecha"))
    assert r.status_code == 400, r.text
    assert "errores" in r.json()["detail"]


# ---------------------------------------------------------------------------
# AC3 y regla de negocio: identificación única → alerta de posible duplicado
# ---------------------------------------------------------------------------

def test_identificacion_duplicada_alerta_antes_de_crear(conn):
    registrar_paciente(conn, _paciente_base(numero_identificacion="99999999"))
    resultado = registrar_paciente(
        conn, _paciente_base(numero_identificacion="99999999", nombre_completo="Otra Paciente")
    )
    assert not resultado.exito
    assert resultado.posible_duplicado is not None
    assert resultado.posible_duplicado.numero_identificacion == "99999999"
    assert len(listar_pacientes_de_oncologo(conn, 1)) == 1


def test_corregir_el_numero_tras_la_alerta_si_permite_guardar(conn):
    registrar_paciente(conn, _paciente_base(numero_identificacion="55555555"))
    resultado = registrar_paciente(
        conn, _paciente_base(numero_identificacion="55555556", nombre_completo="Otra Paciente")
    )
    assert resultado.exito
    assert len(listar_pacientes_de_oncologo(conn, 1)) == 2


def test_api_duplicado_del_mismo_oncologo_revela_el_detalle(client):
    client.post("/pacientes", json=_payload(oncologo_id=1))
    r = client.post("/pacientes", json=_payload(oncologo_id=1))
    assert r.status_code == 409
    assert r.json()["detail"]["posible_duplicado"] is not None


def test_api_duplicado_de_otro_oncologo_no_revela_datos(client):
    client.post("/pacientes", json=_payload(oncologo_id=1))
    r = client.post("/pacientes", json=_payload(oncologo_id=2))
    assert r.status_code == 409
    detalle = r.json()["detail"]
    assert detalle.get("posible_duplicado") is None
    assert "nombre_completo" not in str(detalle)
    assert "telefono" not in str(detalle)


def test_api_condicion_de_carrera_se_trata_como_duplicado(client, monkeypatch):
    """La verificación de duplicado no ve al otro paciente (ventana de la
    carrera), pero el INSERT choca con el UNIQUE: debe ser 409, no 500."""
    assert client.post("/pacientes", json=_payload(numero_identificacion="9999999")).status_code == 201

    real_buscar = registro_module.buscar_por_identificacion
    llamadas = {"n": 0}

    def _buscar_simulando_carrera(conn, tipo, numero):
        llamadas["n"] += 1
        return None if llamadas["n"] == 1 else real_buscar(conn, tipo, numero)

    monkeypatch.setattr(registro_module, "buscar_por_identificacion", _buscar_simulando_carrera)

    r = client.post("/pacientes", json=_payload(numero_identificacion="9999999"))
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["posible_duplicado"] is not None


# ---------------------------------------------------------------------------
# Excepción: paciente sin documento → identificador temporal
# ---------------------------------------------------------------------------

def test_paciente_sin_documento_usa_identificador_temporal(conn):
    paciente = _paciente_base(
        tipo_identificacion=TipoIdentificacion.TEMPORAL,
        numero_identificacion=generar_identificador_temporal(),
    )
    resultado = registrar_paciente(conn, paciente)
    assert resultado.exito
    assert resultado.paciente.numero_identificacion.startswith("TEMP-")


def test_temporal_sin_numero_lo_genera_el_registro(conn):
    paciente = _paciente_base(tipo_identificacion=TipoIdentificacion.TEMPORAL, numero_identificacion="")
    resultado = registrar_paciente(conn, paciente)
    assert resultado.exito
    assert resultado.paciente.numero_identificacion.startswith("TEMP-")


def test_dos_identificadores_temporales_distintos_no_chocan(conn):
    for nombre in ("Un Paciente", "Otro Paciente"):
        paciente = _paciente_base(
            nombre_completo=nombre, tipo_identificacion=TipoIdentificacion.TEMPORAL, numero_identificacion="",
        )
        assert registrar_paciente(conn, paciente).exito


def test_api_temporal_sin_numero_genera_identificador(client):
    r = client.post("/pacientes", json=_payload(tipo_identificacion="temporal", numero_identificacion=None))
    assert r.status_code == 201, r.text
    assert r.json()["numero_identificacion"].startswith("TEMP-")


# ---------------------------------------------------------------------------
# UX: formulario corto con opción de completar después
# ---------------------------------------------------------------------------

def test_registro_corto_sin_antecedentes_ni_motivo_queda_incompleto(conn):
    resultado = registrar_paciente(conn, _paciente_base())
    assert resultado.exito
    assert resultado.paciente.registro_completo is False


def test_registro_con_antecedentes_y_motivo_queda_completo(conn):
    paciente = _paciente_base(
        antecedentes=AntecedentesMedicos(personales="Diabetes tipo 2", familiares="Madre con cáncer de mama"),
        motivo_consulta_inicial="Nódulo palpable en mama izquierda",
    )
    resultado = registrar_paciente(conn, paciente)
    assert resultado.exito
    assert resultado.paciente.registro_completo is True


def test_completar_despues_marca_el_registro_como_completo(conn):
    paciente = registrar_paciente(conn, _paciente_base()).paciente

    parcial = completar_registro(conn, paciente, antecedentes_personales="Hipertensión")
    assert parcial.exito and parcial.paciente.registro_completo is False

    final = completar_registro(conn, parcial.paciente, motivo_consulta_inicial="Masa cervical")
    assert final.exito and final.paciente.registro_completo is True

    guardado = buscar_por_id(conn, paciente.id)
    assert guardado.antecedentes.personales == "Hipertensión"
    assert guardado.motivo_consulta_inicial == "Masa cervical"
    assert guardado.registro_completo is True


def test_api_completar_registro(client):
    pid = client.post("/pacientes", json=_payload()).json()["id"]

    r = client.patch(f"/pacientes/{pid}", params={"oncologo_id": 1}, json={
        "antecedentes": {"personales": "Diabetes tipo 2"},
        "motivo_consulta_inicial": "Nódulo pulmonar",
    })
    assert r.status_code == 200, r.text
    assert r.json()["registro_completo"] is True
    assert r.json()["antecedentes"]["personales"] == "Diabetes tipo 2"


def test_api_completar_registro_valida_longitud_y_propiedad(client):
    pid = client.post("/pacientes", json=_payload()).json()["id"]

    r = client.patch(f"/pacientes/{pid}", params={"oncologo_id": 1}, json={"motivo_consulta_inicial": "x" * 1001})
    assert r.status_code == 400
    assert r.json()["detail"]["errores"][0]["campo"] == "motivo_consulta_inicial"

    r = client.patch(f"/pacientes/{pid}", params={"oncologo_id": 2}, json={"motivo_consulta_inicial": "Otro"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Lectura de un paciente: solo su oncólogo
# ---------------------------------------------------------------------------

def test_api_leer_paciente_propio(client):
    creado = client.post("/pacientes", json=_payload()).json()
    r = client.get(f"/pacientes/{creado['id']}", params={"oncologo_id": 1})
    assert r.status_code == 200
    assert r.json()["id"] == creado["id"]


@pytest.mark.parametrize("oncologo_id,paciente_id", [(999, None), (1, 999999)])
def test_api_leer_paciente_ajeno_o_inexistente_da_404(client, oncologo_id, paciente_id):
    creado = client.post("/pacientes", json=_payload()).json()
    r = client.get(f"/pacientes/{paciente_id or creado['id']}", params={"oncologo_id": oncologo_id})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Validación de formato y longitud
# ---------------------------------------------------------------------------

def _campos_con_error(paciente):
    return {e.campo for e in validar_formato_y_longitud(paciente)}


@pytest.mark.parametrize("nombre", ["Al", "A" * 201, "Maria123"])
def test_nombre_invalido_genera_error(nombre):
    assert "nombre_completo" in _campos_con_error(_paciente_base(nombre_completo=nombre))


def test_nombre_valido_no_genera_error():
    assert "nombre_completo" not in _campos_con_error(_paciente_base())


@pytest.mark.parametrize("fecha", [
    date.today() + timedelta(days=1),
    date.today().replace(year=date.today().year - 130),
])
def test_fecha_nacimiento_futura_o_edad_excesiva_genera_error(fecha):
    assert "fecha_nacimiento" in _campos_con_error(_paciente_base(fecha_nacimiento=fecha))


def test_fecha_nacimiento_valida_no_genera_error():
    assert "fecha_nacimiento" not in _campos_con_error(_paciente_base())


@pytest.mark.parametrize("numero", ["123", "12A34567", "1234567890123456789"])
def test_cedula_con_formato_o_longitud_invalida_genera_error(numero):
    assert "numero_identificacion" in _campos_con_error(_paciente_base(numero_identificacion=numero))


@pytest.mark.parametrize("tipo,numero,valido", [
    (TipoIdentificacion.PASAPORTE, "AB12345", True),
    (TipoIdentificacion.TEMPORAL, "ABC123", False),
    (TipoIdentificacion.TEMPORAL, "TEMP-AB12CD34EF", True),
])
def test_formato_de_identificacion_por_tipo(tipo, numero, valido):
    paciente = _paciente_base(tipo_identificacion=tipo, numero_identificacion=numero)
    assert ("numero_identificacion" not in _campos_con_error(paciente)) is valido


@pytest.mark.parametrize("contacto,campo", [
    (DatosContacto(telefono="abcdefg"), "telefono"),
    (DatosContacto(email="no-es-un-email"), "email"),
    (DatosContacto(telefono="3001234567", direccion="A" * 301), "direccion"),
])
def test_contacto_invalido_genera_error(contacto, campo):
    assert campo in _campos_con_error(_paciente_base(contacto=contacto))


def test_contacto_valido_no_genera_error():
    paciente = _paciente_base(contacto=DatosContacto(telefono="3001234567", email="maria@example.com"))
    assert not {"telefono", "email"} & _campos_con_error(paciente)


def test_antecedentes_y_motivo_muy_largos_generan_error():
    paciente = _paciente_base(
        antecedentes=AntecedentesMedicos(personales="x" * 2001),
        motivo_consulta_inicial="x" * 1001,
    )
    assert {"antecedentes.personales", "motivo_consulta_inicial"} <= _campos_con_error(paciente)


def test_oncologo_id_no_positivo_genera_error():
    assert "oncologo_id" in _campos_con_error(_paciente_base(oncologo_id=-1))
