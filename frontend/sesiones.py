"""Sesiones de la interfaz web: un token opaco en una cookie HttpOnly, guardado en memoria del servidor.

El navegador manda usuario y contraseña UNA vez (``POST /api/sesion``); a partir de ahí solo viaja
la cookie. Así la contraseña no vive en el JavaScript de la página ni se reenvía en cada petición
(a diferencia de HTTP Basic), y recargar la página no obliga a volver a entrar.

Límites (documentados en ``docs/frontend.md``):

    - ``AlmacenSesiones`` guarda las sesiones en la memoria de ESTE proceso: reiniciar el servidor las
      cierra, y con varios procesos cada uno tiene las suyas. Para varias réplicas (NFR-05) está
      ``AlmacenSesionesSQLite``, que se activa con ``COPILOTO_SESIONES_DB``.
    - Caducan por inactividad (20 min) y por antigüedad (8 h), lo que ocurra primero.
    - Se guarda el hash del token, no el token: un volcado de memoria no entrega sesiones usables.
"""
from __future__ import annotations

import hashlib
import secrets
import threading
import time
from typing import Callable, Dict, Optional, Tuple

INACTIVIDAD_S = 20 * 60
DURACION_MAXIMA_S = 8 * 60 * 60


class AlmacenSesiones:
    def __init__(
        self,
        inactividad_s: int = INACTIVIDAD_S,
        duracion_maxima_s: int = DURACION_MAXIMA_S,
        reloj: Callable[[], float] = time.time,
    ) -> None:
        self.inactividad_s = inactividad_s
        self.duracion_maxima_s = duracion_maxima_s
        self._reloj = reloj
        self._sesiones: Dict[str, Tuple[int, float, float]] = {}  # hash -> (usuario_id, creada, último uso)
        self._cerrojo = threading.Lock()

    @staticmethod
    def _clave(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _vigente(self, creada: float, ultimo: float, ahora: float) -> bool:
        return (ahora - ultimo) <= self.inactividad_s and (ahora - creada) <= self.duracion_maxima_s

    def abrir(self, usuario_id: int) -> str:
        """Crea una sesión nueva y devuelve su token (que solo se entrega al navegador, una vez)."""
        token = secrets.token_urlsafe(32)
        ahora = self._reloj()
        with self._cerrojo:
            self._purgar(ahora)
            self._sesiones[self._clave(token)] = (usuario_id, ahora, ahora)
        return token

    def resolver(self, token: Optional[str]) -> Optional[int]:
        """El usuario de la sesión, o ``None`` si no existe o caducó. Una consulta válida renueva la inactividad."""
        if not token:
            return None
        clave = self._clave(token)
        ahora = self._reloj()
        with self._cerrojo:
            dato = self._sesiones.get(clave)
            if dato is None:
                return None
            usuario_id, creada, ultimo = dato
            if not self._vigente(creada, ultimo, ahora):
                del self._sesiones[clave]
                return None
            self._sesiones[clave] = (usuario_id, creada, ahora)
            return usuario_id

    def cerrar(self, token: Optional[str]) -> None:
        if token:
            with self._cerrojo:
                self._sesiones.pop(self._clave(token), None)

    def cerrar_de_usuario(self, usuario_id: int) -> int:
        """Cierra todas las sesiones de un usuario (p. ej. al desactivarlo). Devuelve cuántas cerró."""
        with self._cerrojo:
            claves = [k for k, (uid, _c, _u) in self._sesiones.items() if uid == usuario_id]
            for k in claves:
                del self._sesiones[k]
            return len(claves)

    def _purgar(self, ahora: float) -> None:
        for k in [k for k, (_u, c, ul) in self._sesiones.items() if not self._vigente(c, ul, ahora)]:
            del self._sesiones[k]

    def __len__(self) -> int:
        with self._cerrojo:
            return len(self._sesiones)


ENV_SESIONES_DB = "COPILOTO_SESIONES_DB"


class AlmacenSesionesSQLite(AlmacenSesiones):
    """NFR-05: las mismas sesiones, en una base SQLite que comparten todas las réplicas.

    Con varios procesos (``python -m seguridad.servidor_tls --workers N``) o varias
    máquinas detrás de un balanceador, cualquier réplica atiende a cualquier usuario:
    la sesión que abrió una la reconoce la otra, y cerrarla en una la cierra en
    todas. Reiniciar el servidor tampoco cierra las sesiones.

    Igual que en memoria, se guarda el hash del token, nunca el token. Para varias
    *máquinas* la base debe estar en un almacenamiento compartido; en producción
    real lo natural es Redis o la base de la institución (la interfaz es la misma).
    """

    _ESQUEMA = """
    CREATE TABLE IF NOT EXISTS sesiones (
        clave TEXT PRIMARY KEY,
        usuario_id INTEGER NOT NULL,
        creada REAL NOT NULL,
        ultimo_uso REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_sesiones_usuario ON sesiones (usuario_id);
    """

    def __init__(
        self,
        ruta,
        inactividad_s: int = INACTIVIDAD_S,
        duracion_maxima_s: int = DURACION_MAXIMA_S,
        reloj: Callable[[], float] = time.time,
    ) -> None:
        super().__init__(inactividad_s, duracion_maxima_s, reloj)
        from pathlib import Path

        self.ruta = Path(ruta)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        with self._conexion() as conn:
            conn.executescript(self._ESQUEMA)

    def _conexion(self):
        import sqlite3
        from contextlib import closing, contextmanager

        from operacion.sqlite import preparar_concurrencia

        @contextmanager
        def abrir():
            with closing(sqlite3.connect(str(self.ruta), timeout=5)) as conn:
                preparar_concurrencia(conn, self.ruta)
                with conn:  # una transacción por operación
                    yield conn

        return abrir()

    def abrir(self, usuario_id: int) -> str:
        token = secrets.token_urlsafe(32)
        ahora = self._reloj()
        with self._conexion() as conn:
            self._purgar_en(conn, ahora)
            conn.execute("INSERT INTO sesiones VALUES (?, ?, ?, ?)", (self._clave(token), usuario_id, ahora, ahora))
        return token

    def resolver(self, token: Optional[str]) -> Optional[int]:
        if not token:
            return None
        clave = self._clave(token)
        ahora = self._reloj()
        with self._conexion() as conn:
            fila = conn.execute("SELECT usuario_id, creada, ultimo_uso FROM sesiones WHERE clave = ?", (clave,)).fetchone()
            if fila is None:
                return None
            usuario_id, creada, ultimo = fila
            if not self._vigente(creada, ultimo, ahora):
                conn.execute("DELETE FROM sesiones WHERE clave = ?", (clave,))
                return None
            conn.execute("UPDATE sesiones SET ultimo_uso = ? WHERE clave = ?", (ahora, clave))
            return usuario_id

    def cerrar(self, token: Optional[str]) -> None:
        if token:
            with self._conexion() as conn:
                conn.execute("DELETE FROM sesiones WHERE clave = ?", (self._clave(token),))

    def cerrar_de_usuario(self, usuario_id: int) -> int:
        with self._conexion() as conn:
            return conn.execute("DELETE FROM sesiones WHERE usuario_id = ?", (usuario_id,)).rowcount

    def _purgar_en(self, conn, ahora: float) -> None:
        conn.execute(
            "DELETE FROM sesiones WHERE ? - ultimo_uso > ? OR ? - creada > ?",
            (ahora, self.inactividad_s, ahora, self.duracion_maxima_s),
        )

    def __len__(self) -> int:
        with self._conexion() as conn:
            return conn.execute("SELECT COUNT(*) FROM sesiones").fetchone()[0]


def almacen_por_defecto() -> AlmacenSesiones:
    """Compartido si ``COPILOTO_SESIONES_DB`` indica una base (varias réplicas); si no, en memoria."""
    import os

    ruta = os.environ.get(ENV_SESIONES_DB)
    return AlmacenSesionesSQLite(ruta) if ruta else AlmacenSesiones()
