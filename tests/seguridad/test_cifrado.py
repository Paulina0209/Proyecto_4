"""SEC-02 — Cifrado en reposo (AES-256-GCM)."""
from __future__ import annotations

import sqlite3

import pytest

from seguridad import cifrado
from seguridad.cifrado import (
    Cifrador,
    ErrorCifrado,
    cifrador_configurado,
    esta_cifrado,
    generar_clave,
    leer_descifrado,
    respaldar_base_cifrada,
    restaurar_respaldo,
)

DATO = b"Paciente con EGFR L858R, en osimertinib."


@pytest.fixture()
def cifrador():
    return Cifrador.desde_texto(generar_clave())


def test_ida_y_vuelta(cifrador):
    blob = cifrador.cifrar(DATO, "documento:paciente_1")
    assert esta_cifrado(blob) and DATO not in blob
    assert cifrador.descifrar(blob, "documento:paciente_1") == DATO


def test_cada_cifrado_usa_un_nonce_distinto(cifrador):
    assert cifrador.cifrar(DATO, "c") != cifrador.cifrar(DATO, "c")


def test_dato_alterado_se_detecta(cifrador):
    blob = bytearray(cifrador.cifrar(DATO, "c"))
    blob[-1] ^= 1
    with pytest.raises(ErrorCifrado, match="alterado"):
        cifrador.descifrar(bytes(blob), "c")


def test_contexto_distinto_no_descifra(cifrador):
    """Un archivo de un paciente no se puede hacer pasar por el de otro."""
    blob = cifrador.cifrar(DATO, "documento:paciente_1")
    with pytest.raises(ErrorCifrado):
        cifrador.descifrar(blob, "documento:paciente_2")


def test_otra_clave_se_identifica(cifrador):
    blob = cifrador.cifrar(DATO, "c")
    with pytest.raises(ErrorCifrado, match="otra clave"):
        Cifrador.desde_texto(generar_clave()).descifrar(blob, "c")


def test_clave_invalida():
    with pytest.raises(ErrorCifrado):
        Cifrador(b"corta")
    with pytest.raises(ErrorCifrado):
        Cifrador.desde_texto("no es base64 ñ")


def test_clave_desde_variable_de_entorno(monkeypatch):
    clave = generar_clave()
    monkeypatch.setenv(cifrado.ENV_CLAVE, clave)
    assert cifrador_configurado().clave == Cifrador.desde_texto(clave).clave


def test_clave_se_crea_una_vez_en_el_archivo(monkeypatch, tmp_path):
    monkeypatch.delenv(cifrado.ENV_CLAVE, raising=False)
    ruta = tmp_path / "secretos" / "clave"
    monkeypatch.setenv(cifrado.ENV_ARCHIVO_CLAVE, str(ruta))
    with pytest.raises(ErrorCifrado):
        cifrador_configurado(crear_si_falta=False)
    primero = cifrador_configurado()
    assert ruta.is_file() and "creado" in primero.origen
    assert cifrador_configurado().clave == primero.clave


def test_archivo_anterior_sin_cifrar_se_sigue_leyendo(tmp_path, cifrador):
    ruta = tmp_path / "viejo.pdf"
    ruta.write_bytes(b"%PDF-1.4 anterior a SEC-02")
    assert leer_descifrado(ruta, "c", cifrador) == b"%PDF-1.4 anterior a SEC-02"


def test_respaldo_cifrado_de_base_sqlite(tmp_path, cifrador):
    base = tmp_path / "copiloto.db"
    with sqlite3.connect(base) as conn:
        conn.execute("CREATE TABLE pacientes (nombre TEXT)")
        conn.execute("INSERT INTO pacientes VALUES ('María Pérez')")
    conn.close()

    respaldo = respaldar_base_cifrada(base, tmp_path / "respaldo.cpc", cifrador)
    contenido = respaldo.read_bytes()
    assert esta_cifrado(contenido) and b"Mar\xc3\xada" not in contenido and b"SQLite" not in contenido

    restaurada = restaurar_respaldo(respaldo, tmp_path / "restaurada.db", cifrador)
    with sqlite3.connect(restaurada) as conn:
        assert conn.execute("SELECT nombre FROM pacientes").fetchone()[0] == "María Pérez"
    conn.close()
    with pytest.raises(FileExistsError):
        restaurar_respaldo(respaldo, restaurada, cifrador)


def test_documento_clinico_queda_cifrado_en_disco(tmp_path):
    """DOC-01: el archivo en disco no contiene el documento en claro."""
    from documentos_clinicos.carga_documentos import (
        cargar_documento_clinico,
        crear_conexion,
        leer_contenido_documento,
    )
    from expediente.db import crear_conexion as crear_expediente
    from tests.datos_sinteticos import sembrar_datos_sinteticos

    conn_hc = crear_expediente()
    pid = sembrar_datos_sinteticos(conn_hc)["paciente_maria"]
    contenido = b"%PDF-1.4\n" + DATO
    doc = cargar_documento_clinico(
        crear_conexion(), conn_hc, pid, "informe.pdf", contenido, "dra. prueba", tmp_path
    )

    en_disco = (tmp_path / f"paciente_{pid}").iterdir().__next__().read_bytes()
    assert esta_cifrado(en_disco) and DATO not in en_disco
    assert leer_contenido_documento(doc) == contenido
    assert doc.tamano_bytes == len(contenido)
