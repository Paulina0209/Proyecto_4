"""Sonda de salud del contenedor (NFR-02): ¿esta réplica responde por HTTPS? Sale con 0 si sí, 1 si no.

El certificado puede ser autofirmado; aquí solo importa que el proceso atienda, por eso no se valida.
"""
import json
import os
import ssl
import sys
import urllib.request

puerto = os.environ.get("COPILOTO_PUERTO", "8443")
contexto = ssl.create_default_context()
contexto.check_hostname = False
contexto.verify_mode = ssl.CERT_NONE
try:
    with urllib.request.urlopen(f"https://127.0.0.1:{puerto}/salud/vivo", context=contexto, timeout=4) as respuesta:
        sys.exit(0 if json.load(respuesta).get("estado") == "vivo" else 1)
except Exception:  # noqa: BLE001 - cualquier falla es «no sano»
    sys.exit(1)
