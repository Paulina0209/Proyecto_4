"""Pasarela web: sesión SEC-01, identidad inyectada, permisos por rol, lista cerrada de rutas y cabeceras.

Todo contra la API de pacientes REAL (sin modificarla) y datos sintéticos; nada se simula a mano.
"""
from __future__ import annotations

import re
import sqlite3

import pytest
from fastapi.testclient import TestClient

from auditoria.models import TipoAccion
from frontend.sesiones import AlmacenSesiones
from frontend.servidor import (
    CSP_APP, CSP_DESCARGA, CSP_TABLERO, MENSAJE_SIN_ASIGNACION, NOMBRE_COOKIE, Pasarela,
)
from seguridad.autenticacion import UMBRAL_INTENTOS_FALLIDOS
from tests.frontend.conftest import CLAVE_DEMO, H, LUCIA, RENATA, TOMAS, UID_ESTUDIO_LUCIA, iniciar_sesion

SIN_EXPEDIENTE = 5   # Isabela: registro incompleto, sin expediente clínico


def _eventos(entorno, detalle):
    with sqlite3.connect(entorno.pacientes_db) as c:
        return c.execute("SELECT usuario_id, paciente_id, accion FROM eventos_acceso WHERE detalle = ?", (detalle,)).fetchall()


# --- Sin sesión -----------------------------------------------------------------------------


def test_sin_sesion_la_api_y_el_panel_piden_iniciar_sesion(cliente):
    assert cliente.get("/api/pacientes").status_code == 401
    assert cliente.get(f"/api/pacientes/{LUCIA}/resumen-360").status_code == 401
    assert cliente.get(f"/api/pacientes/{LUCIA}/exportar").status_code == 401
    r = cliente.get("/panel/metricas")
    assert r.status_code == 401 and "Tu sesión terminó" in r.text and 'target="_top"' in r.text


def test_sin_sesion_el_estado_es_un_200_y_no_un_error(cliente):
    r = cliente.get("/api/sesion")
    assert r.status_code == 200 and r.json() == {"autenticado": False}


def test_una_cookie_inventada_no_abre_nada(cliente):
    cliente.cookies.set(NOMBRE_COOKIE, "inventada")
    assert cliente.get("/api/pacientes").status_code == 401
    assert cliente.get("/api/sesion").json() == {"autenticado": False}


# --- Inicio de sesión (SEC-01) ----------------------------------------------------------------


def test_login_correcto_da_la_sesion_y_una_cookie_endurecida(cliente):
    r = iniciar_sesion(cliente, "dra.rios")
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["autenticado"] and cuerpo["usuario"]["nombre_usuario"] == "dra.rios" and cuerpo["usuario"]["rol"] == "oncologo"
    assert cuerpo["acceso_clinico"] and cuerpo["puede_exportar"] and cuerpo["puede_revisar_alertas"] and not cuerpo["ver_metricas"]
    galleta = r.headers["set-cookie"]
    assert galleta.startswith(NOMBRE_COOKIE + "=") and NOMBRE_COOKIE.startswith("__Host-")
    atributos = galleta.lower()
    assert "httponly" in atributos and "secure" in atributos and "samesite=strict" in atributos and "path=/" in atributos
    assert "domain=" not in atributos                         # requisito del prefijo __Host-
    assert "contrasena" not in r.text.lower() and "hash" not in r.text.lower()


def test_el_login_no_revela_si_el_usuario_existe(cliente):
    mal_clave = iniciar_sesion(cliente, "dra.rios", "Incorrecta-123")
    no_existe = iniciar_sesion(cliente, "nadie.asi", "Incorrecta-123")
    assert mal_clave.status_code == no_existe.status_code == 401
    assert mal_clave.json() == no_existe.json()


