"""EST-02 — Ajuste manual de estadificación.

Como oncólogo, quiero poder revisar, ajustar y confirmar manualmente la
estadificación sugerida por el sistema (EST-01), para que el registro final
refleje mi criterio médico.

Regla de negocio no negociable (ver backlog, historia EST-02): el estadio
final registrado es siempre el que confirma el médico, coincida o no con la
sugerencia de ``estadificacion.builder``. ``confirmar_estadificacion`` nunca
compara ``estadio_confirmado`` contra la propuesta del sistema para
aceptarlo o rechazarlo — solo para dejar registrado (auditoría, insumo de
AUD-02) si difirió.

Diseño: igual que ``dx_clinica/juicio_clinico.py`` para DX-03. La tabla
``confirmaciones_estadificacion`` es de solo-inserción (append-only); la
"confirmación vigente" de un paciente es siempre la más reciente. Un médico
puede confirmar de nuevo más adelante (por ejemplo, tras una biopsia
adicional) sin que eso borre ni corrija la confirmación anterior — ambas
quedan en el historial de auditoría.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from estadificacion.models import PropuestaEstadificacion

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema_confirmacion_estadio.sql"


class ConfirmacionInvalidaError(Exception):
    """La confirmación no cumple los requisitos mínimos para registrarse.

    No es un rechazo por desacuerdo con el sistema (eso nunca se valida):
    es únicamente la validación de forma más básica (que el estadio y el
    autor no estén vacíos), igual que ``JuicioClinicoInvalidoError`` en DX-03.
    """


@dataclass(frozen=True)
class ConfirmacionEstadio:
    """Snapshot de solo lectura de una confirmación de estadio ya registrada."""

    id: int
    paciente_id: int
    estadio_confirmado: str
    componentes_confirmados: Optional[Dict[str, str]]
    autor: str
    registrado_en: str
    justificacion: Optional[str]
    estadio_sugerido_por_sistema: Optional[str]
    sistema_id: Optional[str]
    sistema_version: Optional[str]
    sugerencia_disponible: bool
    difiere_de_sugerencia: bool


def crear_conexion(ruta: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(ruta)
    conn.row_factory = sqlite3.Row
    inicializar_esquema(conn)
    return conn


def inicializar_esquema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def _normalizar(estadio: str) -> str:
    return estadio.strip().casefold()


def confirmar_estadificacion(
    conn: sqlite3.Connection,
    paciente_id: int,
    estadio_confirmado: str,
    autor: str,
    propuesta_sistema: Optional[PropuestaEstadificacion] = None,
    componentes_confirmados: Optional[Dict[str, str]] = None,
    justificacion: Optional[str] = None,
    ahora: Optional[datetime] = None,
) -> ConfirmacionEstadio:
    """Registra el estadio que el médico confirma como final (criterio de aceptación de EST-02).

    ``estadio_confirmado`` puede coincidir o no con
    ``propuesta_sistema.estadio_global``: nunca se valida ni se rechaza por
    diferir. ``propuesta_sistema`` solo se usa para dejar un snapshot de
    auditoría de qué sugería el sistema en ese momento, y para calcular
    ``difiere_de_sugerencia`` — insumo directo de AUD-02 (trazabilidad de
    recomendaciones de IA), que todavía no existe como componente propio.
    """

    if not estadio_confirmado or not estadio_confirmado.strip():
        raise ConfirmacionInvalidaError(
            "El estadio confirmado no puede estar vacío: se necesita el valor "
            "final que el médico registra."
        )
    if not autor or not autor.strip():
        raise ConfirmacionInvalidaError(
            "El autor de la confirmación no puede estar vacío: se necesita un "
            "identificador explícito del médico que confirma el estadio."
        )

    sugerencia_disponible = bool(
        propuesta_sistema is not None and propuesta_sistema.estadio_global
    )
    difiere = sugerencia_disponible and _normalizar(
        propuesta_sistema.estadio_global
    ) != _normalizar(estadio_confirmado)

    registrado_en = (ahora or datetime.now(timezone.utc)).isoformat()

    cursor = conn.execute(
        """
        INSERT INTO confirmaciones_estadificacion (
            paciente_id, estadio_confirmado, componentes_confirmados, autor,
            registrado_en, justificacion, estadio_sugerido_por_sistema,
            sistema_id, sistema_version, difiere_de_sugerencia, sugerencia_disponible
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            paciente_id,
            estadio_confirmado,
            json.dumps(componentes_confirmados, ensure_ascii=False) if componentes_confirmados else None,
            autor,
            registrado_en,
            justificacion,
            propuesta_sistema.estadio_global if propuesta_sistema else None,
            propuesta_sistema.sistema_id if propuesta_sistema else None,
            propuesta_sistema.sistema_version if propuesta_sistema else None,
            int(difiere),
            int(sugerencia_disponible),
        ),
    )
    conn.commit()
    return obtener_confirmacion_por_id(conn, cursor.lastrowid)


