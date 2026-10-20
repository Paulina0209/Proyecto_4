"""NFR-03 en un Chromium real: cada pantalla de la interfaz, con sesión iniciada, contra un servidor HTTPS local.

Para cada pantalla se revisa, en claro 1280 px, oscuro 1280 px y claro 320 px (reflujo, 1.4.10): contraste
calculado, espaciado de texto, reflujo y axe-core (si hay una copia: ``AXE_CORE_JS``). Además se recorre
con el teclado y se comprueba que la consola quede limpia. Se omite si no hay Playwright/Chromium/uvicorn.

Un resultado limpio NO significa «accesible»: falta la prueba manual con lector de pantalla
(docs/accesibilidad.md, sección «Prueba manual»).
"""
from __future__ import annotations

import dataclasses
import shutil
import socket
import threading
import time
from contextlib import contextmanager

import pytest

pytest.importorskip("playwright")
pytest.importorskip("uvicorn")
pytest.importorskip("cryptography")

from accesibilidad.navegador import Navegador, NavegadorNoDisponible, auditar_pagina_abierta, ruta_axe  # noqa: E402
from frontend.demo import _guardar_metricas, configurar_api_de_pacientes, construir_app  # noqa: E402
from frontend.demo_datos import CLAVE_DEMO  # noqa: E402
from seguridad.servidor_tls import construir_config, generar_certificado_local  # noqa: E402

VARIANTES = [("claro", 1280), ("oscuro", 1280), ("claro", 320)]
ESQUEMA = {"claro": "light", "oscuro": "dark"}
ESPERA_CARGA = "() => !document.querySelector('main').hasAttribute('aria-busy') && !document.querySelector('main .cargando')"


# --- Servidor y navegador ----------------------------------------------------------------------------------


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def sitio(plantilla, tmp_path_factory):
    """La interfaz real sirviendo datos sintéticos por HTTPS (certificado autofirmado, solo para esta prueba)."""
    import uvicorn  # noqa: F401
    from patients import api as papi

    carpeta = tmp_path_factory.mktemp("sitio") / "demo"
    shutil.copytree(plantilla.carpeta, carpeta, ignore=shutil.ignore_patterns("certs"))
    entorno = dataclasses.replace(
        plantilla, carpeta=carpeta, usuarios_db=carpeta / plantilla.usuarios_db.name,
        pacientes_db=carpeta / plantilla.pacientes_db.name, expediente_db=carpeta / plantilla.expediente_db.name)
    puerto = _puerto_libre()
    mp = pytest.MonkeyPatch()
    for nombre in ("DB_PATH", "EXPEDIENTE_PATH", "PACS_FUENTE", "VISOR_PLANTILLA", "CARGADOR_DETALLE"):
        mp.setattr(papi, nombre, getattr(papi, nombre))
    configurar_api_de_pacientes(entorno, puerto)
    rutas = {"accesos": carpeta / "metricas_accesos.db", "expediente": carpeta / "metricas_expediente.db"}
    app = construir_app(entorno, puerto, metricas=rutas)
    cert, clave = generar_certificado_local(tmp_path_factory.mktemp("certs"))
    config = construir_config(app, "127.0.0.1", puerto, str(cert), str(clave))
    config.log_level, config.access_log = "warning", False
    servidor = uvicorn.Server(config)
    hilo = threading.Thread(target=servidor.run, daemon=True)
    hilo.start()
    limite = time.time() + 20
    while not servidor.started and time.time() < limite:
        time.sleep(0.05)
    assert servidor.started, "el servidor de prueba no arrancó"
    try:
        yield f"https://127.0.0.1:{puerto}"
    finally:
        servidor.should_exit = True
        hilo.join(10)
        mp.undo()


@pytest.fixture(scope="module")
def nav():
    try:
        with Navegador() as n:
            yield n
    except NavegadorNoDisponible as exc:
        pytest.skip(str(exc))