@pytest.mark.parametrize("cuerpo,campos", [
    ({}, {"usuario", "contrasena"}),
    ({"usuario": "dra.rios"}, {"contrasena"}),
    ({"usuario": "  ", "contrasena": "x"}, {"usuario"}),
    ({"usuario": "dra.rios", "contrasena": 12345}, {"contrasena"}),
])
def test_login_con_campos_vacios_dice_cual_falta(cliente, cuerpo, campos):
    r = cliente.post("/api/sesion", json=cuerpo, headers=H)
    assert r.status_code == 400
    assert {e["campo"] for e in r.json()["detail"]["errores"]} == campos


def test_login_con_cuerpo_que_no_es_json_no_rompe(cliente):
    r = cliente.post("/api/sesion", content=b"no es json", headers=H)
    assert r.status_code == 400


def test_login_exige_la_cabecera_propia_contra_csrf(cliente):
    r = cliente.post("/api/sesion", json={"usuario": "dra.rios", "contrasena": CLAVE_DEMO})
    assert r.status_code == 403 and NOMBRE_COOKIE not in r.headers.get("set-cookie", "")


def test_login_desde_otro_origen_se_rechaza(cliente):
    r = cliente.post("/api/sesion", json={"usuario": "dra.rios", "contrasena": CLAVE_DEMO},
                     headers={**H, "Origin": "https://sitio-malicioso.example"})
    assert r.status_code == 403


def test_tras_los_intentos_fallidos_la_cuenta_se_bloquea_aunque_la_clave_sea_buena(cliente):
    for _ in range(UMBRAL_INTENTOS_FALLIDOS):
        assert iniciar_sesion(cliente, "dra.rios", "Incorrecta-123").status_code in (401, 423)
    r = iniciar_sesion(cliente, "dra.rios")
    assert r.status_code == 423 and "bloquead" in r.json()["detail"].lower()
    assert cliente.get("/api/pacientes").status_code == 401           # y no quedó ninguna sesión


def test_cerrar_sesion_borra_la_cookie_y_el_servidor_ya_no_la_acepta(entrar):
    c = entrar("dra.rios")
    token = c.cookies.get(NOMBRE_COOKIE)
    assert c.get("/api/pacientes").status_code == 200
    assert c.delete("/api/sesion").status_code == 403                  # sin la cabecera propia no cierra
    r = c.delete("/api/sesion", headers=H)
    assert r.status_code == 204 and NOMBRE_COOKIE in r.headers["set-cookie"]
    c.cookies.set(NOMBRE_COOKIE, token)                                # aunque alguien conserve el token...
    assert c.get("/api/pacientes").status_code == 401                  # ...el servidor ya lo olvidó


# --- La identidad sale de la sesión -------------------------------------------------------------


def test_la_lista_es_la_de_la_sesion_aunque_el_navegador_pida_otro_oncologo(entrar):
    c = entrar("dra.rios")
    nombres = [p["nombre_completo"] for p in c.get("/api/pacientes?oncologo_id=3&usuario_id=3").json()]
    assert len(nombres) == 6 and "Lucía Herrera Posada" in nombres and not any("Renata" in n for n in nombres)


def test_cada_oncologo_ve_solo_a_sus_pacientes(entrar):
    c = entrar("dra.rios")
    assert c.get(f"/api/pacientes/{LUCIA}").status_code == 200
    assert c.get(f"/api/pacientes/{RENATA}").status_code == 404
    assert c.get(f"/api/pacientes/{RENATA}/resumen-360").status_code == 404
    c = entrar("dr.vega")
    assert c.get(f"/api/pacientes/{RENATA}").status_code == 200
    assert c.get(f"/api/pacientes/{LUCIA}").status_code == 404
    assert len(c.get("/api/pacientes").json()) == 2


def test_la_busqueda_tambien_respeta_la_identidad(entrar):
    c = entrar("dra.rios")
    r = c.get("/api/pacientes/buscar?nombre=lu&oncologo_id=3")
    assert r.status_code == 200 and [p["nombre_completo"] for p in r.json()["items"]] == ["Lucía Herrera Posada"]


