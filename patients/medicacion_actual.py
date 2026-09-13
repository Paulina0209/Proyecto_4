"""Fragmento para pegar dentro de pacientes_clinica/ (mismo paquete que
models.py, validacion.py, repository.py de HC-01). Se deja como un solo
archivo aquí por conveniencia de entrega; al integrarlo, lo natural es
repartir esto entre esos tres archivos existentes, siguiendo la misma
separación que ya tienen.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional


def inicializar_schema(conn: sqlite3.Connection) -> None:
    """Crea medicacion_actual y conciliacion_medicamentos si no existen.
    Ver schema_extension_medicacion.sql para la copia documental."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS medicacion_actual (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente_id INTEGER NOT NULL,
            medicamento TEXT NOT NULL,
            dosis TEXT,
            frecuencia TEXT,
            indicacion TEXT,
            fecha_inicio TEXT,
            fecha_fin TEXT,
            registrado_por INTEGER NOT NULL,
            fecha_registro TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_medicacion_actual_paciente ON medicacion_actual(paciente_id)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conciliacion_medicamentos (
            paciente_id INTEGER PRIMARY KEY,
            estado TEXT NOT NULL DEFAULT 'no_realizada',
            fecha TEXT,
            registrado_por INTEGER
        )
        """
    )
    conn.commit()


# ---- models.py -------------------------------------------------------

@dataclass
class MedicacionActual:
    paciente_id: int
    medicamento: str
    registrado_por: int
    fecha_registro: str
    dosis: Optional[str] = None
    frecuencia: Optional[str] = None
    indicacion: Optional[str] = None
    fecha_inicio: Optional[str] = None
    fecha_fin: Optional[str] = None  # None = activo
    id: Optional[int] = None

    @property
    def activo(self) -> bool:
        return self.fecha_fin is None


# ---- validacion.py -----------------------------------------------------

@dataclass
class ErrorValidacionMedicacion:
    campo: str
    mensaje: str


def validar_medicacion(medicacion: MedicacionActual) -> list[ErrorValidacionMedicacion]:
    errores = []
    if not medicacion.medicamento or not medicacion.medicamento.strip():
        errores.append(ErrorValidacionMedicacion("medicamento", "El medicamento es obligatorio"))
    if not medicacion.paciente_id:
        errores.append(ErrorValidacionMedicacion("paciente_id", "Falta el paciente"))
    if not medicacion.registrado_por:
        errores.append(
            ErrorValidacionMedicacion("registrado_por", "Falta quién registra la medicación")
        )
    return errores


# ---- repository.py -----------------------------------------------------

def agregar_medicacion(conn: sqlite3.Connection, medicacion: MedicacionActual) -> MedicacionActual:
    cursor = conn.execute(
        """
        INSERT INTO medicacion_actual
            (paciente_id, medicamento, dosis, frecuencia, indicacion,
             fecha_inicio, fecha_fin, registrado_por, fecha_registro)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            medicacion.paciente_id,
            medicacion.medicamento,
            medicacion.dosis,
            medicacion.frecuencia,
            medicacion.indicacion,
            medicacion.fecha_inicio,
            medicacion.fecha_fin,
            medicacion.registrado_por,
            medicacion.fecha_registro,
        ),
    )
    conn.commit()
    medicacion.id = cursor.lastrowid
    return medicacion


def listar_medicacion_activa(conn: sqlite3.Connection, paciente_id: int) -> list[str]:
    """Devuelve solo los nombres de medicamento activos — es lo que
    interacciones_clinica.checker necesita como entrada directa."""
    filas = conn.execute(
        "SELECT medicamento FROM medicacion_actual WHERE paciente_id = ? AND fecha_fin IS NULL",
        (paciente_id,),
    ).fetchall()
    return [fila[0] for fila in filas]


def finalizar_medicacion(conn: sqlite3.Connection, medicacion_id: int, fecha_fin: str) -> None:
    conn.execute(
        "UPDATE medicacion_actual SET fecha_fin = ? WHERE id = ?", (fecha_fin, medicacion_id)
    )
    conn.commit()


# ---- estado de conciliación --------------------------------------------

ESTADO_NO_REALIZADA = "no_realizada"
ESTADO_SIN_MEDICACION_CONCOMITANTE = "sin_medicacion_concomitante"
ESTADO_CON_MEDICACION_REGISTRADA = "con_medicacion_registrada"


def obtener_estado_conciliacion(conn: sqlite3.Connection, paciente_id: int) -> str:
    """Nunca lanza si no hay fila -- un paciente sin fila en esta tabla
    significa, por definición, que la conciliación no se ha hecho."""
    fila = conn.execute(
        "SELECT estado FROM conciliacion_medicamentos WHERE paciente_id = ?", (paciente_id,)
    ).fetchone()
    return fila[0] if fila else ESTADO_NO_REALIZADA


def establecer_estado_conciliacion(
    conn: sqlite3.Connection, paciente_id: int, estado: str, fecha: str, registrado_por: int
) -> None:
    conn.execute(
        """
        INSERT INTO conciliacion_medicamentos (paciente_id, estado, fecha, registrado_por)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(paciente_id) DO UPDATE SET
            estado = excluded.estado, fecha = excluded.fecha, registrado_por = excluded.registrado_por
        """,
        (paciente_id, estado, fecha, registrado_por),
    )
    conn.commit()
