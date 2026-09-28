"""PAC-03 · Resumen 360 del paciente.

Arma en una sola consulta lo que el oncólogo necesita al abrir la
historia: diagnóstico, estadio y tratamiento más reciente (AC1), alertas
activas y acceso rápido a laboratorios, imágenes y notas. Si falta algún
dato clínico clave, lo reporta en `campos_faltantes` (AC2).

Lee las mismas tablas que registro (HC-01) y búsqueda (PAC-02): un
diagnóstico o tratamiento registrado ahí aparece aquí.
"""
from __future__ import annotations

import sqlite3

from .models import AccesoRapido, AlertaActiva, ResumenPaciente360, TratamientoReciente

#: Máximo de entradas por lista de acceso rápido (evitar sobrecarga).
LIMITE_ACCESO_RAPIDO = 5

#: Más urgente primero.
_ORDEN_SEVERIDAD = {"alta": 0, "media": 1, "baja": 2}


class PacienteNoEncontrado(Exception):
    """El id no existe o pertenece a otro oncólogo. No se distinguen los
    dos casos para no confirmar que el registro existe."""

    def __init__(self, paciente_id: int):
        self.paciente_id = paciente_id
        super().__init__(f"No existe un paciente con id {paciente_id}.")


def obtener_resumen_360(
    conn: sqlite3.Connection, paciente_id: int, oncologo_id: int
) -> ResumenPaciente360:
    paciente = conn.execute(
        "SELECT nombre_completo FROM pacientes WHERE id = ? AND oncologo_id = ?",
        (paciente_id, oncologo_id),
    ).fetchone()
    if paciente is None:
        raise PacienteNoEncontrado(paciente_id)

    diagnostico = conn.execute(
        "SELECT descripcion, estadio FROM diagnosticos WHERE paciente_id = ? "
        "ORDER BY fecha DESC, id DESC LIMIT 1",
        (paciente_id,),
    ).fetchone()

    fila_tratamiento = conn.execute(
        "SELECT estado, regimen, fecha_inicio FROM tratamientos WHERE paciente_id = ? "
        "ORDER BY fecha_inicio DESC, id DESC LIMIT 1",
        (paciente_id,),
    ).fetchone()
    tratamiento = TratamientoReciente(**dict(fila_tratamiento)) if fila_tratamiento else None

    alertas = sorted(
        conn.execute(
            "SELECT tipo, severidad, descripcion, fecha FROM alertas "
            "WHERE paciente_id = ? AND resuelta = 0 ORDER BY fecha DESC, id DESC",
            (paciente_id,),
        ).fetchall(),
        key=lambda f: _ORDEN_SEVERIDAD.get(f["severidad"], 99),
    )

    diagnostico_principal = diagnostico["descripcion"] if diagnostico else None
    estadio = diagnostico["estadio"] if diagnostico else None
    campos_clave = {
        "diagnostico_principal": diagnostico_principal,
        "estadio": estadio,
        "tratamiento_mas_reciente": tratamiento,
    }

    return ResumenPaciente360(
        paciente_id=paciente_id,
        nombre=paciente["nombre_completo"],
        diagnostico_principal=diagnostico_principal,
        estadio=estadio,
        tratamiento_mas_reciente=tratamiento,
        alertas_activas=tuple(AlertaActiva(**dict(f)) for f in alertas),
        labs_recientes=_estudios(conn, paciente_id, "laboratorio"),
        imagenes_recientes=_estudios(conn, paciente_id, "imagen"),
        notas_recientes=_notas(conn, paciente_id),
        campos_faltantes=tuple(campo for campo, valor in campos_clave.items() if not valor),
    )


def _estudios(conn: sqlite3.Connection, paciente_id: int, tipo: str) -> tuple[AccesoRapido, ...]:
    filas = conn.execute(
        "SELECT fecha, resumen, nombre FROM estudios WHERE paciente_id = ? AND tipo = ? "
        "ORDER BY fecha DESC, id DESC LIMIT ?",
        (paciente_id, tipo, LIMITE_ACCESO_RAPIDO),
    ).fetchall()
    return tuple(AccesoRapido(fecha=f["fecha"], resumen=f["resumen"], titulo=f["nombre"]) for f in filas)


def _notas(conn: sqlite3.Connection, paciente_id: int) -> tuple[AccesoRapido, ...]:
    filas = conn.execute(
        "SELECT fecha, nota FROM consultas WHERE paciente_id = ? AND nota IS NOT NULL "
        "ORDER BY fecha DESC, id DESC LIMIT ?",
        (paciente_id, LIMITE_ACCESO_RAPIDO),
    ).fetchall()
    return tuple(AccesoRapido(fecha=f["fecha"], resumen=f["nota"]) for f in filas)