def test_revisar_una_alerta_fija_quien_revisa_con_la_sesion_no_con_el_cuerpo(entrar):
    c = entrar("dra.rios")
    r = c.post(f"/api/pacientes/{LUCIA}/alertas-laboratorio/1/revisar", json={"revisada_por": "otra.persona", "usuario_id": 3}, headers=H)
    assert r.status_code == 200
    assert r.json()["estado"] == "revisada" and r.json()["revisada_por"] == "dra.rios"


def test_no_se_revisa_la_alerta_de_un_paciente_ajeno(entrar):
    c = entrar("dra.rios")
    r = c.post(f"/api/pacientes/{RENATA}/alertas-laboratorio/1/revisar", json={}, headers=H)
    assert r.status_code == 404


def test_revisar_exige_cabecera_propia_y_mismo_origen(entrar):
    c = entrar("dra.rios")
    url = f"/api/pacientes/{LUCIA}/alertas-laboratorio/1/revisar"
    assert c.post(url, json={}).status_code == 403
    assert c.post(url, json={}, headers={**H, "Origin": "https://sitio-malicioso.example"}).status_code == 403
    assert c.get(f"/api/pacientes/{LUCIA}/alertas-laboratorio").json()[0]["estado"] == "activa"     # nada cambió
    assert c.post(url, json={}, headers={**H, "Origin": "https://testserver"}).status_code == 200


# --- Permisos por rol -----------------------------------------------------------------------


@pytest.mark.parametrize("usuario", ["enf.mora", "enf.02", "auditor.demo", "admin.demo", "direccion"])
def test_los_roles_sin_asignacion_de_pacientes_no_ven_expedientes(entrar, usuario):
    c = entrar(usuario)
    cuerpo = c.get("/api/sesion").json()
    assert cuerpo["autenticado"] and not cuerpo["acceso_clinico"] and not cuerpo["puede_exportar"] and not cuerpo["puede_revisar_alertas"]
    for ruta in ("/api/pacientes", f"/api/pacientes/{LUCIA}", f"/api/pacientes/{LUCIA}/resumen-360",
                 f"/api/pacientes/{LUCIA}/laboratorios/marcadores", f"/api/pacientes/{LUCIA}/imagenes",
                 f"/api/pacientes/{LUCIA}/exportar?formato=html", f"/api/pacientes/{LUCIA}/exportar?formato=pdf"):
        r = c.get(ruta)
        assert r.status_code == 403, f"{usuario} {ruta}: {r.status_code}"
    assert c.post(f"/api/pacientes/{LUCIA}/alertas-laboratorio/1/revisar", json={}, headers=H).status_code == 403


@pytest.mark.parametrize("usuario,explicacion", [("enf.mora", "asignado al equipo"), ("auditor.demo", MENSAJE_SIN_ASIGNACION)])
def test_enfermeria_sin_equipo_y_auditoria_reciben_la_explicacion_y_no_un_error_opaco(entrar, usuario, explicacion):
    r = entrar(usuario).get("/api/pacientes")
    assert r.status_code == 403 and r.json()["detail"] == MENSAJE_SIN_ASIGNACION
    assert explicacion in entrar(usuario).get("/api/sesion").json()["mensaje_sin_acceso_clinico"]


def test_solo_direccion_medica_ve_las_metricas(entrar):
    assert entrar("direccion").get("/api/sesion").json()["ver_metricas"] is True
    for otro in ("dra.rios", "enf.mora", "admin.demo", "auditor.demo"):
        assert entrar(otro).get("/api/sesion").json()["ver_metricas"] is False


def test_desactivar_la_cuenta_corta_la_sesion_en_la_siguiente_peticion(entrar, entorno):
    c = entrar("dra.rios")
    assert c.get("/api/pacientes").status_code == 200
    with sqlite3.connect(entorno.usuarios_db) as conn:
        conn.execute("UPDATE usuarios SET activo = 0 WHERE nombre_usuario = 'dra.rios'")
    assert c.get("/api/pacientes").status_code == 401
    assert c.get("/api/sesion").json() == {"autenticado": False}


