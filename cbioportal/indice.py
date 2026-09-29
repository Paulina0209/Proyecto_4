"""Índice de un estudio completo + detalle bajo demanda.

Traer el detalle de un paciente cuesta unas 8 llamadas a la API (~5 s), así
que importar un estudio entero de una vez toma horas. Pero el médico no
necesita el detalle de todos: necesita **buscarlos** a todos y ver el
detalle del que abre. Por eso la carga tiene dos partes:

    1. ``importar_indice``: dos llamadas masivas (datos de paciente y de
       muestra de todo el estudio) crean a cada paciente con sus datos
       básicos —sexo, edad, diagnóstico— en el expediente y en la base de
       búsqueda (PAC-02). Toma segundos para decenas de miles de pacientes.
    2. ``CargadorDetalle.asegurar_detalle``: cuando se abre un paciente del
       índice que todavía no tiene detalle, lo trae con el importador de
       siempre (``importador.importar_paciente``, camino de HC-01) y
       completa su resumen 360. La segunda vez que se abre ya es local.

Si la API falla al abrir un paciente, el expediente muestra lo que ya
tiene y el fallo queda en ``sincronizaciones_externas``; se reintenta la
próxima vez que se abra.

La ``fecha_referencia`` del índice se guarda en ``indices_cbioportal``: el
detalle que se cargue días después usa la misma, para que la fecha de
nacimiento del índice y las fechas del detalle sean coherentes.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Dict, Iterable, List, Optional

from .cliente import ClienteCBioPortal
from .importador import FuenteCBioPortal, ResultadoImportacion, importar_paciente
from .mapeo import ficha_paciente, partes_identificacion
from .modulo_pacientes import agregar_detalle, crear_paciente

log = logging.getLogger(__name__)

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS indices_cbioportal (
    estudio TEXT PRIMARY KEY,
    fecha_referencia TEXT NOT NULL,
    pacientes INTEGER NOT NULL,
    fecha_carga TEXT NOT NULL
);
"""

_ATRIBUTOS_PACIENTE = ("GENDER", "SEX", "CURRENT_AGE_DEID", "AGE")
_ATRIBUTOS_MUESTRA = ("CANCER_TYPE", "CANCER_TYPE_DETAILED")


@dataclass(frozen=True)
class ResultadoIndice:
    estudio: str
    #: La guardada en la base (la del primer índice de ese estudio).
    fecha_referencia: date
    pacientes: int
    nuevos_en_expediente: int
    nuevos_en_modulo_pacientes: int


