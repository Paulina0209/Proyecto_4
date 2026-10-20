"""Equipo de atención por la pasarela: enfermería ve (sin editar) y consulta las órdenes médicas; admisiones ve datos de
admisión; el oncólogo prescribe. Cada quien, solo con los pacientes de los oncólogos de su equipo."""
import pytest

from tests.frontend.conftest import H, LUCIA, RENATA, iniciar_sesion

CLAVE = "Clave-Admisiones-2026!"


@pytest.fixture()
def ids(entrar):
    """Asigna (como administrador) a enf.mora y a una persona de admisiones nueva al equipo de dra.rios."""
    admin = entrar("admin.demo")
    eq = admin.get("/api/gestion/equipos").json()
    usuarios = {u["nombre_usuario"]: u["id"] for u in admin.get("/api/gestion/usuarios").json()["usuarios"]}
    r = admin.post("/api/gestion/usuarios", json={"nombre_usuario": "adm.prueba", "contrasena": CLAVE, "rol": "administrativo",
                                                  "nombre_completo": "Admisiones de prueba"}, headers=H)
    assert r.status_code == 200, r.text
    usuarios["adm.prueba"] = r.json()["id"]
    rios = next(o["id"] for o in eq["oncologos"] if usuarios["dra.rios"] == o["id"])
    for persona in ("enf.mora", "adm.prueba"):
        r = admin.post(f"/api/gestion/equipos/{usuarios[persona]}", json={"oncologo_id": rios}, headers=H)
        assert r.status_code == 200 and r.json()["oncologos"] == [rios], r.text
    return {**usuarios, "rios": rios}


def _orden(c, paciente=LUCIA, **cambios):
    datos = {"medicamento": "Ondansetrón", "dosis": "8 mg", "via": "VO", "intervalo_horas": 8, "fecha_inicio": "2026-10-20", "hora_inicio": "08:00", **cambios}
    return c.post(f"/api/clinica/pacientes/{paciente}/ordenes", json=datos, headers=H)


def test_la_sesion_de_enfermeria_con_equipo(ids, entrar):
    s = entrar("enf.mora").get("/api/sesion").json()
    assert s["acceso_clinico"] and s["solo_lectura"] and s["ver_ordenes"] and not s["puede_prescribir"] and not s["apoyo_decision"]
    assert not s["puede_registrar"] and [o["id"] for o in s["equipo"]] == [ids["rios"]]


def test_enfermeria_ve_los_pacientes_de_su_equipo_y_no_los_de_otros(ids, entrar):
    c = entrar("enf.mora")
    nombres = [p["id"] for p in c.get("/api/pacientes/buscar").json()["items"]]
    assert LUCIA in nombres and RENATA not in nombres
    assert c.get(f"/api/pacientes/{LUCIA}").status_code == 200
    assert c.get(f"/api/pacientes/{LUCIA}/resumen-360").status_code == 200
    assert c.get(f"/api/pacientes/{RENATA}").status_code == 404                      # no se revela si existe


def test_enfermeria_no_edita_el_expediente_ni_usa_el_apoyo_a_la_decision(ids, entrar):
    c = entrar("enf.mora")
    assert c.post(f"/api/pacientes/{LUCIA}/alertas-laboratorio/1/revisar", json={}, headers=H).status_code == 403
    assert c.post(f"/api/clinica/pacientes/{LUCIA}/consultas-expediente", json={"motivo": "x", "notas": "y"}, headers=H).status_code == 403
    for ruta in ("diagnostico", "estadificacion", "tratamiento", "evidencia?q=x"):
        assert c.get(f"/api/clinica/pacientes/{LUCIA}/{ruta}").status_code == 403, ruta
    assert c.get("/api/notificaciones").status_code == 403                           # la bandeja es del oncólogo
    assert _orden(c).status_code == 403                                               # no prescribe