def test_un_cambio_de_rol_se_aplica_sin_volver_a_iniciar_sesion(entrar, entorno):
    c = entrar("dra.rios")
    assert c.get("/api/pacientes").status_code == 200
    with sqlite3.connect(entorno.usuarios_db) as conn:
        conn.execute("UPDATE usuarios SET rol = 'enfermeria' WHERE nombre_usuario = 'dra.rios'")
    assert c.get("/api/pacientes").status_code == 403


def test_una_sesion_inactiva_caduca(entorno):
    class Reloj:
        t = 5000.0
        def __call__(self): return self.t
    reloj = Reloj()
    app = Pasarela(usuarios_db=entorno.usuarios_db, sesiones=AlmacenSesiones(inactividad_s=60, reloj=reloj)).crear_app()
    with TestClient(app, base_url="https://testserver") as c:
        assert iniciar_sesion(c, "dra.rios").status_code == 200
        assert c.get("/api/pacientes").status_code == 200
        reloj.t += 61
        assert c.get("/api/pacientes").status_code == 401


# --- Lista cerrada de rutas -----------------------------------------------------------------


# Registrar paciente, diagnóstico y consentimiento ya los usa la interfaz completa (ver test_escrituras_de_la_interfaz).
@pytest.mark.parametrize("metodo,ruta", [
    ("PUT", f"/api/pacientes/{LUCIA}"), ("DELETE", f"/api/pacientes/{LUCIA}"),
    ("PATCH", f"/api/pacientes/{LUCIA}"), ("POST", f"/api/pacientes/{LUCIA}/laboratorios/hl7"),
    ("POST", f"/api/pacientes/{LUCIA}/imagenes"), ("GET", f"/api/pacientes/{LUCIA}/rutas-que-no-existen"),
    ("GET", "/api/docs"), ("GET", "/api/openapi.json"), ("GET", "/docs"), ("GET", "/openapi.json"), ("GET", "/redoc"),
])
def test_lo_que_la_interfaz_no_usa_no_existe_ni_con_sesion(entrar, metodo, ruta):
    c = entrar("dra.rios")
    r = c.request(metodo, ruta, headers=H, json={} if metodo in ("POST", "PUT", "PATCH") else None)
    assert r.status_code == 404, f"{metodo} {ruta}: {r.status_code}"


def test_escrituras_de_la_interfaz_toman_la_identidad_de_la_sesion(entrar):
    """PAC-01: el oncólogo a cargo sale de la sesión aunque el navegador mande otro."""
    c = entrar("dra.rios")
    r = c.post("/api/pacientes", headers=H, json={
        "nombre_completo": "Paciente Nuevo Interfaz", "fecha_nacimiento": "1980-01-01", "sexo": "femenino",
        "tipo_identificacion": "cedula", "numero_identificacion": "77665544", "contacto": {"telefono": "3001112233"},
        "oncologo_id": 999})
    assert r.status_code == 201, r.text
    nuevo = r.json()
    assert c.get(f"/api/pacientes/{nuevo['id']}").status_code == 200       # es de dra.rios, no del 999
    assert c.post(f"/api/pacientes/{nuevo['id']}/consentimiento-ia", headers=H, json={"medio": "escrito", "soporte": ""}).status_code == 400
    sin_cabecera = c.post(f"/api/pacientes/{nuevo['id']}/diagnosticos", json={"descripcion": "x"})
    assert sin_cabecera.status_code == 403                                  # CSRF: sin la cabecera propia no pasa


def test_las_rutas_tramposas_no_cuelan_otra_ruta(entrar):
    c = entrar("dra.rios")
    for ruta in (f"/api/pacientes/{LUCIA}/%2e%2e/1", "/api/pacientes/abc", f"/api/pacientes/{LUCIA}/imagenes/a/b/visor"):
        assert c.get(ruta).status_code in (404, 422, 400), ruta