def _vigilar(page):
    """Todo lo que el navegador considera un problema: consola, excepciones, peticiones fallidas o con error HTTP."""
    problemas = []
    page.on("console", lambda m: problemas.append(f"consola.{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: problemas.append(f"excepción: {e}"))
    page.on("requestfailed", lambda r: problemas.append(f"petición fallida: {r.url}"))
    page.on("response", lambda r: problemas.append(f"HTTP {r.status}: {r.url}") if r.status >= 400 else None)
    return problemas


@contextmanager
def abierta(nav, sitio, usuario, *, esquema="claro", ancho=1280):
    """Una pestaña nueva en el sitio; con ``usuario`` inicia sesión por la propia pantalla (como lo haría una persona)."""
    with nav.pagina(url=sitio + "/", ancho=ancho, esquema=ESQUEMA[esquema], ignorar_errores_https=True) as page:
        problemas = _vigilar(page)
        page.wait_for_selector("h1:has-text('Iniciar sesión')")
        if usuario:
            page.fill("input[name=usuario]", usuario)
            page.fill("input[name=contrasena]", CLAVE_DEMO)
            page.click("button[type=submit]")
            page.wait_for_selector("#btn-salir:visible")
            page.wait_for_function(ESPERA_CARGA)
        yield page, problemas


def _ir(page, destino: str):
    page.evaluate("d => { window.location.hash = d; }", destino)
    page.wait_for_function("h => window.location.hash === h", arg=destino)
    page.wait_for_function(ESPERA_CARGA)
    page.wait_for_function("() => !!document.querySelector('main h1')")
    page.wait_for_timeout(120)                      # deja que termine el anuncio diferido para lectores de pantalla


def _marco_del_tablero(page, espera_s: float = 15.0):
    limite = time.time() + espera_s
    while time.time() < limite:
        for f in page.frames:
            if "/panel/metricas" in f.url:
                return f
        page.wait_for_timeout(100)
    raise AssertionError("el tablero no se cargó en el marco: " + ", ".join(f.url for f in page.frames))


def _auditar(page, etiqueta: str):
    informe = auditar_pagina_abierta(page, etiqueta=etiqueta, axe_js=ruta_axe())
    return [f"{etiqueta}: {h}" for h in informe.hallazgos], informe


PANTALLAS_ONCOLOGIA = [
    ("lista de pacientes", "#/pacientes"),
    ("resumen del expediente", "#/pacientes/1"),
    ("laboratorios", "#/pacientes/1/laboratorios"),
    ("laboratorios con tendencia", "#/pacientes/1/laboratorios?prueba=Hemoglobina"),
    ("imágenes", "#/pacientes/1/imagenes"),
    ("biomarcadores", "#/pacientes/1/biomarcadores"),
    ("historia clínica", "#/pacientes/1/historia"),
    ("expediente incompleto", "#/pacientes/5"),
    ("expediente sin datos clínicos", "#/pacientes/6/laboratorios"),
    ("paciente que no es suyo", "#/pacientes/7"),
    ("sección que no existe", "#/pacientes/1/nada"),
    ("página que no existe", "#/nada"),
]


# --- Pantallas ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("esquema,ancho", VARIANTES, ids=lambda v: str(v))
def test_las_pantallas_de_oncologia_no_tienen_hallazgos(nav, sitio, esquema, ancho):
    hallazgos, revisados = [], 0
    with abierta(nav, sitio, "dra.rios", esquema=esquema, ancho=ancho) as (page, problemas):
        for nombre, destino in PANTALLAS_ONCOLOGIA:
            _ir(page, destino)
            h, informe = _auditar(page, f"[{nombre}, {esquema} {ancho} px]")
            hallazgos += h
            if ruta_axe() is not None:
                assert page.evaluate("typeof axe") == "object"             # axe-core corrió de verdad (aun con CSP estricta)
            revisados += informe.datos[next(k for k in informe.datos if k.startswith("contraste"))]["revisados"]
        # Solo se esperan los 404 deliberados: el paciente ajeno (#/pacientes/7) y su eco en la consola del navegador.
        inesperados = [p for p in problemas if not p.startswith("HTTP 404") and "status of 404" not in p]
        assert inesperados == [] and sum(p.startswith("HTTP 404") for p in problemas) >= 1
    assert not hallazgos, "\n".join(hallazgos)
    assert revisados > 200                      # de verdad se revisó texto, no páginas vacías


@pytest.mark.parametrize("esquema,ancho", VARIANTES, ids=lambda v: str(v))
def test_el_inicio_de_sesion_y_su_error_no_tienen_hallazgos(nav, sitio, esquema, ancho):
    hallazgos = []
    with abierta(nav, sitio, None, esquema=esquema, ancho=ancho) as (page, problemas):
        h, _ = _auditar(page, f"[acceso, {esquema} {ancho} px]")
        hallazgos += h
        page.fill("input[name=usuario]", "dra.rios")
        page.fill("input[name=contrasena]", "Incorrecta-123")
        page.click("button[type=submit]")
        page.wait_for_selector("[role=alert]")
        h, _ = _auditar(page, f"[acceso con error, {esquema} {ancho} px]")
        hallazgos += h
        page.click("button[type=submit]")                                  # contraseña vacía: error por campo
        page.wait_for_selector("input[aria-invalid=true]")
        h, _ = _auditar(page, f"[acceso con campos vacíos, {esquema} {ancho} px]")
        hallazgos += h
        assert [p for p in problemas if not p.startswith(("HTTP 401", "HTTP 400", "consola.error: Failed to load resource"))] == []
    assert not hallazgos, "\n".join(hallazgos)


@pytest.mark.parametrize("esquema,ancho", VARIANTES, ids=lambda v: str(v))
def test_el_tablero_de_direccion_y_la_pantalla_sin_acceso_no_tienen_hallazgos(nav, sitio, esquema, ancho):
    hallazgos = []
    with abierta(nav, sitio, "direccion", esquema=esquema, ancho=ancho) as (page, problemas):
        page.wait_for_selector("iframe.marco-tablero")
        marco = page.frame_locator("iframe.marco-tablero")
        marco.locator("h1").wait_for()
        assert page.locator("iframe.marco-tablero").get_attribute("title")           # 4.1.2: el marco tiene nombre
        h, _ = _auditar(page, f"[métricas (página), {esquema} {ancho} px]")
        hallazgos += h
        assert problemas == []
    with abierta(nav, sitio, "enf.mora", esquema=esquema, ancho=ancho) as (page, _problemas):
        assert page.locator("main h1").inner_text() == "Sin pantallas de expediente"
        h, _ = _auditar(page, f"[sin acceso, {esquema} {ancho} px]")
        hallazgos += h
    assert not hallazgos, "\n".join(hallazgos)


def test_el_tablero_incrustado_pasa_la_auditoria_dentro_del_marco(nav, sitio):
    with abierta(nav, sitio, "direccion") as (page, _):
        page.wait_for_selector("iframe.marco-tablero")
        marco = _marco_del_tablero(page)
        marco.wait_for_selector("h1")
        assert marco.inner_text("h1") == "Uso del copiloto oncológico"
        axe = ruta_axe()
        if axe is not None:
            marco.evaluate(axe.read_text(encoding="utf-8"))
            res = marco.evaluate("axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa']}})")
            assert [v["id"] for v in res["violations"]] == []


# --- Teclado, foco y anuncios ---------------------------------------------------------------------------------


def test_se_puede_iniciar_sesion_solo_con_teclado_y_el_foco_cae_en_el_titulo(nav, sitio):
    with abierta(nav, sitio, None) as (page, _):
        assert page.evaluate("document.activeElement.id") != ""          # el campo de usuario recibe el foco al abrir
        page.keyboard.type("dra.rios")
        page.keyboard.press("Tab")
        page.keyboard.type(CLAVE_DEMO)
        page.keyboard.press("Enter")
        page.wait_for_selector(".chat-app")                                # oncología entra al asistente
        assert page.evaluate("document.activeElement.tagName") == "TEXTAREA"  # el foco queda en la pregunta, su acción principal
        assert page.title().startswith("Asistente clínico — ")


def test_el_salto_al_contenido_funciona_y_cada_pantalla_tiene_un_solo_h1_y_titulo_propio(nav, sitio):
    with abierta(nav, sitio, "dra.rios") as (page, _):
        titulos = set()
        for _nombre, destino in PANTALLAS_ONCOLOGIA[:7]:
            _ir(page, destino)
            assert page.locator("h1").count() == 1
            titulos.add(page.title())
        assert len(titulos) >= 6 and all(t.endswith("Copiloto oncológico") for t in titulos)
        page.reload()                                    # como al abrir la página: el foco empieza al principio del documento
        page.wait_for_selector("#btn-salir:visible")
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.className") == "saltar"
        page.keyboard.press("Enter")
        assert page.evaluate("document.activeElement.id") == "contenido"
        assert page.evaluate("window.location.hash") != "#contenido"          # el salto no se confunde con una ruta del enrutador
        assert page.locator("main h1").count() == 1 and page.locator("main h1").inner_text() != "Página no encontrada"


def test_el_recorrido_por_teclado_de_la_lista_y_del_expediente_muestra_foco_y_no_atrapa(nav, sitio):
    with abierta(nav, sitio, "dra.rios") as (page, _):
        for destino in ("#/pacientes", "#/pacientes/1/laboratorios?prueba=Hemoglobina", "#/pacientes/1/imagenes"):
            _ir(page, destino)
            informe = auditar_pagina_abierta(page, etiqueta=destino, axe_js=None, teclado=True)
            paradas = informe.datos["paradas_de_tabulacion"]
            assert informe.aprobado, informe.resumen()
            assert 8 <= len(paradas) <= 60, destino


def test_los_cambios_de_pantalla_se_anuncian_a_los_lectores_de_pantalla(nav, sitio):
    with abierta(nav, sitio, "dra.rios") as (page, _):
        _ir(page, "#/pacientes/1/laboratorios")
        page.wait_for_function("document.getElementById('anuncios').textContent.length > 0")
        assert "Laboratorios" in page.inner_text("#anuncios") or "Herrera" in page.inner_text("#anuncios")
        assert page.get_attribute("#anuncios", "aria-live") == "polite"


def test_la_grafica_de_tendencia_tiene_nombre_descripcion_tabla_y_formas_distintas(nav, sitio):
    with abierta(nav, sitio, "dra.rios") as (page, _):
        _ir(page, "#/pacientes/1/laboratorios?prueba=Hemoglobina")
        page.wait_for_selector("svg.grafica")
        assert page.get_attribute("svg.grafica", "role") == "img"
        nombre = page.evaluate("""() => { const s = document.querySelector('svg.grafica');
            return s.getAttribute('aria-labelledby').split(' ').map(i => document.getElementById(i).textContent).join(' | '); }""")
        assert "Tendencia de Hemoglobina" in nombre and "resultados" in nombre
        assert page.locator("svg.grafica rect.punto.alterado").count() >= 1             # fuera de rango: cuadrado, no solo color
        assert page.locator("table:has(caption:has-text('Resultados de Hemoglobina')) td:has-text('Fuera de rango')").count() >= 1
        assert page.locator("text=Círculo: normal. Cuadrado: fuera de rango. Rombo: crítico.").count() == 1
        assert page.get_attribute(".zona-grafica", "tabindex") == "0"                    # 2.1.1: la región desplazable se alcanza con teclado


def test_cerrar_sesion_vuelve_al_acceso_con_aviso_y_el_boton_atras_no_muestra_datos(nav, sitio):
    with abierta(nav, sitio, "dra.rios") as (page, _):
        _ir(page, "#/pacientes/1")
        page.click("#btn-salir")
        page.wait_for_selector("h1:has-text('Iniciar sesión')")
        assert "Cerraste tu sesión" in page.inner_text("main")
        page.go_back()
        page.wait_for_selector("h1:has-text('Iniciar sesión')")
        assert page.locator("text=Lucía Herrera Posada").count() == 0


def test_el_texto_clinico_se_muestra_como_texto_nunca_como_html(nav, sitio, plantilla):
    """Un nombre con marcado no se interpreta: la interfaz solo inserta texto (CSP además impediría ejecutarlo)."""
    import sqlite3
    # Se usa la misma base del sitio (módulo): renombra al paciente 6 con un texto «malicioso» y vuelve a leerlo.
    from patients import api as papi

    with sqlite3.connect(papi.DB_PATH) as conn:
        original = conn.execute("SELECT nombre_completo FROM pacientes WHERE id = 6").fetchone()[0]
        conn.execute("UPDATE pacientes SET nombre_completo = ? WHERE id = 6", ('<img src=x onerror="window.__xss=1">Tomás <b>Villegas</b>',))
    try:
        with abierta(nav, sitio, "dra.rios") as (page, _):
            _ir(page, "#/pacientes")
            assert page.locator("table >> text=<img src=x").count() == 1
            assert page.evaluate("window.__xss") is None and page.locator("table img").count() == 0
    finally:
        with sqlite3.connect(papi.DB_PATH) as conn:
            conn.execute("UPDATE pacientes SET nombre_completo = ? WHERE id = 6", (original,))


def test_la_interfaz_es_siempre_clara_aunque_el_sistema_prefiera_oscuro(nav, sitio):
    with abierta(nav, sitio, "dra.rios", esquema="oscuro") as (page, _):
        assert page.locator("#btn-tema").count() == 0                        # ya no hay selector de tema: solo claro
        _ir(page, "#/pacientes/1")
        fondo = page.evaluate("getComputedStyle(document.body).backgroundColor")
        assert fondo == "rgb(244, 248, 253)", fondo
        hallazgos, _ = _auditar(page, "[sistema en oscuro]")
        assert not hallazgos, "\n".join(hallazgos)
