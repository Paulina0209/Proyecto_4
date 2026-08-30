"""DX-03 — Registro del juicio clínico del médico (AC4/AC5).

Como oncólogo, si no estoy de acuerdo con la priorización que propone el
sistema, quiero poder registrar mi propio juicio diagnóstico, y que ese
juicio prevalezca como el juicio clínico final una vez que el flujo de
trabajo continúa.

Regla de negocio no negociable (ver backlog, historia DX-03): la decisión
diagnóstica siempre es responsabilidad del profesional de salud
autorizado. El sistema nunca bloquea, valida contra su propia
priorización, ni sobreescribe el juicio que el médico registra —
``registrar_juicio_clinico`` no compara ``diagnostico_registrado`` contra
``dx_clinica.builder`` de ninguna forma: acepta cualquier texto no vacío
del médico, sin excepción.

Diseño: la tabla ``juicios_clinicos_dx`` es de solo-inserción. Un
paciente puede acumular varios juicios a lo largo del tiempo (por
ejemplo, en distintas consultas de seguimiento); el "vigente" es siempre
el más reciente. Esto evita necesitar una operación de "corregir" o
"deshacer" un juicio ya registrado — el médico simplemente registra uno
nuevo, y ese pasa a prevalecer, sin que el anterior se pierda del
historial de auditoría.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence, Tuple

from dx_clinica.models import ResultadoDiagnosticoDiferencial

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema_juicio_clinico.sql"


class JuicioClinicoInvalidoError(Exception):
    """El juicio clínico no cumple los requisitos mínimos para registrarse.

    No es un rechazo por desacuerdo con el sistema (eso nunca se valida):
    es únicamente la validación de forma más básica (que el texto y el
    autor no estén vacíos), igual que en el resto del proyecto (ver
    ``SourceSpan``, ``AprobacionRegistrada``).
    """


@dataclass(frozen=True)
class JuicioClinico:
    """Snapshot de solo lectura de un juicio clínico ya registrado."""

    id: int
    paciente_id: int
    diagnostico_registrado: str
    autor: str
    registrado_en: str
    perfiles_sugeridos_por_sistema: Tuple[str, ...]
    advertencia_sistema: Optional[str]


def crear_conexion(ruta: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(ruta)
    conn.row_factory = sqlite3.Row
    inicializar_esquema(conn)
    return conn


def inicializar_esquema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def registrar_juicio_clinico(
    conn: sqlite3.Connection,
    paciente_id: int,
    diagnostico_registrado: str,
    autor: str,
    resultado_sistema: Optional[ResultadoDiagnosticoDiferencial] = None,
    ahora: Optional[datetime] = None,
) -> JuicioClinico:
    """Registra el juicio diagnóstico del médico (AC4).

    Nunca se compara ``diagnostico_registrado`` contra
    ``resultado_sistema``: coincida o no con lo que el sistema sugería,
    se acepta igual. ``resultado_sistema`` solo se usa para dejar un
    registro de auditoría de qué sugería el sistema en ese momento — es
    contexto histórico, no una validación.
    """

    if not diagnostico_registrado or not diagnostico_registrado.strip():
        raise JuicioClinicoInvalidoError(
            "El juicio clínico no puede estar vacío: se necesita el texto de la "
            "conclusión diagnóstica del médico."
        )
    if not autor or not autor.strip():
        raise JuicioClinicoInvalidoError(
            "El autor del juicio clínico no puede estar vacío: se necesita un "
            "identificador explícito del médico que lo registra."
        )

    perfiles_sugeridos: Sequence[str] = ()
    advertencia_sistema: Optional[str] = None
    if resultado_sistema is not None:
        perfiles_sugeridos = [c.perfil_id for c in resultado_sistema.candidatos]
        advertencia_sistema = resultado_sistema.advertencia_sin_sustento

    registrado_en = (ahora or datetime.now(timezone.utc)).isoformat()

    cursor = conn.execute(
        """
        INSERT INTO juicios_clinicos_dx (
            paciente_id, diagnostico_registrado, autor, registrado_en,
            perfiles_sugeridos_por_sistema, advertencia_sistema
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            paciente_id,
            diagnostico_registrado,
            autor,
            registrado_en,
            json.dumps(list(perfiles_sugeridos), ensure_ascii=False),
            advertencia_sistema,
        ),
    )
    conn.commit()
    return obtener_juicio_por_id(conn, cursor.lastrowid)