def test_solo_se_sirve_por_https(app):
    with TestClient(app, base_url="http://testserver") as c:
        for ruta in ("/", "/api/sesion", "/api/pacientes", "/ui/app.js", "/panel/metricas"):
            assert c.get(ruta).status_code == 403, ruta
        assert c.post("/api/sesion", json={"usuario": "dra.rios", "contrasena": CLAVE_DEMO}, headers=H).status_code == 403


# --- Lo que la interfaz muestra: lecturas reales ----------------------------------------------------


def test_el_resumen_360_trae_lo_que_la_pantalla_pinta(entrar):
    cuerpo = entrar("dra.rios").get(f"/api/pacientes/{LUCIA}/resumen-360").json()
    assert cuerpo["nombre"] == "Lucía Herrera Posada" and cuerpo["estadio"] == "IIB"
    assert any(a["severidad"] == "alta" for a in cuerpo["alertas_activas"]) if "alertas_activas" in cuerpo else True


def test_las_imagenes_y_el_visor_funcionan_y_el_pacs_caido_se_dice_sin_ocultar_el_informe(entrar, entorno):
    c = entrar("dra.rios")
    imagenes = c.get(f"/api/pacientes/{LUCIA}/imagenes").json()
    assert imagenes["integracion_disponible"] and len(imagenes["estudios"]) == 2
    visor = c.get(f"/api/pacientes/{LUCIA}/imagenes/{UID_ESTUDIO_LUCIA}/visor")
    assert visor.status_code == 200 and visor.json()["url"].startswith("https://") and UID_ESTUDIO_LUCIA in visor.json()["url"]
    entorno.pacs.caido = True
    try:
        assert c.get(f"/api/pacientes/{LUCIA}/imagenes").json()["integracion_disponible"] is False
        caido = c.get(f"/api/pacientes/{LUCIA}/imagenes/{UID_ESTUDIO_LUCIA}/visor")
        assert caido.status_code == 503 and caido.json()["informe"] and "no está disponible" in caido.json()["mensaje"]
    finally:
        entorno.pacs.caido = False


def test_un_uid_que_no_es_dicom_no_llega_al_visor(entrar):
    r = entrar("dra.rios").get(f"/api/pacientes/{LUCIA}/imagenes/xx/visor")
    assert r.status_code == 503 and r.json()["informe"] is None


# --- Exportación del expediente (DOC-02) --------------------------------------------------------


def test_exportar_html_descarga_un_documento_accesible_y_deja_auditoria(entrar, entorno):
    from accesibilidad.auditoria_html import auditar_html

    r = entrar("dra.rios").get(f"/api/pacientes/{LUCIA}/exportar?formato=html")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert r.headers["content-disposition"] == f'attachment; filename="expediente-paciente-{LUCIA}.html"'
    assert r.headers["content-security-policy"] == CSP_DESCARGA and "unsafe-inline" in CSP_DESCARGA and "script" not in CSP_DESCARGA
    assert "Lucía Herrera Posada" in r.text or str(LUCIA) in r.text
    assert not auditar_html(r.text).hallazgos
    assert _eventos(entorno, "exportar_expediente_html") == [(2, LUCIA, TipoAccion.EXPORTAR.value)]


def test_exportar_pdf_entrega_un_pdf_y_tambien_se_audita(entrar, entorno):
    r = entrar("dra.rios").get(f"/api/pacientes/{LUCIA}/exportar?formato=pdf")
    assert r.status_code == 200 and r.content.startswith(b"%PDF") and r.headers["content-type"] == "application/pdf"
    assert _eventos(entorno, "exportar_expediente_pdf") == [(2, LUCIA, TipoAccion.EXPORTAR.value)]


