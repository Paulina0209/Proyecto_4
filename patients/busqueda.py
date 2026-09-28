"""PAC-02 · Búsqueda y filtros de pacientes.

- Búsqueda por nombre parcial (sin distinguir mayúsculas ni tildes) y
  filtros combinables por diagnóstico, estado del tratamiento y fecha de
  la última consulta, con paginación.
- Sin resultados → mensaje explícito (AC2), nunca una lista vacía sola.
- Solo pacientes del oncólogo que consulta (regla de negocio, SEC-01).
- Registro e historial de diagnósticos, tratamientos y consultas: los
  datos sobre los que filtra la búsqueda (y que lee el resumen 360).
"""
from __future__ import annotations

import sqlite3
import unicodedata
from datetime import date
from typing import Optional

from .models import (
    ErrorValidacion,
    EstadoTratamiento,
    FiltrosBusqueda,
    PacienteResumen,
    ResultadoBusqueda,
    TipoIdentificacion,
)

LONGITUD_MAX_TEXTO_BUSQUEDA = 200
TAMANO_PAGINA_DEFECTO = 20
TAMANO_PAGINA_MAXIMO = 100


# ---------------------------------------------------------------------------
# Búsqueda
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
    FROM pacientes p
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
    """Requiere conn.row_factory = sqlite3.Row (lo deja así db.conectar)."""
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


# ---------------------------------------------------------------------------
# Datos clínicos sobre los que se filtra
# ---------------------------------------------------------------------------

def _texto_o_none(texto: Optional[str]) -> Optional[str]:
    return texto.strip() if texto and texto.strip() else None


def registrar_diagnostico(
    conn: sqlite3.Connection,
    paciente_id: int,
    descripcion: str,
    fecha: Optional[date] = None,
    estadio: Optional[str] = None,
) -> int:
    """La descripción se guarda tal cual; la normalización para buscar se
    aplica al consultar (ver _normalizar)."""
    if not descripcion or not descripcion.strip():
        raise ValueError("La descripción del diagnóstico es obligatoria.")
    cur = conn.execute(
        "INSERT INTO diagnosticos (paciente_id, descripcion, estadio, fecha) VALUES (?, ?, ?, ?)",
        (paciente_id, descripcion.strip(), _texto_o_none(estadio), fecha.isoformat() if fecha else None),
    )
    conn.commit()
    return cur.lastrowid


def registrar_tratamiento(
    conn: sqlite3.Connection,
    paciente_id: int,
    estado: EstadoTratamiento,
    fecha_inicio: Optional[date] = None,
    regimen: Optional[str] = None,
) -> int:
    """El estado que usa la búsqueda es el del tratamiento más reciente por
    fecha_inicio (a igual fecha, el último registrado)."""
    cur = conn.execute(
        "INSERT INTO tratamientos (paciente_id, estado, regimen, fecha_inicio) VALUES (?, ?, ?, ?)",
        (paciente_id, estado.value, _texto_o_none(regimen), fecha_inicio.isoformat() if fecha_inicio else None),
    )
    conn.commit()
    return cur.lastrowid


def registrar_consulta(
    conn: sqlite3.Connection, paciente_id: int, fecha: date, nota: Optional[str] = None
) -> int:
    """La fecha es obligatoria: sin ella la consulta no podría participar
    en el filtro por última consulta."""
    cur = conn.execute(
        "INSERT INTO consultas (paciente_id, fecha, nota) VALUES (?, ?, ?)",
        (paciente_id, fecha.isoformat(), _texto_o_none(nota)),
    )
    conn.commit()
    return cur.lastrowid


# Historial por paciente, más reciente primero.

def listar_diagnosticos(conn: sqlite3.Connection, paciente_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM diagnosticos WHERE paciente_id = ? ORDER BY fecha DESC, id DESC",
        (paciente_id,),
    ).fetchall()


def listar_tratamientos(conn: sqlite3.Connection, paciente_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM tratamientos WHERE paciente_id = ? ORDER BY fecha_inicio DESC, id DESC",
        (paciente_id,),
    ).fetchall()


def listar_consultas(conn: sqlite3.Connection, paciente_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM consultas WHERE paciente_id = ? ORDER BY fecha DESC, id DESC",
        (paciente_id,),
    ).fetchall()
