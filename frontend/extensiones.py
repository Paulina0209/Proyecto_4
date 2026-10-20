"""Partes de la interfaz que se activan solas cuando el backend las trae.

**HC-06** (línea de tiempo) y **CFG-02** (notificaciones y alertas) ya las
publica ``patients.api`` (``historia_clinica/linea_tiempo.py`` y
``configuracion/notificaciones.py``). La interfaz las activa al detectar
estas rutas (cualquiera de los nombres de la lista); sin ellas, muestra
«Pendiente de integrar»:

    HC-06  GET /pacientes/{paciente_id}/linea-tiempo      (o /linea-de-tiempo, /timeline)
           -> lista de eventos, o {"eventos": [...]}; cada evento con
              fecha, tipo, descripción (los nombres de campo que se aceptan
              están en ``CAMPOS_EVENTO``) y, si la fecha es aproximada,
              "fecha_aproximada": true o "precision": "mes"|"anio".
           Acepta ?tipo=... para filtrar (si no, la interfaz filtra).

    CFG-02 GET /notificaciones                            -> lista de notificaciones del oncólogo
           GET /notificaciones/preferencias               -> qué eventos avisan y por qué canal
           PUT /notificaciones/preferencias               -> guardar las preferencias
           POST /notificaciones/{id}/leida                -> marcar como leída (opcional)

La pasarela pone la identidad de la sesión (``oncologo_id``/``usuario_id``) como en
el resto de la API. Ver docs/frontend_extensiones.md.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

RUTAS_LINEA_TIEMPO = ("/pacientes/{paciente_id}/linea-tiempo", "/pacientes/{paciente_id}/linea-de-tiempo",
                      "/pacientes/{paciente_id}/timeline")
RUTA_NOTIFICACIONES = "/notificaciones"

#: Nombres de campo que la interfaz entiende en un evento de la línea de tiempo.
CAMPOS_EVENTO = {
    "fecha": ("fecha", "fecha_evento", "date", "inicio"),
    "tipo": ("tipo", "tipo_evento", "categoria", "type"),
    "descripcion": ("descripcion", "titulo", "detalle", "resumen", "description"),
    "aproximada": ("fecha_aproximada", "aproximada", "es_aproximada"),
}


def _rutas(app) -> List[Tuple[str, Tuple[str, ...]]]:
    rutas = []
    for ruta in getattr(app, "routes", []):
        camino = getattr(ruta, "path", None)
        metodos = tuple(sorted(getattr(ruta, "methods", None) or ()))
        if camino:
            rutas.append((camino, metodos))
    return rutas


def linea_tiempo(app) -> Optional[str]:
    """La ruta de HC-06 en ``patients.api``, si existe."""
    for camino, metodos in _rutas(app):
        if camino in RUTAS_LINEA_TIEMPO and "GET" in metodos:
            return camino
    return None


def notificaciones(app) -> Dict[str, List[str]]:
    """Rutas de CFG-02 por método (vacío si no existen)."""
    encontradas: Dict[str, List[str]] = {}
    for camino, metodos in _rutas(app):
        if camino == RUTA_NOTIFICACIONES or camino.startswith(RUTA_NOTIFICACIONES + "/"):
            for metodo in metodos:
                encontradas.setdefault(metodo, []).append(camino)
    return encontradas


def estado(app) -> Dict[str, Any]:
    ruta_lt = linea_tiempo(app)
    notif = notificaciones(app)
    return {
        "linea_tiempo": {"disponible": ruta_lt is not None, "historia": "HC-06",
                         "ruta": ruta_lt.replace("{paciente_id}", "{id}") if ruta_lt else None,
                         "campos": CAMPOS_EVENTO},
        "notificaciones": {"disponible": bool(notif.get("GET")), "historia": "CFG-02",
                           "preferencias": RUTA_NOTIFICACIONES + "/preferencias" in notif.get("GET", []),
                           "guardar_preferencias": RUTA_NOTIFICACIONES + "/preferencias" in notif.get("PUT", []),
                           "marcar_leida": any(c.endswith("/leida") for c in notif.get("POST", []))},
    }


def reglas_extra(app):
    """Reglas de la lista cerrada de la pasarela para las rutas de Toro que existan."""
    from frontend.servidor import _Regla
    from seguridad.autorizacion import Accion

    reglas = []
    ruta_lt = linea_tiempo(app)
    if ruta_lt:
        reglas.append(_Regla("GET", re.escape(ruta_lt).replace(re.escape("{paciente_id}"), r"\d+"), Accion.VER_EXPEDIENTE))
    for metodo, caminos in notificaciones(app).items():
        for camino in caminos:
            patron = re.sub(r"\\\{[a-z_]+\\\}", r"[^/]+", re.escape(camino))
            accion = Accion.VER_EXPEDIENTE if metodo == "GET" else Accion.EDITAR_EXPEDIENTE
            reglas.append(_Regla(metodo, patron, accion))
    return tuple(reglas)
