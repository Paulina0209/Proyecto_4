"""Órdenes médicas de medicamentos: lo que el oncólogo prescribe y enfermería suministra.

Cada orden dice qué medicamento, qué dosis, por qué vía, cada cuánto y desde cuándo. De ahí sale el
horario de administración (las dosis programadas de un periodo), que es lo que enfermería consulta.

    - Solo el oncólogo prescribe o suspende (``Accion.PRESCRIBIR_MEDICAMENTO``); enfermería las consulta.
    - Una orden no se edita ni se borra: se suspende con motivo y, si hace falta, se prescribe otra.
      Así queda la historia completa de lo que se indicó y cuándo cambió.
    - Puede venir de la decisión de tratamiento del oncólogo (TX-04): se guarda el vínculo.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

VIAS = {"VO": "Oral", "IV": "Intravenosa", "SC": "Subcutánea", "IM": "Intramuscular", "TOP": "Tópica", "INH": "Inhalada", "SL": "Sublingual"}
#: Frecuencias que ofrece la interfaz (horas entre dosis; 0 = dosis única).
FRECUENCIAS = {0: "Dosis única", 4: "Cada 4 horas", 6: "Cada 6 horas", 8: "Cada 8 horas", 12: "Cada 12 horas", 24: "Cada 24 horas",
               168: "Cada 7 días", 336: "Cada 14 días", 504: "Cada 21 días", 672: "Cada 28 días", 1008: "Cada 42 días"}
_HORA = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS ordenes_medicamento (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente_id INTEGER NOT NULL,
    medicamento TEXT NOT NULL,
    dosis TEXT NOT NULL,
    via TEXT NOT NULL,
    intervalo_horas INTEGER NOT NULL,
    fecha_inicio TEXT NOT NULL,
    hora_inicio TEXT NOT NULL,
    fecha_fin TEXT,
    indicaciones TEXT,
    decision_id INTEGER,
    ordenado_por TEXT NOT NULL,
    ordenado_en TEXT NOT NULL,
    suspendida_por TEXT,
    suspendida_en TEXT,
    motivo_suspension TEXT
);
CREATE INDEX IF NOT EXISTS idx_ordenes_paciente ON ordenes_medicamento(paciente_id);
"""


class ErrorOrden(Exception):
    """Datos inválidos: ``errores`` trae todos a la vez, ``(campo, mensaje)``."""

    def __init__(self, errores: List[Tuple[str, str]]):
        self.errores = errores
        super().__init__("; ".join(m for _c, m in errores))


@dataclass(frozen=True)
class OrdenMedicamento:
    id: int
    paciente_id: int
    medicamento: str
    dosis: str
    via: str
    intervalo_horas: int
    fecha_inicio: str
    hora_inicio: str
    fecha_fin: Optional[str]
    indicaciones: Optional[str]
    decision_id: Optional[int]
    ordenado_por: str
    ordenado_en: str
    suspendida_por: Optional[str]
    suspendida_en: Optional[str]
    motivo_suspension: Optional[str]

    @property
    def activa(self) -> bool:
        return self.suspendida_en is None and (self.fecha_fin is None or self.fecha_fin >= date.today().isoformat())

    @property
    def frecuencia(self) -> str:
        return FRECUENCIAS.get(self.intervalo_horas) or f"Cada {self.intervalo_horas} horas"

    @property
    def via_etiqueta(self) -> str:
        return VIAS.get(self.via, self.via)

    def texto(self) -> str:
        """Una línea legible (la usa el asistente como fuente citable)."""
        partes = [f"Orden médica: {self.medicamento} {self.dosis}, vía {self.via_etiqueta.lower()}, {self.frecuencia.lower()}",
                  f"desde el {self.fecha_inicio} a las {self.hora_inicio}"]
        if self.fecha_fin:
            partes.append(f"hasta el {self.fecha_fin}")
        if self.indicaciones:
            partes.append(f"indicaciones: {self.indicaciones}")
        partes.append(f"ordenada por {self.ordenado_por}")
        if self.suspendida_en:
            partes.append(f"SUSPENDIDA el {self.suspendida_en[:10]} ({self.motivo_suspension})")
        return "; ".join(partes) + "."

    def a_dict(self) -> Dict[str, object]:
        return {**asdict(self), "activa": self.activa, "frecuencia": self.frecuencia, "via_etiqueta": self.via_etiqueta}


