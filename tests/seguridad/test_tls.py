"""SEC-02 — Cifrado en tránsito.

AC: dado cualquier intercambio cliente-servidor, cuando se transmite
información clínica, viaja exclusivamente sobre una versión vigente de TLS
(sin caer a conexiones sin cifrar).
"""
from __future__ import annotations

import socket
import ssl
import threading
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from seguridad.servidor_tls import construir_config, generar_certificado_local, main
from seguridad.tls import (
    CABECERA_HSTS,
    ConexionInseguraError,
    SoloHTTPSMiddleware,
    contexto_tls_cliente,
    contexto_tls_servidor,
    exigir_url_segura,
)


@pytest.fixture(scope="module")
def certificado(tmp_path_factory):
    return generar_certificado_local(tmp_path_factory.mktemp("certs"))


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --- Contextos TLS -----------------------------------------------------------


def test_contextos_exigen_tls_12_como_minimo(certificado):
    cert, clave = certificado
    assert contexto_tls_servidor(str(cert), str(clave)).minimum_version >= ssl.TLSVersion.TLSv1_2
    cliente = contexto_tls_cliente()
    assert cliente.minimum_version >= ssl.TLSVersion.TLSv1_2
    assert cliente.check_hostname and cliente.verify_mode == ssl.CERT_REQUIRED


def _servidor_tls_un_saludo(contexto: ssl.SSLContext):
    """Acepta una conexión, intenta el saludo TLS y la cierra."""
    escucha = socket.socket()
    escucha.bind(("127.0.0.1", 0))
    escucha.listen(1)

    def atender():
        conexion, _ = escucha.accept()
        try:
            with contexto.wrap_socket(conexion, server_side=True) as tls:
                tls.sendall(b"ok")
        except (ssl.SSLError, OSError):
            pass
        finally:
            escucha.close()

    threading.Thread(target=atender, daemon=True).start()
    return escucha.getsockname()[1]


def test_servidor_negocia_tls_vigente(certificado):
    cert, clave = certificado
    puerto = _servidor_tls_un_saludo(contexto_tls_servidor(str(cert), str(clave)))
    cliente = contexto_tls_cliente(str(cert))
    with socket.create_connection(("127.0.0.1", puerto), timeout=5) as crudo:
        with cliente.wrap_socket(crudo, server_hostname="localhost") as tls:
            assert tls.version() in ("TLSv1.2", "TLSv1.3")
            assert tls.recv(2) == b"ok"


def test_servidor_rechaza_tls_obsoleto(certificado):
    cert, clave = certificado
    puerto = _servidor_tls_un_saludo(contexto_tls_servidor(str(cert), str(clave)))
    viejo = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    viejo.check_hostname = False
    viejo.verify_mode = ssl.CERT_NONE
    try:
        viejo.minimum_version = ssl.TLSVersion.TLSv1
        viejo.maximum_version = ssl.TLSVersion.TLSv1_1
        viejo.set_ciphers("ALL:@SECLEVEL=0")
    except (ValueError, ssl.SSLError):
        pytest.skip("El OpenSSL local ya no permite ni siquiera configurar TLS 1.1 en el cliente.")
    with socket.create_connection(("127.0.0.1", puerto), timeout=5) as crudo:
        with pytest.raises((ssl.SSLError, ConnectionError)):
            viejo.wrap_socket(crudo, server_hostname="localhost").recv(2)


# --- API HTTP: solo HTTPS ----------------------------------------------------


def _app():
    app = FastAPI()
    app.add_middleware(SoloHTTPSMiddleware, rutas_exentas=("/salud",))

    @app.get("/pacientes/1")
    def paciente():
        return {"diagnostico": "adenocarcinoma"}

    @app.get("/salud")
    def salud():
        return {"ok": True}

    return app


def test_peticion_en_claro_se_rechaza_sin_procesarse():
    with TestClient(_app(), base_url="http://testserver") as cliente:
        r = cliente.get("/pacientes/1", follow_redirects=False)
    assert r.status_code == 403  # sin redirección: la primera petición ya habría ido en claro
    assert "adenocarcinoma" not in r.text
    assert "HTTPS" in r.json()["detail"]


def test_peticion_https_pasa_y_obliga_hsts():
    with TestClient(_app(), base_url="https://testserver") as cliente:
        r = cliente.get("/pacientes/1")
    assert r.status_code == 200
    assert r.headers["strict-transport-security"] == CABECERA_HSTS


def test_cabecera_forwarded_proto_del_cliente_no_salta_el_control():
    """Sin un proxy de confianza, uvicorn no cambia el esquema por la cabecera."""
    with TestClient(_app(), base_url="http://testserver") as cliente:
        r = cliente.get("/pacientes/1", headers={"X-Forwarded-Proto": "https"})
    assert r.status_code == 403


