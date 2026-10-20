"""HC-06 — Línea de tiempo cronológica del paciente.

Como oncólogo, quiero ver una línea de tiempo cronológica de eventos clínicos
del paciente, para entender la evolución del caso de un vistazo.

Reúne en una sola lista, de la más antigua a la más reciente, lo que ya está
registrado en las dos bases:

    - Base de pacientes (HC-01 / PAC-02): diagnósticos, tratamientos,
      consultas y los estudios de acceso rápido del resumen 360.
    - Expediente clínico (HC-02, HC-03, HC-04 y lo importado de sistemas
      externos o de cBioPortal): episodios diagnósticos, biopsias,
      biomarcadores, laboratorios (agrupados por día), informes de imagen,
      estudios del PACS, notas de consulta y antecedentes externos.

Fechas aproximadas (AC2): una fecha guardada solo con mes y año
(``2019-05``) o solo con año (``2019``), como las que traen los
antecedentes FHIR, se marca ``fecha_aproximada`` con su ``precision``
(``mes`` o ``anio``). Un evento sin fecha legible se pone al final con
``precision = "desconocida"``: no se inventa una fecha para ordenarlo.

No guarda nada: es una vista sobre lo registrado.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

#: Tipos de evento (clave -> etiqueta que ve el oncólogo), en el orden del filtro.
TIPOS_EVENTO: Dict[str, str] = {
    "diagnostico": "Diagnóstico",
    "biopsia": "Biopsia",
    "biomarcador": "Biomarcador",
    "estudio_imagen": "Estudio de imagen",
    "laboratorio": "Laboratorio",
    "tratamiento": "Tratamiento",
    "procedimiento": "Procedimiento",
    "consulta": "Consulta",
}

#: Antecedentes externos (FHIR, cBioPortal) según su tipo.
_TIPO_ANTECEDENTE = {"condicion": "diagnostico", "medicacion": "tratamiento", "procedimiento": "procedimiento"}

_ESTADOS_TRATAMIENTO = {
    "en_tratamiento": "en tratamiento",
    "en_seguimiento": "en seguimiento",
    "suspendido": "suspendido",
    "finalizado": "finalizado",
}

#: Resultados de un mismo día que se nombran en el evento de laboratorio; el resto se cuenta.
LABORATORIOS_POR_EVENTO = 6

_DIA = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_MES = re.compile(r"^(\d{4})-(\d{2})$")
_ANIO = re.compile(r"^(\d{4})$")


class TipoEventoDesconocido(ValueError):
    def __init__(self, tipo: str):
        self.tipo = tipo
        super().__init__(f"Tipo de evento desconocido: '{tipo}'. Use uno de: {', '.join(TIPOS_EVENTO)}.")


@dataclass(frozen=True)
class EventoClinico:
    fecha: Optional[str]          # AAAA-MM-DD, AAAA-MM o AAAA según la precisión; None si se desconoce
    precision: str                # dia | mes | anio | desconocida
    fecha_aproximada: bool
    tipo: str                     # clave de TIPOS_EVENTO
    tipo_etiqueta: str
    descripcion: str
    fuente: str                   # de dónde sale el dato (para poder ir a verlo)

    def a_dict(self) -> dict:
        return asdict(self)


def normalizar_fecha(valor: Optional[str]) -> Tuple[Optional[str], str]:
    """``(fecha, precision)`` a partir de lo que esté guardado.

    >>> normalizar_fecha("2024-03-05T10:00:00")
    ('2024-03-05', 'dia')
    >>> normalizar_fecha("2019-05")
    ('2019-05', 'mes')
    >>> normalizar_fecha("desconocida")
    (None, 'desconocida')
    """
    texto = str(valor or "").strip()
    m = _DIA.match(texto)
    if m:
        return m.group(0), "dia"
    if _MES.match(texto):
        return texto, "mes"
    if _ANIO.match(texto):
        return texto, "anio"
    return None, "desconocida"


def _evento(fecha_cruda, tipo: str, descripcion: str, fuente: str) -> EventoClinico:
    fecha, precision = normalizar_fecha(fecha_cruda)
    return EventoClinico(fecha=fecha, precision=precision, fecha_aproximada=precision in ("mes", "anio"),
                         tipo=tipo, tipo_etiqueta=TIPOS_EVENTO[tipo], descripcion=descripcion.strip(), fuente=fuente)


def _tabla_existe(conn: sqlite3.Connection, tabla: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (tabla,)).fetchone() is not None


# ---------------------------------------------------------------------------
# Base de pacientes
# ---------------------------------------------------------------------------

def _de_la_base_de_pacientes(conn: sqlite3.Connection, paciente_id: int, con_laboratorios: bool) -> List[EventoClinico]:
    eventos = []
    for f in conn.execute("SELECT descripcion, estadio, fecha FROM diagnosticos WHERE paciente_id = ?", (paciente_id,)):
        estadio = f" (estadio {f['estadio']})" if f["estadio"] else ""
        eventos.append(_evento(f["fecha"], "diagnostico", f"{f['descripcion']}{estadio}", "diagnosticos"))
    for f in conn.execute("SELECT estado, regimen, fecha_inicio FROM tratamientos WHERE paciente_id = ?", (paciente_id,)):
        estado = _ESTADOS_TRATAMIENTO.get(f["estado"], f["estado"])
        eventos.append(_evento(f["fecha_inicio"], "tratamiento", f"Inicio: {f['regimen'] or 'régimen sin especificar'} ({estado})", "tratamientos"))
    for f in conn.execute("SELECT fecha, nota FROM consultas WHERE paciente_id = ?", (paciente_id,)):
        eventos.append(_evento(f["fecha"], "consulta", f["nota"] or "Consulta sin nota registrada.", "consultas"))
    for f in conn.execute("SELECT tipo, nombre, resumen, fecha FROM estudios WHERE paciente_id = ?", (paciente_id,)):
        if f["tipo"] == "imagen":
            eventos.append(_evento(f["fecha"], "estudio_imagen", f"{f['nombre']}: {f['resumen']}", "estudios"))
        elif con_laboratorios:
            eventos.append(_evento(f["fecha"], "laboratorio", f"{f['nombre']}: {f['resumen']}", "estudios"))
    return eventos


# ---------------------------------------------------------------------------
# Expediente clínico
# ---------------------------------------------------------------------------

def _laboratorios(conn_exp: sqlite3.Connection, expediente_id: int) -> List[EventoClinico]:
    """Un evento por día con laboratorios: la línea de tiempo no se llena con cada valor."""
    criticos = {f[0] for f in conn_exp.execute(
        "SELECT laboratorio_id FROM alertas_laboratorio WHERE paciente_id = ?", (expediente_id,))} \
        if _tabla_existe(conn_exp, "alertas_laboratorio") else set()
    por_dia: Dict[str, List[sqlite3.Row]] = {}
    for f in conn_exp.execute("SELECT id, fecha, prueba, valor, unidad, alterado FROM laboratorios WHERE paciente_id = ? "
                              "ORDER BY fecha, id", (expediente_id,)):
        por_dia.setdefault(f["fecha"], []).append(f)
    eventos = []
    for dia, filas in por_dia.items():
        # Primero lo crítico y lo fuera de rango: es lo que no debe quedar en el «y N más».
        filas = sorted(filas, key=lambda f: (f["id"] not in criticos, not f["alterado"]))
        textos = []
        for f in filas[:LABORATORIOS_POR_EVENTO]:
            marca = " (crítico)" if f["id"] in criticos else " (fuera de rango)" if f["alterado"] else ""
            textos.append(f"{f['prueba']} {f['valor']} {f['unidad'] or ''}".strip() + marca)
        resto = len(filas) - len(textos)
        cuantos = f"{len(filas)} resultado" + ("s" if len(filas) != 1 else "")
        eventos.append(_evento(dia, "laboratorio", f"{cuantos}: " + "; ".join(textos) + (f"; y {resto} más" if resto else ""),
                               "laboratorios"))
    return eventos


def _del_expediente(conn_exp: sqlite3.Connection, expediente_id: int) -> List[EventoClinico]:
    eventos: List[EventoClinico] = []

    def filas(tabla: str, sql: str) -> Iterable[sqlite3.Row]:
        return conn_exp.execute(sql, (expediente_id,)) if _tabla_existe(conn_exp, tabla) else ()

    for f in filas("episodios_diagnosticos", "SELECT descripcion, tipo_cancer, fecha_diagnostico FROM episodios_diagnosticos WHERE paciente_id = ?"):
        tipo = f" ({f['tipo_cancer']})" if f["tipo_cancer"] else ""
        eventos.append(_evento(f["fecha_diagnostico"], "diagnostico", f"Episodio diagnóstico: {f['descripcion']}{tipo}", "episodios"))
    for f in filas("biopsias", "SELECT fecha, sitio, procedimiento, diagnostico_histologico FROM biopsias WHERE paciente_id = ?"):
        resultado = f": {f['diagnostico_histologico']}" if f["diagnostico_histologico"] else ""
        eventos.append(_evento(f["fecha"], "biopsia", f"{f['procedimiento']} ({f['sitio']}){resultado}", "biopsias"))
    for f in filas("biomarcadores", "SELECT fecha, biomarcador, resultado FROM biomarcadores WHERE paciente_id = ?"):
        eventos.append(_evento(f["fecha"], "biomarcador", f"{f['biomarcador']}: {f['resultado']}", "biomarcadores"))
    for f in filas("imagenologia", "SELECT fecha, modalidad, region, hallazgos FROM imagenologia WHERE paciente_id = ?"):
        eventos.append(_evento(f["fecha"], "estudio_imagen", f"{f['modalidad']} de {f['region']}: {f['hallazgos']}", "imagenologia"))
    for f in filas("estudios_pacs", "SELECT fecha, modalidad, descripcion FROM estudios_pacs WHERE paciente_id = ? AND imagenologia_id IS NULL"):
        eventos.append(_evento(f["fecha"], "estudio_imagen",
                               f"{f['descripcion'] or 'Estudio sin descripción'} ({f['modalidad'] or 'modalidad no indicada'}, PACS)", "pacs"))
    for f in filas("consultas", "SELECT fecha, motivo, notas_libres FROM consultas WHERE paciente_id = ?"):
        eventos.append(_evento(f["fecha"], "consulta", f"{f['motivo']}: {f['notas_libres']}", "notas_consulta"))
    for f in filas("antecedentes_externos", "SELECT tipo, descripcion, fecha, fuente FROM antecedentes_externos WHERE paciente_id = ?"):
        eventos.append(_evento(f["fecha"], _TIPO_ANTECEDENTE.get(f["tipo"], "procedimiento"),
                               f"{f['descripcion']} (fuente externa: {f['fuente']})", "antecedentes_externos"))
    if _tabla_existe(conn_exp, "laboratorios"):
        eventos += _laboratorios(conn_exp, expediente_id)
    return eventos


# ---------------------------------------------------------------------------
# La línea de tiempo
# ---------------------------------------------------------------------------

#: Para no duplicar lo mismo visto desde dos lugares (p. ej. el informe de una imagen y su estudio en el
#: PACS, o el diagnóstico de la ficha y su episodio en el expediente), estas fuentes ceden ante las
#: primeras cuando coinciden tipo y fecha.
_FUENTES_SECUNDARIAS = {"pacs": ("imagenologia",), "estudios": ("imagenologia", "pacs"),
                        "episodios": ("diagnosticos",), "antecedentes_externos": ("diagnosticos", "episodios")}


def _sin_duplicados(eventos: Sequence[EventoClinico]) -> List[EventoClinico]:
    vistos = {(e.fuente, e.tipo, e.fecha) for e in eventos if e.fecha}
    return [e for e in eventos
            if not (e.fecha and any((otra, e.tipo, e.fecha) in vistos for otra in _FUENTES_SECUNDARIAS.get(e.fuente, ())))]


def _orden(e: EventoClinico):
    # Sin fecha, al final. «2019-05» va antes que «2019-05-10»: se sabe menos de él, no que sea posterior.
    return (e.fecha is None, e.fecha or "", list(TIPOS_EVENTO).index(e.tipo))


def linea_de_tiempo(
    conn_pacientes: sqlite3.Connection,
    paciente_id: int,
    conn_expediente: Optional[sqlite3.Connection] = None,
    expediente_id: Optional[int] = None,
    tipos: Optional[Iterable[str]] = None,
) -> List[EventoClinico]:
    """Eventos del paciente, del más antiguo al más reciente (los sin fecha al final).

    ``tipos`` filtra por clave de ``TIPOS_EVENTO`` (AC1); un tipo desconocido es un error,
    no un filtro que deja la lista vacía sin decir por qué."""
    filtro = None
    if tipos is not None:
        filtro = {t.strip() for t in tipos if t and t.strip()}
        for t in filtro:
            if t not in TIPOS_EVENTO:
                raise TipoEventoDesconocido(t)
    eventos: List[EventoClinico] = []
    hay_labs_en_expediente = False
    if conn_expediente is not None and expediente_id is not None:
        eventos += _del_expediente(conn_expediente, expediente_id)
        hay_labs_en_expediente = any(e.fuente == "laboratorios" for e in eventos)
    # Como el resumen 360: los laboratorios de acceso rápido solo si el expediente no tiene los suyos.
    eventos += _de_la_base_de_pacientes(conn_pacientes, paciente_id, con_laboratorios=not hay_labs_en_expediente)
    eventos = _sin_duplicados(eventos)
    if filtro:
        eventos = [e for e in eventos if e.tipo in filtro]
    return sorted(eventos, key=_orden)
