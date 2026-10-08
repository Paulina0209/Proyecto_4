"""Puente entre la base del módulo de pacientes y el expediente clínico.

Los laboratorios (HC-02), las biopsias y los biomarcadores (HC-04) viven en
el expediente (``historia_clinica``), que es lo que leen DX, EST, TX e IA.
El módulo de pacientes (PAC-02 búsqueda, PAC-03 resumen 360) tiene su
propia base. Un paciente es el mismo en las dos por su identificación:

    patients.pacientes.numero_identificacion == expediente.pacientes.identificacion

Así ya están vinculados los pacientes de cBioPortal (``CBIO:<estudio>:<id>``).
Un paciente registrado en la plataforma entra al expediente la primera vez
que se le registra un dato clínico (``crear=True``); leer nunca lo crea.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

#: Fecha de nacimiento del expediente cuando el paciente no la tiene (la
#: columna es obligatoria allí); el mapeo de cBioPortal usa el mismo valor.
FECHA_NACIMIENTO_DESCONOCIDA = "desconocida"


def paciente_en_expediente(
    conn_pacientes: sqlite3.Connection,
    conn_expediente: sqlite3.Connection,
    paciente_id: int,
    crear: bool = False,
) -> Optional[int]:
    """Id del paciente en el expediente, o ``None`` si no está (y no se
    pidió crearlo)."""
    fila = conn_pacientes.execute(
        "SELECT nombre_completo, fecha_nacimiento, sexo, numero_identificacion FROM pacientes WHERE id = ?",
        (paciente_id,),
    ).fetchone()
    if fila is None:
        return None
    existente = conn_expediente.execute(
        "SELECT id FROM pacientes WHERE identificacion = ?", (fila["numero_identificacion"],)
    ).fetchone()
    if existente is not None:
        return existente[0]
    if not crear:
        return None

    diagnostico = conn_pacientes.execute(
        "SELECT descripcion, estadio FROM diagnosticos WHERE paciente_id = ? ORDER BY fecha DESC, id DESC LIMIT 1",
        (paciente_id,),
    ).fetchone()
    cursor = conn_expediente.execute(
        "INSERT INTO pacientes (nombre, fecha_nacimiento, sexo, identificacion, diagnostico_principal, estadio) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            fila["nombre_completo"],
            fila["fecha_nacimiento"] or FECHA_NACIMIENTO_DESCONOCIDA,
            fila["sexo"],
            fila["numero_identificacion"],
            diagnostico["descripcion"] if diagnostico else None,
            diagnostico["estadio"] if diagnostico else None,
        ),
    )
    conn_expediente.commit()
    return cursor.lastrowid


def identificacion_coincide(numero_identificacion: str, recibida: str) -> bool:
    """La identificación escrita en la orden de laboratorio corresponde al
    paciente. Para un paciente de cBioPortal basta el id del estudio
    (``P-0000036`` para ``CBIO:msk_chord_2024:P-0000036``), como en
    ``expediente.repository.buscar_paciente_por_identificacion``."""
    recibida = (recibida or "").strip()
    if not recibida:
        return False
    if recibida == numero_identificacion:
        return True
    return numero_identificacion.startswith("CBIO:") and numero_identificacion.endswith(f":{recibida}")
