"""Historial de conversaciones de cada médico (SQLite, ``COPILOTO_CONVERSACIONES_DB``).

Cada conversación es de un usuario; nadie ve las de otro. Cada mensaje guarda
la intención detectada, cómo terminó (respondida / rechazada / aclaración), las
fuentes citadas y los pasos del grafo, para poder reconstruir de dónde salió
cada respuesta.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from asistente import config

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS conversaciones (
    id TEXT PRIMARY KEY,
    usuario_id INTEGER NOT NULL,
    paciente_id INTEGER,
    titulo TEXT NOT NULL,
    creada TEXT NOT NULL,
    actualizada TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversaciones_usuario ON conversaciones (usuario_id, actualizada DESC);
CREATE TABLE IF NOT EXISTS mensajes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversacion_id TEXT NOT NULL REFERENCES conversaciones(id),
    rol TEXT NOT NULL,              -- medico | asistente
    texto TEXT NOT NULL,
    intencion TEXT,
    estado TEXT,                    -- respondida | rechazada | aclaracion
    paciente_id INTEGER,
    fuentes_json TEXT NOT NULL DEFAULT '[]',
    pasos_json TEXT NOT NULL DEFAULT '[]',
    modelo TEXT,
    fecha TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mensajes_conversacion ON mensajes (conversacion_id, id);
"""


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


def conectar(ruta: Optional[Path] = None) -> sqlite3.Connection:
    from operacion.sqlite import preparar_concurrencia

    ruta = Path(ruta or config.ruta_conversaciones())
    ruta.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(ruta), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    preparar_concurrencia(conn, ruta)
    conn.executescript(_ESQUEMA)
    return conn


def nueva_conversacion(usuario_id: int, titulo: str, paciente_id: Optional[int] = None) -> str:
    cid = secrets.token_urlsafe(12)
    with closing(conectar()) as conn, conn:
        momento = _ahora()
        conn.execute("INSERT INTO conversaciones VALUES (?, ?, ?, ?, ?, ?)", (cid, usuario_id, paciente_id, titulo[:120], momento, momento))
    return cid


def es_de(conversacion_id: str, usuario_id: int) -> bool:
    with closing(conectar()) as conn:
        fila = conn.execute("SELECT usuario_id FROM conversaciones WHERE id = ?", (conversacion_id,)).fetchone()
    return fila is not None and fila[0] == usuario_id


def guardar_mensaje(conversacion_id: str, rol: str, texto: str, *, intencion: Optional[str] = None, estado: Optional[str] = None,
                    paciente_id: Optional[int] = None, fuentes: Optional[List[Dict[str, Any]]] = None,
                    pasos: Optional[List[Dict[str, Any]]] = None, modelo: Optional[str] = None) -> None:
    with closing(conectar()) as conn, conn:
        momento = _ahora()
        conn.execute(
            "INSERT INTO mensajes (conversacion_id, rol, texto, intencion, estado, paciente_id, fuentes_json, pasos_json, modelo, fecha) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (conversacion_id, rol, texto, intencion, estado, paciente_id, json.dumps(fuentes or [], ensure_ascii=False),
             json.dumps(pasos or [], ensure_ascii=False), modelo, momento))
        if paciente_id is not None:
            conn.execute("UPDATE conversaciones SET paciente_id = ?, actualizada = ? WHERE id = ?", (paciente_id, momento, conversacion_id))
        else:
            conn.execute("UPDATE conversaciones SET actualizada = ? WHERE id = ?", (momento, conversacion_id))


def conversaciones_de(usuario_id: int, limite: int = 30) -> List[Dict[str, Any]]:
    with closing(conectar()) as conn:
        return [dict(f) for f in conn.execute(
            "SELECT c.*, (SELECT COUNT(*) FROM mensajes m WHERE m.conversacion_id = c.id) AS mensajes FROM conversaciones c "
            "WHERE usuario_id = ? ORDER BY actualizada DESC LIMIT ?", (usuario_id, limite))]


def mensajes_de(conversacion_id: str) -> List[Dict[str, Any]]:
    with closing(conectar()) as conn:
        filas = conn.execute("SELECT * FROM mensajes WHERE conversacion_id = ? ORDER BY id", (conversacion_id,)).fetchall()
    resultado = []
    for f in filas:
        d = dict(f)
        d["fuentes"] = json.loads(d.pop("fuentes_json") or "[]")
        d["pasos"] = json.loads(d.pop("pasos_json") or "[]")
        resultado.append(d)
    return resultado


def historia_reciente(conversacion_id: str, n: int = 6) -> List[Dict[str, Any]]:
    """Los últimos ``n`` mensajes (para dar contexto a la siguiente pregunta)."""
    return mensajes_de(conversacion_id)[-n:]
