from __future__ import annotations

import sqlite3
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from .models import (
    Paciente,
    Sexo,
    TipoIdentificacion,
    DatosContacto,
    AntecedentesMedicos,
)

SCHEMA_PATH = Path(__file__).parent / "schema_patient.sql"


def inicializar_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def buscar_por_id(conn: sqlite3.Connection, paciente_id: int) -> Optional[Paciente]:
    cur = conn.execute("SELECT * FROM pacientes_identidad WHERE id = ?", (paciente_id,))
    fila = cur.fetchone()
    return _fila_a_paciente(fila) if fila else None


def buscar_por_identificacion(
    conn: sqlite3.Connection,
    tipo_identificacion: TipoIdentificacion,
    numero_identificacion: str,
) -> Optional[Paciente]:
    cur = conn.execute(
        "SELECT * FROM pacientes_identidad WHERE tipo_identificacion = ? AND numero_identificacion = ?",
        (tipo_identificacion.value, numero_identificacion),
    )
    fila = cur.fetchone()
    return _fila_a_paciente(fila) if fila else None


def guardar_paciente(conn: sqlite3.Connection, paciente: Paciente) -> Paciente:
    cur = conn.execute(
        """
        INSERT INTO pacientes_identidad (
            nombre_completo, fecha_nacimiento, sexo, tipo_identificacion,
            numero_identificacion, telefono, email, direccion,
            antecedentes_personales, antecedentes_familiares,
            motivo_consulta_inicial, oncologo_id, registro_completo, fecha_registro
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            paciente.nombre_completo,
            paciente.fecha_nacimiento.isoformat() if paciente.fecha_nacimiento else None,
            paciente.sexo.value,
            paciente.tipo_identificacion.value,
            paciente.numero_identificacion,
            paciente.contacto.telefono,
            paciente.contacto.email,
            paciente.contacto.direccion,
            paciente.antecedentes.personales,
            paciente.antecedentes.familiares,
            paciente.motivo_consulta_inicial,
            paciente.oncologo_id,
            int(paciente.registro_completo),
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    paciente.id = cur.lastrowid
    return paciente


def listar_pacientes_de_oncologo(conn: sqlite3.Connection, oncologo_id: int) -> list:
    cur = conn.execute(
        "SELECT * FROM pacientes_identidad WHERE oncologo_id = ? ORDER BY fecha_registro DESC",
        (oncologo_id,),
    )
    return [_fila_a_paciente(fila) for fila in cur.fetchall()]


def _fila_a_paciente(fila: sqlite3.Row) -> Paciente:
    fecha_nac = date.fromisoformat(fila["fecha_nacimiento"]) if fila["fecha_nacimiento"] else None
    return Paciente(
        id=fila["id"],
        nombre_completo=fila["nombre_completo"],
        fecha_nacimiento=fecha_nac,
        sexo=Sexo(fila["sexo"]),
        tipo_identificacion=TipoIdentificacion(fila["tipo_identificacion"]),
        numero_identificacion=fila["numero_identificacion"],
        contacto=DatosContacto(
            telefono=fila["telefono"], email=fila["email"], direccion=fila["direccion"]
        ),
        antecedentes=AntecedentesMedicos(
            personales=fila["antecedentes_personales"],
            familiares=fila["antecedentes_familiares"],
        ),
        motivo_consulta_inicial=fila["motivo_consulta_inicial"],
        oncologo_id=fila["oncologo_id"],
        registro_completo=bool(fila["registro_completo"]),
    )
