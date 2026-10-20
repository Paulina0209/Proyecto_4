"""NFR-05 — Escalabilidad horizontal: varios procesos atienden la misma API.

(Las sesiones compartidas entre réplicas de la interfaz se prueban en
tests/frontend/test_replicas.py, con los datos de la demo.)
"""
from __future__ import annotations

import collections
import os
import pickle
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from seguridad.servidor_tls import FabricaContextoTLS, construir_config, generar_certificado_local

RAIZ = Path(__file__).resolve().parents[2]


def test_la_fabrica_tls_viaja_a_los_procesos_hijos(tmp_path):
    cert, clave = generar_certificado_local(tmp_path)
    fabrica = pickle.loads(pickle.dumps(FabricaContextoTLS(str(cert), str(clave))))
    assert fabrica().minimum_version.name in ("TLSv1_2", "TLSv1_3")


def test_varios_procesos_exigen_la_app_como_texto(tmp_path):
    cert, clave = generar_certificado_local(tmp_path)
    with pytest.raises(ValueError, match="texto"):
        construir_config(object(), "127.0.0.1", 8443, str(cert), str(clave), workers=2)
    assert construir_config("patients.api:app", "127.0.0.1", 8443, str(cert), str(clave), workers=2).workers == 2


def test_dos_procesos_reparten_las_peticiones(tmp_path):
    """Arranca de verdad ``servidor_tls --workers 2`` y comprueba que responden dos procesos distintos."""
    import httpx

    from patients import db
    from seguridad.tls import contexto_tls_cliente

    conn = db.conectar(tmp_path / "pacientes.db")
    db.inicializar(conn)
    conn.close()
    cert, clave = generar_certificado_local(tmp_path / "certs")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    entorno = {**os.environ, "COPILOTO_PACIENTES_DB": str(tmp_path / "pacientes.db"),
               "COPILOTO_EXPEDIENTE_DB": str(tmp_path / "expediente.db"),
               "COPILOTO_SESIONES_DB": str(tmp_path / "sesiones.db")}
    proceso = subprocess.Popen(
        [sys.executable, "-m", "seguridad.servidor_tls", "--app", "patients.api:app", "--port", str(puerto),
         "--workers", "2", "--cert", str(cert), "--key", str(clave)],
        cwd=str(RAIZ), env=entorno, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    url = f"https://127.0.0.1:{puerto}/salud/vivo"
    contexto = contexto_tls_cliente(str(cert))
    try:
        limite = time.monotonic() + 60
        while time.monotonic() < limite:
            try:
                httpx.get(url, verify=contexto, timeout=2)
                break
            except httpx.HTTPError:
                time.sleep(0.3)
        instancias = collections.Counter()
        limite = time.monotonic() + 30
        while len(instancias) < 2 and time.monotonic() < limite:
            with httpx.Client(verify=contexto) as cliente:  # conexión nueva: el sistema la asigna a un proceso
                instancias[cliente.get(url).json()["instancia"]] += 1
        assert len(instancias) == 2, instancias
    finally:
        proceso.terminate()
        proceso.wait(timeout=15)
