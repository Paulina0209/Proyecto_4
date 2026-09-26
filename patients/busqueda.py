
from __future__ import annotations

import sqlite3
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional

from .models import ErrorValidacion, TipoIdentificacion

LONGITUD_MAX_TEXTO_BUSQUEDA = 200
TAMANO_PAGINA_DEFECTO = 20
TAMANO_PAGINA_MAXIMO = 100


# ---------------------------------------------------------------------------
# Schema (ver nota de SUPUESTO arriba)
# ---------------------------------------------------------------------------

def inicializar_schema_busqueda(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS diagnosticos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente_id INTEGER NOT NULL,
            descripcion TEXT NOT NULL,
            fecha TEXT
        );
        CREATE TABLE IF NOT EXISTS tratamientos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente_id INTEGER NOT NULL,
            estado TEXT NOT NULL,
            fecha_inicio TEXT
        );
        CREATE TABLE IF NOT EXISTS consultas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paciente_id INTEGER NOT NULL,
            fecha TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_diagnosticos_paciente ON diagnosticos(paciente_id);
        CREATE INDEX IF NOT EXISTS idx_tratamientos_paciente ON tratamientos(paciente_id);
        CREATE INDEX IF NOT EXISTS idx_consultas_paciente ON consultas(paciente_id);
        CREATE INDEX IF NOT EXISTS idx_pacientes_oncologo ON pacientes_identidad(oncologo_id);
        """
    )
    conn.commit()


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------

class EstadoTratamiento(str, Enum):
    EN_TRATAMIENTO = "en_tratamiento"
    EN_SEGUIMIENTO = "en_seguimiento"
    SUSPENDIDO = "suspendido"
    FINALIZADO = "finalizado"


@dataclass
class FiltrosBusqueda:
    oncologo_id: int  # alcance de permisos: solo pacientes de este oncólogo
    nombre: Optional[str] = None
    diagnostico: Optional[str] = None
    estado_tratamiento: Optional[EstadoTratamiento] = None
    ultima_consulta_desde: Optional[date] = None
    ultima_consulta_hasta: Optional[date] = None

    def aplicados(self) -> dict[str, str]:
        """Solo los filtros con valor, ya en texto legible (para el mensaje
        de 'sin resultados' y para que la UI muestre chips de filtros)."""
        filtros: dict[str, str] = {}
        if self.nombre and self.nombre.strip():
            filtros["nombre"] = self.nombre.strip()
        if self.diagnostico and self.diagnostico.strip():
            filtros["diagnostico"] = self.diagnostico.strip()
        if self.estado_tratamiento:
            filtros["estado_tratamiento"] = self.estado_tratamiento.value
        if self.ultima_consulta_desde:
            filtros["ultima_consulta_desde"] = self.ultima_consulta_desde.isoformat()
        if self.ultima_consulta_hasta:
            filtros["ultima_consulta_hasta"] = self.ultima_consulta_hasta.isoformat()
        return filtros


@dataclass
class PacienteResumen:
    id: int
    nombre_completo: str
    fecha_nacimiento: Optional[date]
    tipo_identificacion: TipoIdentificacion
    numero_identificacion: str
    diagnosticos: list[str] = field(default_factory=list)
    estado_tratamiento: Optional[str] = None  # estado del tratamiento más reciente
    fecha_ultima_consulta: Optional[date] = None


@dataclass
class ResultadoBusqueda:
    items: list[PacienteResumen]
    total: int
    pagina: int
    tamano_pagina: int
    mensaje: Optional[str] = None  # solo se llena cuando total == 0

    @property
    def total_paginas(self) -> int:
        return -(-self.total // self.tamano_pagina) if self.total else 0


# ---------------------------------------------------------------------------
# validacion
# ---------------------------------------------------------------------------

def validar_filtros(filtros: FiltrosBusqueda) -> list[ErrorValidacion]:
    errores: list[ErrorValidacion] = []
    if not filtros.oncologo_id or filtros.oncologo_id <= 0:
        errores.append(ErrorValidacion("oncologo_id", "El id del oncólogo debe ser un entero positivo."))
    if (
        filtros.ultima_consulta_desde
        and filtros.ultima_consulta_hasta
        and filtros.ultima_consulta_desde > filtros.ultima_consulta_hasta
    ):
        errores.append(ErrorValidacion(
            "ultima_consulta_desde",
            "La fecha 'desde' de la última consulta no puede ser posterior a la fecha 'hasta'.",
        ))
    for campo in ("nombre", "diagnostico"):
        valor = getattr(filtros, campo)
        if valor and len(valor) > LONGITUD_MAX_TEXTO_BUSQUEDA:
            errores.append(ErrorValidacion(
                campo, f"El texto de búsqueda no puede superar {LONGITUD_MAX_TEXTO_BUSQUEDA} caracteres.",
            ))
    return errores


# ---------------------------------------------------------------------------
# repository
# ---------------------------------------------------------------------------

def _normalizar(texto) -> str:
    """Minúsculas y sin tildes: 'José' y 'jose' deben encontrarse entre sí.
    (El LIKE de SQLite solo ignora mayúsculas en ASCII, no tildes.)"""
    if texto is None:
        return ""
    descompuesto = unicodedata.normalize("NFKD", str(texto).casefold())
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def _patron_contiene(texto: str) -> str:
    """Escapa % y _ para que se busquen como caracteres literales."""
    escapado = texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escapado}%"


# Una fila por paciente del oncólogo, con estado de tratamiento (el del
# tratamiento más reciente) y fecha de última consulta ya calculados, para
# poder filtrar por ellos con un WHERE normal.
_BASE_SQL = """
WITH base AS (
    SELECT
        p.id, p.nombre_completo, p.fecha_nacimiento,
        p.tipo_identificacion, p.numero_identificacion,
        (SELECT t.estado FROM tratamientos t
          WHERE t.paciente_id = p.id
          ORDER BY t.fecha_inicio DESC, t.id DESC LIMIT 1) AS estado_tratamiento,
        (SELECT MAX(c.fecha) FROM consultas c
          WHERE c.paciente_id = p.id) AS ultima_consulta
    FROM pacientes_identidad p
    WHERE p.oncologo_id = ?
)
"""


def _construir_where(filtros: FiltrosBusqueda) -> tuple[str, list]:
    condiciones: list[str] = []
    params: list = []

    # Cada palabra del nombre debe aparecer en algún lugar del nombre:
    # "juan perez" encuentra a "Juan Carlos Pérez".
    for palabra in _normalizar(filtros.nombre).split():
        condiciones.append("norm(nombre_completo) LIKE ? ESCAPE '\\'")
        params.append(_patron_contiene(palabra))

    diagnostico = _normalizar(filtros.diagnostico).strip()
    if diagnostico:
        condiciones.append(
            "EXISTS (SELECT 1 FROM diagnosticos d WHERE d.paciente_id = base.id "
            "AND norm(d.descripcion) LIKE ? ESCAPE '\\')"
        )
        params.append(_patron_contiene(diagnostico))

    if filtros.estado_tratamiento:
        condiciones.append("estado_tratamiento = ?")
        params.append(filtros.estado_tratamiento.value)

    # Un paciente sin consultas queda fuera cuando se filtra por fecha.
    if filtros.ultima_consulta_desde:
        condiciones.append("date(ultima_consulta) >= ?")
        params.append(filtros.ultima_consulta_desde.isoformat())
    if filtros.ultima_consulta_hasta:
        condiciones.append("date(ultima_consulta) <= ?")
        params.append(filtros.ultima_consulta_hasta.isoformat())

    where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""
    return where, params


def _diagnosticos_por_paciente(conn: sqlite3.Connection, ids: list[int]) -> dict[int, list[str]]:
    if not ids:
        return {}
    marcadores = ",".join("?" * len(ids))
    filas = conn.execute(
        f"SELECT paciente_id, descripcion FROM diagnosticos "
        f"WHERE paciente_id IN ({marcadores}) ORDER BY fecha DESC, id DESC",
        ids,
    ).fetchall()
    resultado: dict[int, list[str]] = {}
    for fila in filas:
        resultado.setdefault(fila["paciente_id"], []).append(fila["descripcion"])
    return resultado


def mensaje_sin_resultados(filtros: FiltrosBusqueda) -> str:
    aplicados = filtros.aplicados()
    if not aplicados:
        return "Aún no tienes pacientes registrados."
    detalle = ", ".join(f"{k}: {v}" for k, v in aplicados.items())
    return (
        f"No se encontraron pacientes que coincidan con los filtros aplicados ({detalle}). "
        "Prueba a quitar o ajustar algún filtro."
    )


def buscar_pacientes(
    conn: sqlite3.Connection,
    filtros: FiltrosBusqueda,
    pagina: int = 1,
    tamano_pagina: int = TAMANO_PAGINA_DEFECTO,
) -> ResultadoBusqueda:
    """Requiere conn.row_factory = sqlite3.Row (igual que repository.py)."""
    conn.create_function("norm", 1, _normalizar, deterministic=True)

    where, params_where = _construir_where(filtros)
    params_base = [filtros.oncologo_id]

    total = conn.execute(
        f"{_BASE_SQL} SELECT COUNT(*) FROM base {where}", params_base + params_where
    ).fetchone()[0]

    filas = conn.execute(
        f"{_BASE_SQL} SELECT * FROM base {where} "
        "ORDER BY norm(nombre_completo), id LIMIT ? OFFSET ?",
        params_base + params_where + [tamano_pagina, (pagina - 1) * tamano_pagina],
    ).fetchall()

    diagnosticos = _diagnosticos_por_paciente(conn, [f["id"] for f in filas])

    items = [
        PacienteResumen(
            id=f["id"],
            nombre_completo=f["nombre_completo"],
            fecha_nacimiento=date.fromisoformat(f["fecha_nacimiento"]) if f["fecha_nacimiento"] else None,
            tipo_identificacion=TipoIdentificacion(f["tipo_identificacion"]),
            numero_identificacion=f["numero_identificacion"],
            diagnosticos=diagnosticos.get(f["id"], []),
            estado_tratamiento=f["estado_tratamiento"],
            fecha_ultima_consulta=(
                date.fromisoformat(f["ultima_consulta"][:10]) if f["ultima_consulta"] else None
            ),
        )
        for f in filas
    ]

    return ResultadoBusqueda(
        items=items,
        total=total,
        pagina=pagina,
        tamano_pagina=tamano_pagina,
        mensaje=mensaje_sin_resultados(filtros) if total == 0 else None,
    )