def obtener_juicio_por_id(conn: sqlite3.Connection, juicio_id: int) -> JuicioClinico:
    fila = conn.execute("SELECT * FROM juicios_clinicos_dx WHERE id = ?", (juicio_id,)).fetchone()
    if fila is None:
        raise KeyError(f"No existe ningún juicio clínico con id={juicio_id}.")
    return _fila_a_juicio(fila)


def obtener_juicio_vigente(conn: sqlite3.Connection, paciente_id: int) -> Optional[JuicioClinico]:
    """El juicio más reciente del paciente, o ``None`` si nunca se registró uno.

    Este es el que "prevalece" (AC5): si existe, el flujo clínico debe
    tratarlo como el juicio diagnóstico final, sin importar qué sugiera
    ``dx_clinica.builder``.
    """

    fila = conn.execute(
        "SELECT * FROM juicios_clinicos_dx WHERE paciente_id = ? ORDER BY id DESC LIMIT 1",
        (paciente_id,),
    ).fetchone()
    if fila is None:
        return None
    return _fila_a_juicio(fila)


def obtener_historial_juicios(conn: sqlite3.Connection, paciente_id: int) -> Tuple[JuicioClinico, ...]:
    """Todo el historial de juicios del paciente, del más reciente al más antiguo."""

    filas = conn.execute(
        "SELECT * FROM juicios_clinicos_dx WHERE paciente_id = ? ORDER BY id DESC",
        (paciente_id,),
    ).fetchall()
    return tuple(_fila_a_juicio(f) for f in filas)


@dataclass(frozen=True)
class DecisionDiagnosticaVigente:
    """Qué debe tratarse como el juicio diagnóstico vigente para este paciente ahora mismo (AC5).

    ``fuente`` es siempre ``"juicio_medico"`` si el médico registró
    alguno (sin importar qué tan diferente sea de lo que sugería el
    sistema), y solo cae a ``"apoyo_sistema"`` cuando no existe ningún
    juicio médico registrado todavía — y en ese caso el contenido sigue
    rotulado explícitamente como apoyo a la decisión clínica, nunca como
    un diagnóstico definitivo.
    """

    fuente: str  # "juicio_medico" | "apoyo_sistema"
    contenido: str
    juicio: Optional[JuicioClinico]
    resultado_sistema: Optional[ResultadoDiagnosticoDiferencial]

    def es_juicio_medico(self) -> bool:
        return self.fuente == "juicio_medico"


def obtener_decision_diagnostica_vigente(
    conn: sqlite3.Connection,
    paciente_id: int,
    resultado_sistema: Optional[ResultadoDiagnosticoDiferencial],
) -> DecisionDiagnosticaVigente:
    """Resuelve qué debe presentarse como el juicio diagnóstico vigente (AC5).

    Si el médico ya registró un juicio para este paciente, ese juicio
    prevalece siempre — incluso si contradice al candidato mejor
    priorizado de ``resultado_sistema`` — porque el sistema nunca tiene
    autoridad para invalidar el juicio clínico del médico.
    """

    juicio = obtener_juicio_vigente(conn, paciente_id)
    if juicio is not None:
        return DecisionDiagnosticaVigente(
            fuente="juicio_medico",
            contenido=juicio.diagnostico_registrado,
            juicio=juicio,
            resultado_sistema=resultado_sistema,
        )

    if resultado_sistema is None or resultado_sistema.esta_vacio():
        contenido = "Sin juicio médico registrado y sin alternativa diagnóstica sustentada por el sistema."
    else:
        contenido = (
            f"(apoyo a la decisión clínica, no definitivo) {resultado_sistema.candidatos[0].nombre}"
        )

    return DecisionDiagnosticaVigente(
        fuente="apoyo_sistema",
        contenido=contenido,
        juicio=None,
        resultado_sistema=resultado_sistema,
    )


def _fila_a_juicio(fila: sqlite3.Row) -> JuicioClinico:
    return JuicioClinico(
        id=fila["id"],
        paciente_id=fila["paciente_id"],
        diagnostico_registrado=fila["diagnostico_registrado"],
        autor=fila["autor"],
        registrado_en=fila["registrado_en"],
        perfiles_sugeridos_por_sistema=tuple(json.loads(fila["perfiles_sugeridos_por_sistema"])),
        advertencia_sistema=fila["advertencia_sistema"],
    )
