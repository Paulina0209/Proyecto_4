"""Consultas de lectura sobre la base de datos mock de historia clínica."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class Paciente:
    id: int
    nombre: str
    fecha_nacimiento: str
    sexo: str
    identificacion: str
    diagnostico_principal: Optional[str]
    estadio: Optional[str]


@dataclass(frozen=True)
class Consulta:
    id: int
    paciente_id: int
    fecha: str
    motivo: str
    notas_libres: str


@dataclass(frozen=True)
class ResultadoLaboratorio:
    id: int
    paciente_id: int
    consulta_id: Optional[int]
    fecha: str
    prueba: str
    valor: str
    unidad: Optional[str]
    rango_referencia: Optional[str]
    alterado: bool


@dataclass(frozen=True)
class EstudioImagenologico:
    id: int
    paciente_id: int
    consulta_id: Optional[int]
    fecha: str
    modalidad: str
    region: str
    hallazgos: str


@dataclass(frozen=True)
class Biomarcador:
    id: int
    paciente_id: int
    consulta_id: Optional[int]
    fecha: str
    biomarcador: str
    resultado: str


@dataclass(frozen=True)
class HallazgoClinico:
    """Un hecho clínico atómico y trazable del expediente de un paciente.

    Es el "hecho" mínimo que consumen los módulos que razonan sobre el
    expediente completo de un paciente (por ejemplo, ``dx_clinica`` para
    el diagnóstico diferencial), a diferencia de ``SourceSpan`` de
    ``ia_clinica.notes``, que está acotado a una sola consulta. El ``id``
    conserva el prefijo del registro de origen (``lab-3``, ``imagen-2``,
    ``biomarcador-1``, ``consulta-1-nota-4``) para que cualquier hallazgo
    usado corriente abajo se pueda trazar hasta la fila exacta de la base
    de datos.
    """

    id: str
    paciente_id: int
    origen: str  # "consulta" | "laboratorio" | "imagenologia" | "biomarcador"
    texto: str
    fecha: str


def listar_pacientes(conn: sqlite3.Connection) -> List[Paciente]:
    """Lista los pacientes sintéticos disponibles para demos y pruebas."""
    rows = conn.execute("SELECT * FROM pacientes ORDER BY id").fetchall()
    return [_fila_a_paciente(row) for row in rows]


def obtener_paciente(conn: sqlite3.Connection, paciente_id: int) -> Optional[Paciente]:
    row = conn.execute("SELECT * FROM pacientes WHERE id = ?", (paciente_id,)).fetchone()
    return _fila_a_paciente(row) if row else None


def listar_consultas(conn: sqlite3.Connection, paciente_id: int) -> List[Consulta]:
    rows = conn.execute(
        "SELECT * FROM consultas WHERE paciente_id = ? ORDER BY fecha", (paciente_id,)
    ).fetchall()
    return [_fila_a_consulta(row) for row in rows]


def obtener_consulta(conn: sqlite3.Connection, consulta_id: int) -> Optional[Consulta]:
    row = conn.execute("SELECT * FROM consultas WHERE id = ?", (consulta_id,)).fetchone()
    return _fila_a_consulta(row) if row else None


def laboratorios_de_consulta(conn: sqlite3.Connection, consulta_id: int) -> List[ResultadoLaboratorio]:
    rows = conn.execute(
        "SELECT * FROM laboratorios WHERE consulta_id = ? ORDER BY id", (consulta_id,)
    ).fetchall()
    return [_fila_a_laboratorio(row) for row in rows]


def imagenologia_de_consulta(conn: sqlite3.Connection, consulta_id: int) -> List[EstudioImagenologico]:
    rows = conn.execute(
        "SELECT * FROM imagenologia WHERE consulta_id = ? ORDER BY id", (consulta_id,)
    ).fetchall()
    return [_fila_a_imagenologia(row) for row in rows]


def biomarcadores_de_consulta(conn: sqlite3.Connection, consulta_id: int) -> List[Biomarcador]:
    rows = conn.execute(
        "SELECT * FROM biomarcadores WHERE consulta_id = ? ORDER BY id", (consulta_id,)
    ).fetchall()
    return [_fila_a_biomarcador(row) for row in rows]


# -- Consultas a nivel de todo el paciente (no acotadas a una consulta) -----
#
# IA-02 necesita solo lo "de esta consulta puntual". DX-02, en cambio,
# necesita combinar todos los datos clínicos disponibles del expediente
# (observación técnica: "combinar los datos clínicos recuperados del
# expediente"), así que estas funciones no filtran por consulta_id.


def laboratorios_de_paciente(conn: sqlite3.Connection, paciente_id: int) -> List[ResultadoLaboratorio]:
    rows = conn.execute(
        "SELECT * FROM laboratorios WHERE paciente_id = ? ORDER BY fecha", (paciente_id,)
    ).fetchall()
    return [_fila_a_laboratorio(row) for row in rows]


def imagenologia_de_paciente(conn: sqlite3.Connection, paciente_id: int) -> List[EstudioImagenologico]:
    rows = conn.execute(
        "SELECT * FROM imagenologia WHERE paciente_id = ? ORDER BY fecha", (paciente_id,)
    ).fetchall()
    return [_fila_a_imagenologia(row) for row in rows]


def biomarcadores_de_paciente(conn: sqlite3.Connection, paciente_id: int) -> List[Biomarcador]:
    rows = conn.execute(
        "SELECT * FROM biomarcadores WHERE paciente_id = ? ORDER BY fecha", (paciente_id,)
    ).fetchall()
    return [_fila_a_biomarcador(row) for row in rows]


# -- Conversión de filas sqlite3.Row a dataclasses --------------------------


def _fila_a_paciente(row: sqlite3.Row) -> Paciente:
    return Paciente(
        id=row["id"],
        nombre=row["nombre"],
        fecha_nacimiento=row["fecha_nacimiento"],
        sexo=row["sexo"],
        identificacion=row["identificacion"],
        diagnostico_principal=row["diagnostico_principal"],
        estadio=row["estadio"],
    )


def _fila_a_consulta(row: sqlite3.Row) -> Consulta:
    return Consulta(
        id=row["id"],
        paciente_id=row["paciente_id"],
        fecha=row["fecha"],
        motivo=row["motivo"],
        notas_libres=row["notas_libres"],
    )


def _fila_a_laboratorio(row: sqlite3.Row) -> ResultadoLaboratorio:
    return ResultadoLaboratorio(
        id=row["id"],
        paciente_id=row["paciente_id"],
        consulta_id=row["consulta_id"],
        fecha=row["fecha"],
        prueba=row["prueba"],
        valor=row["valor"],
        unidad=row["unidad"],
        rango_referencia=row["rango_referencia"],
        alterado=bool(row["alterado"]),
    )


def _fila_a_imagenologia(row: sqlite3.Row) -> EstudioImagenologico:
    return EstudioImagenologico(
        id=row["id"],
        paciente_id=row["paciente_id"],
        consulta_id=row["consulta_id"],
        fecha=row["fecha"],
        modalidad=row["modalidad"],
        region=row["region"],
        hallazgos=row["hallazgos"],
    )


def _fila_a_biomarcador(row: sqlite3.Row) -> Biomarcador:
    return Biomarcador(
        id=row["id"],
        paciente_id=row["paciente_id"],
        consulta_id=row["consulta_id"],
        fecha=row["fecha"],
        biomarcador=row["biomarcador"],
        resultado=row["resultado"],
    )
