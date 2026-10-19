"""NFR-02 — Sondas de salud para el balanceador y el monitor de disponibilidad.

    GET /salud/vivo     ¿el proceso responde? Siempre 200 si el proceso está
                        en pie. Es lo que usa el orquestador para reiniciarlo.
                        No lleva datos, así que también se atiende por HTTP
                        (los balanceadores suelen sondear por la red interna).
    GET /salud/listo    ¿puede atender? 200 si todas las verificaciones
                        *críticas* pasan, 503 si alguna falla: el balanceador
                        deja de mandarle tráfico a esta réplica (y se lo manda a
                        las demás, NFR-05) sin reiniciarla.
    GET /salud/metricas latencias por ruta de esta réplica (NFR-01).

Una dependencia externa caída (OpenAI, PACS) no es crítica: el sistema sigue
atendiendo con el borrador por reglas o con lo último sincronizado del PACS, y
la sonda la informa como ``degradado`` sin sacar la réplica de servicio.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from operacion.latencia import REGISTRO, RegistroLatencias

#: Espacio libre mínimo en el disco de las bases: por debajo, SQLite no puede escribir.
ESPACIO_MINIMO_MB = 200

RUTA_VIVO = "/salud/vivo"


class EstadoVerificacion(str, Enum):
    OK = "ok"
    DEGRADADO = "degradado"
    FALLA = "falla"


@dataclass(frozen=True)
class Verificacion:
    nombre: str
    estado: EstadoVerificacion
    detalle: str
    critica: bool = True
    ms: float = 0.0

    def a_dict(self) -> dict:
        return asdict(self) | {"estado": self.estado.value}


def verificar_base(nombre: str, ruta: Path, critica: bool = True) -> Verificacion:
    """Abre la base en solo lectura y hace una consulta (sin crearla si no existe)."""
    inicio = time.perf_counter()
    ruta = Path(ruta)
    if not ruta.is_file():
        return Verificacion(nombre, EstadoVerificacion.FALLA, f"No existe la base {ruta.name}.", critica)
    try:
        conn = sqlite3.connect(f"file:{ruta.as_posix()}?mode=ro", uri=True, timeout=2)
        try:
            tablas = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return Verificacion(nombre, EstadoVerificacion.FALLA, f"No se pudo leer: {exc}", critica,
                            round((time.perf_counter() - inicio) * 1000, 1))
    return Verificacion(nombre, EstadoVerificacion.OK, f"{tablas} tablas", critica,
                        round((time.perf_counter() - inicio) * 1000, 1))


def verificar_espacio(ruta: Path, minimo_mb: int = ESPACIO_MINIMO_MB) -> Verificacion:
    carpeta = Path(ruta)
    while not carpeta.exists() and carpeta != carpeta.parent:
        carpeta = carpeta.parent
    libre_mb = shutil.disk_usage(carpeta).free / 1024 / 1024
    if libre_mb < minimo_mb:
        return Verificacion("espacio en disco", EstadoVerificacion.FALLA, f"{libre_mb:.0f} MB libres (mínimo {minimo_mb}).")
    return Verificacion("espacio en disco", EstadoVerificacion.OK, f"{libre_mb / 1024:.1f} GB libres")


def verificar_modelo_ia() -> Verificacion:
    """Solo configuración (sin llamar a la red en cada sondeo): sin llave, la IA usa el cliente por reglas."""
    from core import llm_config

    if llm_config.obtener_api_key():
        return Verificacion("modelo de IA", EstadoVerificacion.OK, f"{llm_config.obtener_modelo()} configurado", critica=False)
    return Verificacion("modelo de IA", EstadoVerificacion.DEGRADADO,
                        "Sin OPENAI_API_KEY: notas y resúmenes por reglas.", critica=False)


def verificar_pacs() -> Verificacion:
    from historia_clinica.imagenes_pacs import ENV_PACS_URL

    if not os.environ.get(ENV_PACS_URL):
        return Verificacion("PACS", EstadoVerificacion.DEGRADADO,
                            "Sin PACS configurado: se muestran los informes del expediente.", critica=False)
    return Verificacion("PACS", EstadoVerificacion.OK, "Configurado", critica=False)


def estado_general(verificaciones: Sequence[Verificacion]) -> EstadoVerificacion:
    if any(v.critica and v.estado is EstadoVerificacion.FALLA for v in verificaciones):
        return EstadoVerificacion.FALLA
    if any(v.estado is not EstadoVerificacion.OK for v in verificaciones):
        return EstadoVerificacion.DEGRADADO
    return EstadoVerificacion.OK


def crear_router(
    verificaciones: Callable[[], Iterable[Verificacion]],
    registro: Optional[RegistroLatencias] = None,
    instancia: Optional[str] = None,
) -> APIRouter:
    """Router con las tres sondas. ``verificaciones`` se llama en cada ``/salud/listo``."""
    router = APIRouter(prefix="/salud", tags=["NFR-02 salud"])
    registro = registro if registro is not None else REGISTRO
    nombre_instancia = instancia or f"{os.environ.get('COMPUTERNAME') or os.environ.get('HOSTNAME') or 'local'}:{os.getpid()}"

    @router.get("/vivo", summary="NFR-02: el proceso responde")
    def vivo():
        return {"estado": "vivo", "instancia": nombre_instancia}

    @router.get("/listo", summary="NFR-02: la réplica puede atender (503 si no)")
    def listo():
        resultados: List[Verificacion] = list(verificaciones())
        general = estado_general(resultados)
        cuerpo = {
            "estado": general.value,
            "instancia": nombre_instancia,
            "verificaciones": [v.a_dict() for v in resultados],
        }
        return JSONResponse(cuerpo, status_code=503 if general is EstadoVerificacion.FALLA else 200)

    @router.get("/metricas", summary="NFR-01: latencias por ruta de esta réplica")
    def metricas():
        return {"instancia": nombre_instancia, "rutas": [r.a_dict() for r in registro.resumen()]}

    return router