@dataclass(frozen=True)
class DosisProgramada:
    orden_id: int
    paciente_id: int
    medicamento: str
    dosis: str
    via: str
    momento: str  # ISO local, sin zona: el horario de la institución

    def a_dict(self) -> Dict[str, object]:
        return asdict(self)


def inicializar_esquema(conn: sqlite3.Connection) -> None:
    conn.executescript(_ESQUEMA)
    conn.commit()


def _fila(fila) -> OrdenMedicamento:
    return OrdenMedicamento(*fila)


_COLUMNAS = ("id, paciente_id, medicamento, dosis, via, intervalo_horas, fecha_inicio, hora_inicio, fecha_fin, indicaciones, "
             "decision_id, ordenado_por, ordenado_en, suspendida_por, suspendida_en, motivo_suspension")


def prescribir(conn: sqlite3.Connection, paciente_id: int, *, medicamento: str, dosis: str, via: str, intervalo_horas: int,
               fecha_inicio: str, hora_inicio: str, ordenado_por: str, fecha_fin: Optional[str] = None,
               indicaciones: Optional[str] = None, decision_id: Optional[int] = None,
               ahora: Optional[datetime] = None) -> OrdenMedicamento:
    inicializar_esquema(conn)
    errores: List[Tuple[str, str]] = []
    medicamento = " ".join((medicamento or "").split())
    dosis = " ".join((dosis or "").split())
    if not 2 <= len(medicamento) <= 120:
        errores.append(("medicamento", "Escribe el medicamento."))
    if not dosis or not re.search(r"\d", dosis):
        errores.append(("dosis", "La dosis debe incluir cantidad y unidad, por ejemplo 200 mg."))
    via = (via or "").upper()
    if via not in VIAS:
        errores.append(("via", f"Vía desconocida. Opciones: {', '.join(VIAS)}."))
    try:
        intervalo = int(intervalo_horas)
    except (TypeError, ValueError):
        intervalo = -1
    if intervalo < 0 or intervalo > 24 * 90:
        errores.append(("intervalo_horas", "Elige la frecuencia."))
    try:
        inicio = date.fromisoformat(str(fecha_inicio))
    except ValueError:
        inicio = None
        errores.append(("fecha_inicio", "Indica la fecha de inicio."))
    if not _HORA.match(str(hora_inicio or "")):
        errores.append(("hora_inicio", "La hora de inicio va en formato HH:MM (24 horas)."))
    fin = None
    if fecha_fin:
        try:
            fin = date.fromisoformat(str(fecha_fin))
        except ValueError:
            errores.append(("fecha_fin", "La fecha de fin no es válida."))
        else:
            if inicio and fin < inicio:
                errores.append(("fecha_fin", "La fecha de fin no puede ser anterior al inicio."))
    if errores:
        raise ErrorOrden(errores)
    cursor = conn.execute(
        "INSERT INTO ordenes_medicamento (paciente_id, medicamento, dosis, via, intervalo_horas, fecha_inicio, hora_inicio, fecha_fin, "
        "indicaciones, decision_id, ordenado_por, ordenado_en) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (paciente_id, medicamento, dosis, via, intervalo, inicio.isoformat(), hora_inicio, fin.isoformat() if fin else None,
         (indicaciones or "").strip() or None, decision_id, ordenado_por, (ahora or datetime.now(timezone.utc)).isoformat()))
    conn.commit()
    return obtener(conn, paciente_id, cursor.lastrowid)


