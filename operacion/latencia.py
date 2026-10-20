"""NFR-01 — Medición de los tiempos de respuesta.

Como usuario del sistema, quiero tiempos de respuesta bajos (consultas < 2 s,
generación de notas < 10 s), para que la herramienta no interrumpa mi flujo de
consulta.

``MedicionLatenciaMiddleware`` mide cada petición HTTP y:

    - la agrega a ``RegistroLatencias`` por *plantilla* de ruta
      (``/pacientes/{paciente_id}``, no ``/pacientes/7328``), para no mezclar
      ni guardar ids de pacientes;
    - devuelve ``Server-Timing: app;dur=<ms>``, que el navegador muestra en
      sus herramientas de red.

``RegistroLatencias.resumen()`` da p50/p95/máximo por ruta y si cumple su
objetivo; lo publica ``/salud/metricas`` (``operacion.salud``).
"""

from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from typing import Deque, Dict, Iterable, List, Optional

#: Objetivos de NFR-01, en segundos.
OBJETIVO_CONSULTA_S = 2.0
OBJETIVO_NOTA_S = 10.0
#: Percentil con el que se evalúa el objetivo (el 95 % de las peticiones).
PERCENTIL_OBJETIVO = 95

#: Muestras que se conservan por ruta (las más recientes).
MUESTRAS_POR_RUTA = 2000


def percentil(valores: Iterable[float], p: float) -> float:
    """Percentil por el método del rango más cercano (sin interpolar)."""
    ordenados = sorted(valores)
    if not ordenados:
        return 0.0
    rango = math.ceil(p / 100 * len(ordenados))
    return ordenados[max(0, min(len(ordenados), rango) - 1)]


@dataclass(frozen=True)
class ResumenRuta:
    ruta: str
    peticiones: int
    errores: int
    p50_ms: float
    p95_ms: float
    max_ms: float
    objetivo_ms: float

    @property
    def cumple(self) -> bool:
        return self.p95_ms <= self.objetivo_ms

    def a_dict(self) -> dict:
        return asdict(self) | {"cumple": self.cumple}


class RegistroLatencias:
    """Latencias recientes por ruta, seguro entre hilos."""

    def __init__(self, muestras_por_ruta: int = MUESTRAS_POR_RUTA, objetivos: Optional[Dict[str, float]] = None):
        self._muestras: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=muestras_por_ruta))
        self._errores: Dict[str, int] = defaultdict(int)
        self._cerrojo = threading.Lock()
        #: Objetivo en segundos por prefijo de ruta; el resto, OBJETIVO_CONSULTA_S.
        self.objetivos = dict(objetivos or {})

    def registrar(self, ruta: str, segundos: float, error: bool = False) -> None:
        with self._cerrojo:
            self._muestras[ruta].append(segundos * 1000)
            if error:
                self._errores[ruta] += 1

    def objetivo_ms(self, ruta: str) -> float:
        for prefijo, segundos in self.objetivos.items():
            if ruta.startswith(prefijo):
                return segundos * 1000
        return OBJETIVO_CONSULTA_S * 1000

    def resumen(self) -> List[ResumenRuta]:
        with self._cerrojo:
            copia = {ruta: list(m) for ruta, m in self._muestras.items()}
            errores = dict(self._errores)
        return [
            ResumenRuta(
                ruta=ruta,
                peticiones=len(muestras),
                errores=errores.get(ruta, 0),
                p50_ms=round(percentil(muestras, 50), 1),
                p95_ms=round(percentil(muestras, PERCENTIL_OBJETIVO), 1),
                max_ms=round(max(muestras), 1),
                objetivo_ms=self.objetivo_ms(ruta),
            )
            for ruta, muestras in sorted(copia.items())
        ]

    def limpiar(self) -> None:
        with self._cerrojo:
            self._muestras.clear()
            self._errores.clear()


#: Registro del proceso (cada réplica tiene el suyo).
REGISTRO = RegistroLatencias()


def plantilla_de_ruta(scope: dict) -> str:
    """``/pacientes/7328/resumen-360`` -> ``/pacientes/{paciente_id}/resumen-360``.

    Starlette deja en ``scope["path_params"]`` los parámetros de la ruta que
    resolvió (también dentro de apps montadas). Una ruta que no resolvió
    (404) se agrupa como ``(sin ruta)`` para no crear una entrada por URL.
    """
    parametros = scope.get("path_params") or {}
    if not parametros and scope.get("endpoint") is None:
        return "(sin ruta)"
    partes = scope.get("path", "").split("/")
    valores = {str(v): k for k, v in parametros.items()}
    return "/".join("{" + valores[p] + "}" if p in valores else p for p in partes)


class MedicionLatenciaMiddleware:
    """Mide cada petición HTTP y agrega ``Server-Timing``."""

    def __init__(self, app, registro: Optional[RegistroLatencias] = None):
        self.app = app
        self.registro = registro if registro is not None else REGISTRO

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        inicio = time.perf_counter()
        estado = {"codigo": 500}

        async def enviar(mensaje):
            if mensaje["type"] == "http.response.start":
                estado["codigo"] = mensaje["status"]
                duracion = (time.perf_counter() - inicio) * 1000
                cabeceras = list(mensaje.get("headers") or [])
                cabeceras.append((b"server-timing", f"app;dur={duracion:.1f}".encode("ascii")))
                mensaje = {**mensaje, "headers": cabeceras}
            await send(mensaje)

        try:
            await self.app(scope, receive, enviar)
        finally:
            self.registro.registrar(
                f"{scope.get('method', 'GET')} {plantilla_de_ruta(scope)}",
                time.perf_counter() - inicio,
                error=estado["codigo"] >= 500,
            )