def importar_indice(
    conn: sqlite3.Connection,
    conn_pacientes: sqlite3.Connection,
    cliente: ClienteCBioPortal,
    estudio: str,
    oncologo_id: int,
    fecha_referencia: date,
    tipos: Optional[Iterable[str]] = None,
    por_tipo: Optional[int] = None,
) -> ResultadoIndice:
    """Crea (sin detalle) a los pacientes de ``estudio`` en ambas bases.

    ``tipos``: tipos de cáncer (``CANCER_TYPE``) a incluir; ``None`` = todos.
    Un paciente entra si alguna de sus muestras es de esos tipos.
    ``por_tipo``: tope por tipo (los primeros por id); ``None`` = sin tope.
    Re-ejecutarlo solo agrega los pacientes que falten.
    """
    conn.executescript(_ESQUEMA)
    fecha_referencia = fecha_referencia_de(conn, estudio) or fecha_referencia

    datos_pacientes = cliente.datos_clinicos_estudio(estudio, "PATIENT", _ATRIBUTOS_PACIENTE)
    muestras_por_paciente: Dict[str, List[dict]] = {}
    for muestra_id, datos in sorted(cliente.datos_clinicos_estudio(estudio, "SAMPLE", _ATRIBUTOS_MUESTRA).items()):
        muestras_por_paciente.setdefault(datos["PATIENT_ID"], []).append({"id": muestra_id, "datos": datos})

    elegidos = _seleccionar(muestras_por_paciente, tipos, por_tipo)
    fichas = [
        ficha_paciente(
            {"estudio": estudio, "paciente": p, "datos_paciente": datos_pacientes.get(p, {}),
             "muestras": muestras_por_paciente[p], "eventos": []},
            fecha_referencia,
        )
        for p in elegidos
    ]

    try:
        antes = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO pacientes (nombre, fecha_nacimiento, sexo, identificacion, diagnostico_principal, estadio) "
            "VALUES (?, ?, ?, ?, ?, NULL)",
            [(f.nombre, f.fecha_nacimiento, f.sexo, f.identificacion, f.diagnostico_principal) for f in fichas],
        )
        nuevos_expediente = conn.total_changes - antes
        conn.execute(
            "INSERT INTO indices_cbioportal (estudio, fecha_referencia, pacientes, fecha_carga) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (estudio) DO UPDATE SET pacientes = excluded.pacientes, fecha_carga = excluded.fecha_carga",
            (estudio, fecha_referencia.isoformat(), len(fichas), datetime.now().isoformat()),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    existentes = {
        fila[0] for fila in conn_pacientes.execute(
            "SELECT numero_identificacion FROM pacientes WHERE tipo_identificacion = 'externo'"
        )
    }
    nuevas = [f for f in fichas if f.identificacion not in existentes]
    try:
        for ficha in nuevas:
            crear_paciente(conn_pacientes, ficha, oncologo_id)
        conn_pacientes.commit()
    except Exception:
        conn_pacientes.rollback()
        raise

    return ResultadoIndice(estudio, fecha_referencia, len(fichas), nuevos_expediente, len(nuevas))


def _seleccionar(muestras_por_paciente: Dict[str, List[dict]], tipos, por_tipo) -> List[str]:
    tipos_de = {p: {m["datos"].get("CANCER_TYPE") for m in ms} for p, ms in muestras_por_paciente.items()}
    if tipos is None:
        return sorted(tipos_de)
    elegidos: Dict[str, None] = {}
    for tipo in tipos:
        candidatos = sorted(p for p, t in tipos_de.items() if tipo in t)
        elegidos.update(dict.fromkeys(candidatos[:por_tipo] if por_tipo is not None else candidatos))
    return list(elegidos)


def fecha_referencia_de(conn: sqlite3.Connection, estudio: str) -> Optional[date]:
    conn.executescript(_ESQUEMA)
    fila = conn.execute("SELECT fecha_referencia FROM indices_cbioportal WHERE estudio = ?", (estudio,)).fetchone()
    return date.fromisoformat(fila[0]) if fila else None


def detalle_cargado(conn: sqlite3.Connection, identificacion: str) -> bool:
    """Hay al menos una importación exitosa de cBioPortal para ese paciente."""
    return conn.execute(
        "SELECT 1 FROM sincronizaciones_externas s JOIN pacientes p ON p.id = s.paciente_id "
        "WHERE p.identificacion = ? AND s.fuente = ? AND s.estado = 'exitosa' LIMIT 1",
        (identificacion, FuenteCBioPortal.nombre),
    ).fetchone() is not None


class CargadorDetalle:
    """Trae el detalle de un paciente del índice la primera vez que se abre.

    ``conectar_expediente`` abre una conexión al expediente (se abre y
    cierra en cada carga, para poder usarse desde varios hilos del
    servidor). Hay un candado por paciente: dos pestañas abriendo al mismo
    paciente no lo importan dos veces, y pacientes distintos no se esperan.
    """

    #: Hay un médico esperando: menos espera y menos reintentos que en la CLI.
    TIMEOUT_SEGUNDOS = 20.0
    REINTENTOS = 1

    def __init__(self, conectar_expediente: Callable[[], sqlite3.Connection], cliente: Optional[ClienteCBioPortal] = None):
        self._conectar = conectar_expediente
        self._cliente = cliente or ClienteCBioPortal(timeout=self.TIMEOUT_SEGUNDOS, reintentos=self.REINTENTOS)
        self._fuentes: Dict[date, FuenteCBioPortal] = {}
        self._candados: Dict[str, threading.Lock] = {}
        self._candado_candados = threading.Lock()

    @classmethod
    def desde_ruta(cls, ruta: str, cliente: Optional[ClienteCBioPortal] = None) -> "CargadorDetalle":
        from historia_clinica.db import crear_conexion

        return cls(lambda: crear_conexion(ruta), cliente)

    def asegurar_detalle(self, conn_pacientes: sqlite3.Connection, paciente_id: int) -> Optional[ResultadoImportacion]:
        """``paciente_id`` es el de ``patients/db``. Devuelve ``None`` si no
        había nada que cargar (paciente propio, o detalle ya cargado).
        Nunca lanza: abrir el expediente no puede fallar porque cBioPortal
        no responda."""
        fila = conn_pacientes.execute(
            "SELECT tipo_identificacion, numero_identificacion FROM pacientes WHERE id = ?", (paciente_id,)
        ).fetchone()
        if fila is None or fila[0] != "externo" or not str(fila[1]).startswith("CBIO:"):
            return None
        identificacion = fila[1]
        with self._candado_candados:
            candado = self._candados.setdefault(identificacion, threading.Lock())
        with candado:
            try:
                conn = self._conectar()
            except Exception:  # noqa: BLE001
                log.exception("No se pudo abrir el expediente para cargar %s.", identificacion)
                return None
            try:
                if detalle_cargado(conn, identificacion):
                    return None
                estudio, paciente = partes_identificacion(identificacion)
                fecha = fecha_referencia_de(conn, estudio) or date.today()
                resultado = importar_paciente(conn, self._fuente(fecha), estudio, paciente)
                if resultado.sincronizacion.exito and resultado.contenido is not None:
                    agregar_detalle(conn_pacientes, paciente_id, resultado, fecha)
                else:
                    log.warning("Detalle de %s no disponible: %s", identificacion, resultado.sincronizacion.mensaje)
                return resultado
            except Exception:  # noqa: BLE001
                log.exception("Falló la carga del detalle de %s.", identificacion)
                return None
            finally:
                conn.close()

    def _fuente(self, fecha: date) -> FuenteCBioPortal:
        if fecha not in self._fuentes:
            self._fuentes[fecha] = FuenteCBioPortal(self._cliente, fecha)
        return self._fuentes[fecha]


__all__ = [
    "CargadorDetalle",
    "ResultadoIndice",
    "detalle_cargado",
    "fecha_referencia_de",
    "importar_indice",
]