def suspender(conn: sqlite3.Connection, paciente_id: int, orden_id: int, *, suspendida_por: str, motivo: str,
              ahora: Optional[datetime] = None) -> OrdenMedicamento:
    orden = obtener(conn, paciente_id, orden_id)
    if orden is None:
        raise ErrorOrden([("orden_id", "Esa orden no es de este paciente.")])
    if orden.suspendida_en:
        raise ErrorOrden([("orden_id", "La orden ya estaba suspendida.")])
    motivo = " ".join((motivo or "").split())
    if not motivo:
        raise ErrorOrden([("motivo", "El motivo de la suspensión es obligatorio.")])
    conn.execute("UPDATE ordenes_medicamento SET suspendida_por = ?, suspendida_en = ?, motivo_suspension = ? WHERE id = ?",
                 (suspendida_por, (ahora or datetime.now(timezone.utc)).isoformat(), motivo, orden_id))
    conn.commit()
    return obtener(conn, paciente_id, orden_id)


def obtener(conn: sqlite3.Connection, paciente_id: int, orden_id: int) -> Optional[OrdenMedicamento]:
    inicializar_esquema(conn)
    fila = conn.execute(f"SELECT {_COLUMNAS} FROM ordenes_medicamento WHERE id = ? AND paciente_id = ?", (orden_id, paciente_id)).fetchone()
    return _fila(fila) if fila else None


def ordenes_de(conn: sqlite3.Connection, paciente_id: int) -> List[OrdenMedicamento]:
    """Todas las órdenes del paciente: las vigentes primero, luego el historial."""
    inicializar_esquema(conn)
    filas = [_fila(f) for f in conn.execute(f"SELECT {_COLUMNAS} FROM ordenes_medicamento WHERE paciente_id = ? ORDER BY id DESC", (paciente_id,))]
    return sorted(filas, key=lambda o: not o.activa)


def dosis_programadas(ordenes: Iterable[OrdenMedicamento], desde: datetime, hasta: datetime) -> List[DosisProgramada]:
    """Las administraciones que tocan en [desde, hasta), en orden cronológico."""
    resultado: List[DosisProgramada] = []
    for o in ordenes:
        if o.suspendida_en and o.suspendida_en[:10] <= desde.date().isoformat():
            continue
        h, m = (int(x) for x in o.hora_inicio.split(":"))
        momento = datetime.combine(date.fromisoformat(o.fecha_inicio), time(h, m))
        limite = hasta
        if o.fecha_fin:
            limite = min(limite, datetime.combine(date.fromisoformat(o.fecha_fin), time(23, 59, 59)))
        if o.suspendida_en:
            limite = min(limite, datetime.fromisoformat(o.suspendida_en[:19]))
        if o.intervalo_horas == 0:
            candidatos: Sequence[datetime] = [momento]
        else:
            paso = timedelta(hours=o.intervalo_horas)
            if momento < desde:  # salta directo a la primera dosis del periodo
                momento += paso * ((desde - momento) // paso)
            candidatos = []
            while momento < limite and len(candidatos) < 200:
                candidatos.append(momento)
                momento += paso
        for c in candidatos:
            if desde <= c < limite:
                resultado.append(DosisProgramada(o.id, o.paciente_id, o.medicamento, o.dosis, o.via, c.isoformat(timespec="minutes")))
    return sorted(resultado, key=lambda d: (d.momento, d.medicamento))


def horario(conn: sqlite3.Connection, paciente_ids: Sequence[int], desde: Optional[datetime] = None, horas: int = 24) -> List[DosisProgramada]:
    """El horario de administración de varios pacientes (por defecto, las próximas 24 horas)."""
    inicializar_esquema(conn)
    desde = desde or datetime.now().replace(minute=0, second=0, microsecond=0)
    ordenes = [o for pid in paciente_ids for o in ordenes_de(conn, pid)]
    return dosis_programadas(ordenes, desde, desde + timedelta(hours=horas))