def test_el_oncologo_prescribe_y_enfermeria_ve_la_orden_y_el_horario(ids, entrar):
    medica = entrar("dra.rios")
    r = _orden(medica, indicaciones="Antes de la quimioterapia")
    assert r.status_code == 200, r.text
    orden = r.json()
    assert orden["activa"] and orden["ordenado_por"].endswith("(dra.rios)")
    c = entrar("enf.mora")
    datos = c.get(f"/api/clinica/pacientes/{LUCIA}/ordenes").json()
    assert [o["id"] for o in datos["ordenes"]] == [orden["id"]] and not datos["puede_prescribir"] and datos["horario"]
    horario = c.get("/api/clinica/enfermeria/horario").json()
    assert horario["pacientes"][0]["id"] == LUCIA and all(d["medicamento"] == "Ondansetrón" for d in horario["dosis"])
    hc = c.get(f"/api/chat/pacientes/{LUCIA}/hc").json()
    assert [o["id"] for o in hc["secciones"]["ordenes"]] == [f"orden-{orden['id']}"]
    assert c.post(f"/api/clinica/pacientes/{LUCIA}/ordenes/{orden['id']}/suspender", json={"motivo": "x"}, headers=H).status_code == 403
    r = entrar("dra.rios").post(f"/api/clinica/pacientes/{LUCIA}/ordenes/{orden['id']}/suspender", json={"motivo": "Náuseas controladas"}, headers=H)
    assert r.status_code == 200 and not r.json()["activa"]


def test_una_orden_incompleta_se_explica_campo_por_campo(ids, entrar):
    r = _orden(entrar("dra.rios"), dosis="", via="XX")
    assert r.status_code == 400 and {"dosis", "via"} <= {e["campo"] for e in r.json()["detail"]["errores"]}


def test_admisiones_ve_datos_de_admision_sin_datos_clinicos(ids, cliente):
    assert iniciar_sesion(cliente, "adm.prueba", CLAVE).status_code == 200
    s = cliente.get("/api/sesion").json()
    assert s["acceso_admision"] and not s["acceso_clinico"] and s["puede_registrar_paciente"] and s["puede_consentimiento"]
    pacientes = cliente.get("/api/clinica/admision/pacientes").json()["pacientes"]
    assert LUCIA in [p["id"] for p in pacientes] and RENATA not in [p["id"] for p in pacientes]
    assert set(pacientes[0]) == {"id", "nombre_completo", "fecha_nacimiento", "sexo", "tipo_identificacion", "numero_identificacion",
                                 "oncologo_id", "consentimiento_ia"}
    assert cliente.get(f"/api/pacientes/{LUCIA}/resumen-360").status_code == 403       # nada clínico
    assert cliente.get(f"/api/clinica/pacientes/{LUCIA}/ordenes").status_code == 403


def test_admisiones_registra_un_paciente_para_el_oncologo_de_su_equipo(ids, cliente):
    assert iniciar_sesion(cliente, "adm.prueba", CLAVE).status_code == 200
    r = cliente.post("/api/pacientes", json={"nombre_completo": "Marta Ruiz Prueba", "fecha_nacimiento": "1970-01-01", "sexo": "femenino",
                                             "tipo_identificacion": "cedula", "numero_identificacion": "55443322",
                                             "contacto": {"telefono": "3001234567", "email": None, "direccion": None},
                                             "antecedentes": {"personales": None, "familiares": None}, "motivo_consulta_inicial": None}, headers=H)
    assert r.status_code in (200, 201), r.text
    assert r.json()["oncologo_id"] == ids["rios"]


def test_sin_equipo_no_ve_pacientes(entrar):
    s = entrar("enf.mora").get("/api/sesion").json()
    assert not s["acceso_clinico"] and "asignado al equipo" in s["mensaje_sin_acceso_clinico"]
    assert entrar("enf.mora").get("/api/clinica/enfermeria/horario").status_code == 403