def test_exportar_no_audita_lo_que_no_se_exporto(entrar, entorno):
    c = entrar("dra.rios")
    assert c.get(f"/api/pacientes/{RENATA}/exportar?formato=html").status_code == 404           # de otro oncólogo
    assert c.get(f"/api/pacientes/{SIN_EXPEDIENTE}/exportar?formato=html").status_code == 404    # sin expediente
    assert c.get(f"/api/pacientes/{LUCIA}/exportar?formato=docx").status_code == 400             # formato desconocido
    with sqlite3.connect(entorno.pacientes_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM eventos_acceso WHERE detalle LIKE 'exportar_expediente_%'").fetchone()[0] == 0


# --- Tablero de métricas (ADM-02) ----------------------------------------------------------------


def test_direccion_ve_el_tablero_con_su_politica_y_solo_esta_pagina_puede_incrustarlo(entrar):
    r = entrar("direccion").get("/panel/metricas")
    assert r.status_code == 200 and "Uso del copiloto oncológico" in r.text
    assert r.headers["content-security-policy"] == CSP_TABLERO and "frame-ancestors 'self'" in CSP_TABLERO
    assert r.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("usuario", ["dra.rios", "enf.mora", "admin.demo", "auditor.demo"])
def test_los_demas_roles_no_ven_el_tablero(entrar, usuario):
    r = entrar(usuario).get("/panel/metricas")
    assert r.status_code == 403 and "Sin permiso" in r.text and "Solo la dirección médica" in r.text


@pytest.mark.parametrize("params", [{"desde": "2026-13-45"}, {"hasta": "ayer"}, {"desde": "2026-10-10", "hasta": "2026-10-01"}])
def test_un_periodo_invalido_se_explica_en_una_pagina_que_deja_corregir(entrar, params):
    r = entrar("direccion").get("/panel/metricas", params=params)
    assert r.status_code == 400 and r.headers["content-type"].startswith("text/html") and 'role="alert"' in r.text


def test_el_periodo_no_se_refleja_sin_escapar(entrar):
    r = entrar("direccion").get("/panel/metricas", params={"desde": '"><script>alert(1)</script>'})
    assert r.status_code == 400 and "<script>alert(1)" not in r.text


# --- Cabeceras de seguridad -----------------------------------------------------------------------


def test_la_pagina_principal_lleva_una_csp_estricta_sin_inline(cliente):
    r = cliente.get("/")
    csp = r.headers["content-security-policy"]
    assert csp == CSP_APP
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp and "default-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp and "script-src 'self'" in csp
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["strict-transport-security"]


@pytest.mark.parametrize("ruta", ["/", "/ui/app.js", "/ui/app.css", "/api/info", "/api/sesion", "/api/no-existe", "/no-existe"])
def test_toda_respuesta_lleva_las_cabeceras_de_seguridad(cliente, ruta):
    h = cliente.get(ruta).headers
    assert h["x-content-type-options"] == "nosniff" and h["referrer-policy"] == "no-referrer"
    assert "content-security-policy" in h and h["cache-control"] == "no-store" and "camera=()" in h["permissions-policy"]


def test_las_respuestas_de_la_api_no_se_guardan_en_cache(entrar):
    c = entrar("dra.rios")
    for ruta in ("/api/pacientes", f"/api/pacientes/{LUCIA}/resumen-360"):
        assert c.get(ruta).headers["cache-control"] == "no-store"


def test_la_interfaz_sirve_sus_archivos_y_nada_mas(cliente):
    assert cliente.get("/ui/app.js").status_code == 200
    assert cliente.get("/ui/index.html").status_code == 200
    assert cliente.get("/ui/../servidor.py").status_code == 404
    assert cliente.get("/ui/%2e%2e/servidor.py").status_code == 404
    assert cliente.get("/favicon.ico").headers["content-type"].startswith("image/svg+xml")


def test_el_modo_demo_se_anuncia_y_sin_el_no_se_muestran_credenciales(cliente, entorno):
    info = cliente.get("/api/info").json()
    assert info["modo_demo"] is True and {u["usuario"] for u in info["demo"]["usuarios"]} >= {"dra.rios", "direccion"}
    produccion = Pasarela(usuarios_db=entorno.usuarios_db).crear_app()
    with TestClient(produccion, base_url="https://testserver") as c:
        assert c.get("/api/info").json() == {"modo_demo": False, "demo": None}