def obtener_confirmacion_por_id(conn: sqlite3.Connection, confirmacion_id: int) -> ConfirmacionEstadio:
    fila = conn.execute(
        "SELECT * FROM confirmaciones_estadificacion WHERE id = ?", (confirmacion_id,)
    ).fetchone()
    if fila is None:
        raise KeyError(f"No existe ninguna confirmación de estadio con id={confirmacion_id}.")
    return _fila_a_confirmacion(fila)


def obtener_confirmacion_vigente(
    conn: sqlite3.Connection, paciente_id: int
) -> Optional[ConfirmacionEstadio]:
    """La confirmación más reciente del paciente, o ``None`` si nunca se registró una.

    Es la que debe tratarse como el estadio final (criterio de aceptación de
    EST-02): si existe, prevalece sobre lo que sugiera
    ``estadificacion.builder``, sin importar qué tan distinta sea.
    """

    fila = conn.execute(
        "SELECT * FROM confirmaciones_estadificacion WHERE paciente_id = ? ORDER BY id DESC LIMIT 1",
        (paciente_id,),
    ).fetchone()
    if fila is None:
        return None
    return _fila_a_confirmacion(fila)


def obtener_historial_confirmaciones(
    conn: sqlite3.Connection, paciente_id: int
) -> tuple[ConfirmacionEstadio, ...]:
    """Todo el historial de confirmaciones del paciente, de la más reciente a la más antigua."""

    filas = conn.execute(
        "SELECT * FROM confirmaciones_estadificacion WHERE paciente_id = ? ORDER BY id DESC",
        (paciente_id,),
    ).fetchall()
    return tuple(_fila_a_confirmacion(f) for f in filas)


@dataclass(frozen=True)
class EstadioVigente:
    """Qué debe tratarse como el estadio final de este paciente ahora mismo.

    ``fuente`` es ``"confirmacion_medica"`` si el médico ya confirmó un
    estadio (sin importar qué tan distinto sea de lo que sugería el
    sistema), y solo cae a ``"apoyo_sistema"`` cuando no existe ninguna
    confirmación registrada todavía — y en ese caso el estadio sigue
    rotulado explícitamente como propuesta de apoyo, nunca como definitivo.
    """

    fuente: str  # "confirmacion_medica" | "apoyo_sistema"
    estadio: Optional[str]
    confirmacion: Optional[ConfirmacionEstadio]
    propuesta_sistema: Optional[PropuestaEstadificacion]

    def es_confirmacion_medica(self) -> bool:
        return self.fuente == "confirmacion_medica"


def obtener_estadificacion_vigente(
    conn: sqlite3.Connection,
    paciente_id: int,
    propuesta_sistema: Optional[PropuestaEstadificacion],
) -> EstadioVigente:
    """Resuelve qué debe presentarse como el estadio vigente del paciente.

    Si el médico ya confirmó un estadio, ese prevalece siempre — incluso si
    contradice al estadio propuesto por EST-01 — porque el sistema nunca
    tiene autoridad para invalidar la confirmación del médico.
    """

    confirmacion = obtener_confirmacion_vigente(conn, paciente_id)
    if confirmacion is not None:
        return EstadioVigente(
            fuente="confirmacion_medica",
            estadio=confirmacion.estadio_confirmado,
            confirmacion=confirmacion,
            propuesta_sistema=propuesta_sistema,
        )

    estadio_propuesto = propuesta_sistema.estadio_global if propuesta_sistema else None
    return EstadioVigente(
        fuente="apoyo_sistema",
        estadio=estadio_propuesto,
        confirmacion=None,
        propuesta_sistema=propuesta_sistema,
    )


def _fila_a_confirmacion(fila: sqlite3.Row) -> ConfirmacionEstadio:
    componentes = fila["componentes_confirmados"]
    return ConfirmacionEstadio(
        id=fila["id"],
        paciente_id=fila["paciente_id"],
        estadio_confirmado=fila["estadio_confirmado"],
        componentes_confirmados=json.loads(componentes) if componentes else None,
        autor=fila["autor"],
        registrado_en=fila["registrado_en"],
        justificacion=fila["justificacion"],
        estadio_sugerido_por_sistema=fila["estadio_sugerido_por_sistema"],
        sistema_id=fila["sistema_id"],
        sistema_version=fila["sistema_version"],
        sugerencia_disponible=bool(fila["sugerencia_disponible"]),
        difiere_de_sugerencia=bool(fila["difiere_de_sugerencia"]),
    )