def test_ruta_exenta_responde_en_claro_sin_hsts():
    with TestClient(_app(), base_url="http://testserver") as cliente:
        r = cliente.get("/salud")
    assert r.status_code == 200 and "strict-transport-security" not in r.headers


@pytest.mark.parametrize("modulo", ["patients.api", "administracion.api"])
def test_las_apis_del_copiloto_rechazan_http(modulo, tmp_path, monkeypatch):
    import importlib

    api = importlib.import_module(modulo)
    if modulo == "patients.api":
        monkeypatch.setattr(api, "DB_PATH", tmp_path / "p.db")
        monkeypatch.setattr(api, "EXPEDIENTE_PATH", tmp_path / "e.db")
    else:
        monkeypatch.setattr(api, "USUARIOS_DB_PATH", tmp_path / "u.db")
    with TestClient(api.app, base_url="http://testserver") as cliente:
        assert cliente.get("/docs").status_code == 403


# --- Servidor real con uvicorn -----------------------------------------------


def test_servidor_tls_real_atiende_https_y_no_http(certificado):
    cert, clave = certificado
    puerto = _puerto_libre()
    import uvicorn

    config = construir_config(_app(), "127.0.0.1", puerto, str(cert), str(clave))
    config.log_level = "warning"
    servidor = uvicorn.Server(config)
    hilo = threading.Thread(target=servidor.run, daemon=True)
    hilo.start()
    try:
        for _ in range(100):
            if servidor.started:
                break
            time.sleep(0.05)
        r = httpx.get(f"https://localhost:{puerto}/pacientes/1", verify=contexto_tls_cliente(str(cert)))
        assert r.status_code == 200
        assert r.headers["strict-transport-security"] == CABECERA_HSTS
        with pytest.raises(httpx.HTTPError):
            httpx.get(f"http://localhost:{puerto}/pacientes/1", timeout=3)
    finally:
        servidor.should_exit = True
        hilo.join(timeout=5)


def test_servidor_no_arranca_sin_certificado(monkeypatch, capsys):
    monkeypatch.delenv("COPILOTO_TLS_CERT", raising=False)
    monkeypatch.delenv("COPILOTO_TLS_KEY", raising=False)
    assert main([]) == 2
    assert "no se sirve sin cifrar" in capsys.readouterr().err


def test_servidor_no_arranca_con_certificado_inexistente(tmp_path):
    with pytest.raises(FileNotFoundError):
        construir_config("patients.api:app", "127.0.0.1", 8443, str(tmp_path / "no.pem"), str(tmp_path / "no.key"))


# --- Integraciones salientes ------------------------------------------------


@pytest.mark.parametrize(
    "url",
    ["https://www.cbioportal.org/api", "http://localhost:8042/dicom-web", "http://127.0.0.1:8042", "http://[::1]:8042"],
)
def test_urls_aceptadas(url):
    assert exigir_url_segura(url) == url


@pytest.mark.parametrize("url", ["http://pacs.hospital.example/dicom-web", "http://10.0.0.5:8042", "ftp://x", "pacs"])
def test_urls_en_claro_hacia_la_red_se_rechazan(url):
    with pytest.raises(ConexionInseguraError):
        exigir_url_segura(url)


def test_loopback_tambien_se_puede_prohibir():
    with pytest.raises(ConexionInseguraError):
        exigir_url_segura("http://localhost:8042", permitir_loopback=False)


def test_pacs_cbioportal_y_visor_exigen_tls():
    from cbioportal.cliente import ClienteCBioPortal
    from historia_clinica.imagenes_pacs import ErrorConfiguracionVisor, FuenteDICOMweb, validar_plantilla_visor

    with pytest.raises(ConexionInseguraError):
        FuenteDICOMweb("PACS", "http://pacs.hospital.example/dicom-web", session=object())
    with pytest.raises(ConexionInseguraError):
        ClienteCBioPortal("http://cbioportal.hospital.example/api", session=object())
    with pytest.raises(ErrorConfiguracionVisor):
        validar_plantilla_visor("http://visor.hospital.example/viewer?StudyInstanceUIDs={study_uid}")
    # El Orthanc local de la demo de HC-03 sigue funcionando.
    assert FuenteDICOMweb("Orthanc local", "http://localhost:8042/dicom-web", session=object()).base_url


def test_api_informa_pacs_sin_tls_como_no_disponible(monkeypatch):
    import patients.api as api

    monkeypatch.setattr(api, "PACS_FUENTE", None)
    monkeypatch.setenv("COPILOTO_PACS_URL", "http://pacs.hospital.example/dicom-web")
    assert api._fuente_pacs() is None
