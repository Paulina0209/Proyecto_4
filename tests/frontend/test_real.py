"""Lanzador de la interfaz con datos reales (``python -m frontend.real``)."""
from datetime import datetime, timedelta, timezone

from frontend import real


def test_crea_el_certificado_si_falta_y_lo_reutiliza_si_sigue_vigente(tmp_path):
    cert, clave = real.asegurar_certificado(tmp_path, aviso=lambda _m: None)
    assert cert.is_file() and clave.is_file()
    contenido = cert.read_bytes()
    otra_vez, _ = real.asegurar_certificado(tmp_path, aviso=lambda _m: None)
    assert otra_vez.read_bytes() == contenido


def test_renueva_el_certificado_que_esta_por_vencer(tmp_path):
    cert, _ = real.asegurar_certificado(tmp_path, aviso=lambda _m: None)
    viejo = cert.read_bytes()
    dentro_de_29_dias = datetime.now(timezone.utc) + timedelta(days=29)   # el local dura 30
    nuevo, _ = real.asegurar_certificado(tmp_path, ahora=dentro_de_29_dias, aviso=lambda _m: None)
    assert nuevo.read_bytes() != viejo


def test_un_certificado_ilegible_se_reemplaza(tmp_path):
    (tmp_path / "localhost.pem").write_text("no es un certificado")
    (tmp_path / "localhost-clave.pem").write_text("x")
    cert, _ = real.asegurar_certificado(tmp_path, aviso=lambda _m: None)
    assert b"BEGIN CERTIFICATE" in cert.read_bytes()


def test_sirve_la_pasarela_sobre_tls_con_el_certificado_local(tmp_path):
    args = real.argumentos_servidor(tmp_path / "c.pem", tmp_path / "k.pem", 9443, "127.0.0.1", 2)
    assert args[args.index("--app") + 1] == "frontend.servidor:app"
    assert args[args.index("--port") + 1] == "9443" and args[args.index("--workers") + 1] == "2"
    assert args[args.index("--cert") + 1].endswith("c.pem") and args[args.index("--key") + 1].endswith("k.pem")


def test_sin_llave_de_openai_no_indexa_pero_no_impide_arrancar(monkeypatch):
    from core import llm_config

    monkeypatch.setattr(llm_config, "obtener_api_key", lambda: None)
    mensajes = []
    real.indexar(aviso=mensajes.append)
    assert "OPENAI_API_KEY" in mensajes[0]


def test_muestra_los_usuarios_del_escenario_y_no_los_de_la_demo_sintetica():
    mensajes = []
    real.mostrar_accesos(8443, aviso=mensajes.append)
    texto = "\n".join(mensajes)
    assert "https://127.0.0.1:8443" in texto and "dra.gomez" in texto and "admin.copiloto" in texto
    assert "admin.demo" not in texto


def test_el_orden_es_datos_certificado_indice_y_servidor(monkeypatch, tmp_path):
    pasos = []
    monkeypatch.setattr(real, "preparar_datos", lambda: pasos.append("datos") or 0)
    monkeypatch.setattr(real, "asegurar_certificado", lambda: pasos.append("cert") or (tmp_path / "c", tmp_path / "k"))
    monkeypatch.setattr(real, "indexar", lambda: pasos.append("indice"))
    monkeypatch.setattr(real, "mostrar_accesos", lambda _p: None)
    import seguridad.servidor_tls as tls
    monkeypatch.setattr(tls, "main", lambda argv: pasos.append(("servidor", argv[1])) or 0)
    assert real.main([]) == 0
    assert pasos == ["datos", "cert", "indice", ("servidor", "frontend.servidor:app")]
    pasos.clear()
    assert real.main(["--sin-indexar"]) == 0
    assert "indice" not in pasos


def test_si_los_datos_no_se_pueden_preparar_no_arranca(monkeypatch):
    monkeypatch.setattr(real, "preparar_datos", lambda: 1)
    monkeypatch.setattr(real, "asegurar_certificado", lambda: (_ for _ in ()).throw(AssertionError("no debía seguir")))
    assert real.main([]) == 1
