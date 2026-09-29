"""Escritura en el expediente de lo que documenta el oncólogo.

cBioPortal trae el historial (diagnóstico, biomarcadores, laboratorios,
imágenes, tratamientos), pero no las notas de consulta ni las variables
que requieren juicio clínico (T/N/M, entorno de la enfermedad, PD-L1 TPS,
línea de tratamiento…). Esas las registra el oncólogo con estas funciones,
y a partir de ahí las leen IA-02 (nota de la consulta), EST y TX.

Nada se sobrescribe: cada registro es una fila nueva con su fecha, y los
lectores usan el valor más reciente de cada variable.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Mapping, Optional

from expediente.repository import obtener_paciente


class PacienteInexistenteError(ValueError):
    """El paciente no existe en el expediente."""


def _verificar_paciente(conn: sqlite3.Connection, paciente_id: int) -> None:
    if obtener_paciente(conn, paciente_id) is None:
        raise PacienteInexistenteError(f"No existe el paciente {paciente_id} en el expediente.")


def registrar_consulta(
    conn: sqlite3.Connection,
    paciente_id: int,
    motivo: str,
    notas_libres: str,
    fecha: Optional[date] = None,
) -> int:
    """Guarda la nota de una consulta y devuelve su id (entrada de IA-02)."""
    _verificar_paciente(conn, paciente_id)
    if not motivo.strip() or not notas_libres.strip():
        raise ValueError("El motivo y las notas de la consulta son obligatorios.")
    cur = conn.execute(
        "INSERT INTO consultas (paciente_id, fecha, motivo, notas_libres) VALUES (?, ?, ?, ?)",
        (paciente_id, (fecha or date.today()).isoformat(), motivo.strip(), notas_libres.strip()),
    )
    conn.commit()
    return cur.lastrowid


def registrar_datos_clinicos(
    conn: sqlite3.Connection,
    paciente_id: int,
    datos: Mapping[str, object],
    fecha: Optional[date] = None,
    consulta_id: Optional[int] = None,
) -> list[int]:
    """Registra variables clínicas estructuradas (p. ej. ``clinical_t_category``,
    ``pdl1_tps``, ``treatment_line``) y devuelve los ids de las filas."""
    _verificar_paciente(conn, paciente_id)
    if not datos:
        raise ValueError("No hay datos para registrar.")
    dia = (fecha or date.today()).isoformat()
    ids = []
    for variable, valor in datos.items():
        if not str(variable).strip() or valor is None or str(valor).strip() == "":
            raise ValueError(f"Variable o valor vacío: {variable!r}={valor!r}.")
        cur = conn.execute(
            "INSERT INTO datos_clinicos_estructurados (paciente_id, consulta_id, fecha, variable, valor) "
            "VALUES (?, ?, ?, ?, ?)",
            (paciente_id, consulta_id, dia, str(variable).strip(), str(valor).strip()),
        )
        ids.append(cur.lastrowid)
    conn.commit()
    return ids


def registrar_comorbilidad(
    conn: sqlite3.Connection,
    paciente_id: int,
    condicion: str,
    severidad: Optional[str] = None,
    tipo_contraindicacion_ici: Optional[str] = None,
    fecha: Optional[date] = None,
    consulta_id: Optional[int] = None,
) -> int:
    """Registra una comorbilidad. ``tipo_contraindicacion_ici`` es el juicio
    del oncólogo (``"immediate"`` | ``"absolute"`` | None)."""
    _verificar_paciente(conn, paciente_id)
    if tipo_contraindicacion_ici not in (None, "immediate", "absolute"):
        raise ValueError("tipo_contraindicacion_ici debe ser 'immediate', 'absolute' o None.")
    cur = conn.execute(
        "INSERT INTO comorbilidades (paciente_id, consulta_id, fecha_registro, condicion, severidad, "
        "tipo_contraindicacion_ici) VALUES (?, ?, ?, ?, ?, ?)",
        (paciente_id, consulta_id, (fecha or date.today()).isoformat(), condicion.strip(), severidad,
         tipo_contraindicacion_ici),
    )
    conn.commit()
    return cur.lastrowid
