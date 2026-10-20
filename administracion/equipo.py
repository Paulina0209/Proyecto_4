"""Equipo de atención: a qué oncólogos asiste cada persona de enfermería o de admisiones.

Sin esta asignación la interfaz no les muestra pacientes (fail-closed): un paciente pertenece a su
oncólogo, y enfermería o admisiones ven solo los pacientes de los oncólogos con los que trabajan.

    - Quién asigna: el administrador del sistema (``Accion.GESTIONAR_USUARIOS``), como el resto de ADM-01.
    - A quién: personas de enfermería o administrativas, a oncólogos activos.
    - Nada se borra: retirar una asignación la deja inactiva con quién y cuándo; todo queda en AUD-01.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from administracion.usuarios import ErrorValidacion, UsuarioNoEncontradoError, _auditar, _verificar_actor
from seguridad.models import Rol, Usuario

#: Roles que trabajan sobre los pacientes de un oncólogo.
ROLES_DE_EQUIPO = frozenset({Rol.ENFERMERIA, Rol.ADMINISTRATIVO})

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS equipo_atencion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    oncologo_id INTEGER NOT NULL REFERENCES usuarios(id),
    asignado_por INTEGER NOT NULL,
    asignado_en TEXT NOT NULL,
    retirado_por INTEGER,
    retirado_en TEXT
);
CREATE INDEX IF NOT EXISTS idx_equipo_usuario ON equipo_atencion(usuario_id) WHERE retirado_en IS NULL;
"""


@dataclass(frozen=True)
class Asignacion:
    usuario_id: int
    oncologo_id: int
    oncologo_nombre: str
    asignado_en: str


def inicializar_esquema(conn: sqlite3.Connection) -> None:
    conn.executescript(_ESQUEMA)
    conn.commit()


def _ahora(ahora: Optional[datetime]) -> str:
    return (ahora or datetime.now(timezone.utc)).isoformat()


def _rol_de(conn: sqlite3.Connection, usuario_id: int, campo: str) -> Rol:
    fila = conn.execute("SELECT rol, activo FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    if fila is None:
        raise UsuarioNoEncontradoError(f"No existe el usuario {usuario_id}.")
    return Rol(fila["rol"] if isinstance(fila, sqlite3.Row) else fila[0])


def oncologos_de(conn: sqlite3.Connection, usuario_id: int) -> List[int]:
    """Los oncólogos (activos) con los que trabaja la persona, en el orden en que se asignaron."""
    inicializar_esquema(conn)
    return [f[0] for f in conn.execute(
        "SELECT e.oncologo_id FROM equipo_atencion e JOIN usuarios u ON u.id = e.oncologo_id "
        "WHERE e.usuario_id = ? AND e.retirado_en IS NULL AND u.activo = 1 ORDER BY e.id", (usuario_id,))]


def asignaciones_de(conn: sqlite3.Connection, usuario_id: int) -> List[Asignacion]:
    inicializar_esquema(conn)
    return [Asignacion(f[0], f[1], f[2] or f"Oncólogo {f[1]}", f[3]) for f in conn.execute(
        "SELECT e.usuario_id, e.oncologo_id, COALESCE(p.nombre_completo, u.nombre_usuario), e.asignado_en "
        "FROM equipo_atencion e JOIN usuarios u ON u.id = e.oncologo_id LEFT JOIN perfiles_usuario p ON p.usuario_id = u.id "
        "WHERE e.usuario_id = ? AND e.retirado_en IS NULL AND u.activo = 1 ORDER BY e.id", (usuario_id,))]


def asignar(conn: sqlite3.Connection, actor: Usuario, usuario_id: int, oncologo_id: int,
            ahora: Optional[datetime] = None) -> Asignacion:
    """Suma un oncólogo al equipo de la persona (idempotente)."""
    inicializar_esquema(conn)
    _verificar_actor(conn, actor, "asignar_equipo", ahora, usuario_id)
    errores = []
    if _rol_de(conn, usuario_id, "usuario_id") not in ROLES_DE_EQUIPO:
        errores.append(("usuario_id", "Solo se asignan a un oncólogo las personas de enfermería o de admisiones."))
    fila = conn.execute("SELECT rol, activo FROM usuarios WHERE id = ?", (oncologo_id,)).fetchone()
    if fila is None or fila[0] != Rol.ONCOLOGO.value or not fila[1]:
        errores.append(("oncologo_id", "Elige un oncólogo activo."))
    if errores:
        raise ErrorValidacion(errores)
    if oncologo_id not in oncologos_de(conn, usuario_id):
        conn.execute("INSERT INTO equipo_atencion (usuario_id, oncologo_id, asignado_por, asignado_en) VALUES (?, ?, ?, ?)",
                     (usuario_id, oncologo_id, actor.id, _ahora(ahora)))
        _auditar(conn, actor.id, "asignar_equipo", "ok", ahora, usuario_id, oncologo_id=oncologo_id)
    return next(a for a in asignaciones_de(conn, usuario_id) if a.oncologo_id == oncologo_id)


def retirar(conn: sqlite3.Connection, actor: Usuario, usuario_id: int, oncologo_id: int,
            ahora: Optional[datetime] = None) -> None:
    """Saca al oncólogo del equipo de la persona: deja de ver a sus pacientes (queda la constancia)."""
    inicializar_esquema(conn)
    _verificar_actor(conn, actor, "retirar_equipo", ahora, usuario_id)
    cursor = conn.execute(
        "UPDATE equipo_atencion SET retirado_por = ?, retirado_en = ? WHERE usuario_id = ? AND oncologo_id = ? AND retirado_en IS NULL",
        (actor.id, _ahora(ahora), usuario_id, oncologo_id))
    if cursor.rowcount:
        _auditar(conn, actor.id, "retirar_equipo", "ok", ahora, usuario_id, oncologo_id=oncologo_id)
    else:
        conn.commit()
