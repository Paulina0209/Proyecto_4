"""NFR-06 — Cumplimiento de datos personales y gestión de derechos.

Como institución, quiero que el sistema permita aplicar las políticas de
tratamiento de datos de la jurisdicción que corresponda y gestionar los
derechos asociados a la información personal, para facilitar el
cumplimiento normativo.

Regla de negocio de la historia: la norma aplicable depende de la
jurisdicción y del contexto institucional, y la institución (responsable
del tratamiento) define la base legal, las políticas y las obligaciones.
Por eso aquí no hay lógica "HIPAA", "GDPR" ni "Ley 1581" escrita en el
código (nota técnica de la historia). Una ``PoliticaTratamiento`` es un
dato configurable que declara:

    - su jurisdicción y el marco normativo que la institución aplica
      (texto de referencia, no comportamiento);
    - las finalidades de tratamiento y cuáles requieren autorización;
    - las bases legales que la institución admite;
    - los derechos del titular que reconoce (acceso, rectificación...);
    - el plazo de respuesta a una solicitud y si la autorización exige soporte.

Cada criterio de aceptación tiene una función:

    - AC1 configurar políticas     -> ``configurar_politica`` (versionada)
    - AC2 evidencia de autorización -> ``registrar_autorizacion`` / ``estado_autorizacion``
    - AC3 finalidad identificable  -> ``Autorizacion.finalidad`` + ``politica_de_autorizacion``
    - AC4 atender derechos         -> ``registrar_solicitud_derechos``,
                                      ``recopilar_informacion_titular``,
                                      ``actualizar_solicitud``
    - AC5 traza de auditoría       -> cada operación deja un evento en
                                      ``auditoria.eventos_acceso`` (AUD-01),
                                      en la misma transacción que el registro

Las tablas son de solo-inserción (ver ``schema_privacidad.sql``).
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from auditoria.models import TipoAccion
from auditoria.registro_acceso import inicializar_schema as inicializar_schema_auditoria
from auditoria.registro_acceso import obtener_eventos_de_paciente, registrar_acceso
from privacidad.models import (
    ESTADOS_FINALES,
    Autorizacion,
    DecisionTratamientoDatos,
    EstadoAutorizacion,
    EstadoSolicitud,
    EventoSolicitud,
    Finalidad,
    InformacionTitular,
    PoliticaTratamiento,
    ResultadoOperacion,
    SolicitudDerechos,
)

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema_privacidad.sql"
_CODIGO_VALIDO = re.compile(r"^[a-z0-9][a-z0-9_\-.]*$")

#: Tablas del expediente clínico con datos del titular: (tabla, columna del paciente).
#: Las que no existan en la conexión dada se omiten.
TABLAS_EXPEDIENTE: Tuple[Tuple[str, str], ...] = (
    ("pacientes", "id"),
    ("consultas", "paciente_id"),
    ("laboratorios", "paciente_id"),
    ("imagenologia", "paciente_id"),
    ("biomarcadores", "paciente_id"),
    ("datos_clinicos_estructurados", "paciente_id"),
    ("comorbilidades", "paciente_id"),
    ("antecedentes_externos", "paciente_id"),
    ("sincronizaciones_externas", "paciente_id"),
)


def crear_conexion(ruta: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(ruta)
    conn.row_factory = sqlite3.Row
    inicializar_esquema(conn)
    return conn


def inicializar_esquema(conn: sqlite3.Connection) -> None:
    """Crea las tablas de NFR-06 y las de auditoría (AUD-01), donde queda su traza."""
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    inicializar_schema_auditoria(conn)
    conn.commit()


def _ahora(ahora: Optional[datetime]) -> datetime:
    return ahora or datetime.now(timezone.utc)


def _auditar(conn, usuario_id, accion, paciente_id, detalle, ahora) -> None:
    """Registra la traza (AC5). ``registrar_acceso`` hace el commit, así que
    el registro de negocio y su evento de auditoría se confirman juntos."""
    registrar_acceso(conn, usuario_id, accion, paciente_id=paciente_id, detalle=detalle, ahora=ahora)


# ---------------------------------------------------------------------------
# AC1 — Políticas configurables por jurisdicción
# ---------------------------------------------------------------------------


def configurar_politica(
    conn: sqlite3.Connection,
    usuario_id: int,
    *,
    codigo: str,
    jurisdiccion: str,
    nombre: str,
    finalidades: Sequence[Finalidad],
    bases_legales: Sequence[str],
    derechos: Sequence[str],
    plazo_respuesta_dias: int,
    marco_normativo: Optional[str] = None,
    requiere_evidencia_autorizacion: bool = True,
    ahora: Optional[datetime] = None,
) -> ResultadoOperacion:
    """Crea una política o publica una nueva versión de una existente.

    Las versiones anteriores se conservan: las autorizaciones y solicitudes
    registradas antes siguen apuntando a la versión bajo la que se
    registraron.
    """
    errores: List[str] = []
    if not _CODIGO_VALIDO.match(codigo or ""):
        errores.append("El código de la política debe ser un identificador en minúsculas (p. ej. 'co-pacientes').")
    if not (jurisdiccion or "").strip():
        errores.append("La jurisdicción es obligatoria.")
    if not (nombre or "").strip():
        errores.append("El nombre de la política es obligatorio.")
    if not finalidades:
        errores.append("La política debe declarar al menos una finalidad de tratamiento.")
    codigos_finalidad = [f.codigo for f in finalidades]
    if len(set(codigos_finalidad)) != len(codigos_finalidad):
        errores.append("Hay finalidades con el código repetido.")
    if any(not _CODIGO_VALIDO.match(c or "") or not (f.descripcion or "").strip() for c, f in zip(codigos_finalidad, finalidades)):
        errores.append("Cada finalidad necesita un código en minúsculas y una descripción.")
    if not [b for b in bases_legales if b.strip()]:
        errores.append("La política debe declarar al menos una base legal admitida.")
    if not [d for d in derechos if d.strip()]:
        errores.append("La política debe declarar los derechos del titular que reconoce.")
    if not isinstance(plazo_respuesta_dias, int) or plazo_respuesta_dias <= 0:
        errores.append("El plazo de respuesta debe ser un número entero de días mayor que cero.")
    if errores:
        return ResultadoOperacion(exito=False, motivo_rechazo=" ".join(errores))

    momento = _ahora(ahora)
    version_actual = conn.execute(
        "SELECT MAX(version) FROM politicas_tratamiento WHERE codigo = ?", (codigo,)
    ).fetchone()[0]
    version = (version_actual or 0) + 1
    cursor = conn.execute(
        """
        INSERT INTO politicas_tratamiento
            (codigo, version, jurisdiccion, nombre, marco_normativo, finalidades_json,
             bases_legales_json, derechos_json, plazo_respuesta_dias,
             requiere_evidencia_autorizacion, configurado_por, fecha)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            codigo,
            version,
            jurisdiccion.strip(),
            nombre.strip(),
            marco_normativo,
            json.dumps([f.__dict__ for f in finalidades], ensure_ascii=False),
            json.dumps([b.strip() for b in bases_legales if b.strip()], ensure_ascii=False),
            json.dumps([d.strip() for d in derechos if d.strip()], ensure_ascii=False),
            plazo_respuesta_dias,
            int(requiere_evidencia_autorizacion),
            usuario_id,
            momento.isoformat(),
        ),
    )
    politica = _politica_por_id(conn, cursor.lastrowid)
    _auditar(
        conn, usuario_id, TipoAccion.CONFIGURAR_POLITICA_DATOS, None,
        f"Política '{codigo}' v{version} ({politica.jurisdiccion}) configurada.", momento,
    )
    return ResultadoOperacion(exito=True, registro=politica)


def politica_vigente(conn: sqlite3.Connection, codigo: str) -> Optional[PoliticaTratamiento]:
    fila = conn.execute(
        "SELECT * FROM politicas_tratamiento WHERE codigo = ? ORDER BY version DESC LIMIT 1", (codigo,)
    ).fetchone()
    return _fila_a_politica(fila) if fila else None


def politicas_vigentes(conn: sqlite3.Connection, jurisdiccion: Optional[str] = None) -> Tuple[PoliticaTratamiento, ...]:
    """La última versión de cada política, opcionalmente de una sola jurisdicción."""
    filas = conn.execute(
        """
        SELECT p.* FROM politicas_tratamiento p
        JOIN (SELECT codigo, MAX(version) AS version FROM politicas_tratamiento GROUP BY codigo) ultima
          ON ultima.codigo = p.codigo AND ultima.version = p.version
        ORDER BY p.codigo
        """
    ).fetchall()
    politicas = tuple(_fila_a_politica(f) for f in filas)
    if jurisdiccion is None:
        return politicas
    return tuple(p for p in politicas if p.jurisdiccion.casefold() == jurisdiccion.casefold())


def historial_politica(conn: sqlite3.Connection, codigo: str) -> Tuple[PoliticaTratamiento, ...]:
    filas = conn.execute(
        "SELECT * FROM politicas_tratamiento WHERE codigo = ? ORDER BY version DESC", (codigo,)
    ).fetchall()
    return tuple(_fila_a_politica(f) for f in filas)


def _politica_por_id(conn: sqlite3.Connection, politica_id: int) -> PoliticaTratamiento:
    fila = conn.execute("SELECT * FROM politicas_tratamiento WHERE id = ?", (politica_id,)).fetchone()
    if fila is None:
        raise KeyError(f"No existe ninguna política con id={politica_id}.")
    return _fila_a_politica(fila)


# ---------------------------------------------------------------------------
# AC2 / AC3 — Autorizaciones con evidencia y finalidad
# ---------------------------------------------------------------------------


def registrar_autorizacion(
    conn: sqlite3.Connection,
    usuario_id: int,
    *,
    paciente_id: int,
    codigo_politica: str,
    finalidad: str,
    base_legal: str,
    estado: EstadoAutorizacion = EstadoAutorizacion.OTORGADA,
    medio: Optional[str] = None,
    evidencia_ref: Optional[str] = None,
    ahora: Optional[datetime] = None,
) -> ResultadoOperacion:
    """Deja constancia de que existe (o se revocó/denegó) una autorización.

    Se valida contra la versión vigente de la política: la finalidad y la
    base legal deben estar declaradas en ella, y si la política exige
    soporte, una autorización otorgada debe traer el medio y la referencia
    a su evidencia.
    """
    politica = politica_vigente(conn, codigo_politica)
    if politica is None:
        return ResultadoOperacion(exito=False, motivo_rechazo=f"No existe la política '{codigo_politica}'.")
    if politica.finalidad(finalidad) is None:
        declaradas = ", ".join(f.codigo for f in politica.finalidades)
        return ResultadoOperacion(
            exito=False,
            motivo_rechazo=f"La finalidad '{finalidad}' no está declarada en la política '{codigo_politica}' "
            f"(finalidades: {declaradas}).",
        )
    if base_legal not in politica.bases_legales:
        return ResultadoOperacion(
            exito=False,
            motivo_rechazo=f"La base legal '{base_legal}' no está admitida por la política '{codigo_politica}' "
            f"(admitidas: {', '.join(politica.bases_legales)}).",
        )
    estado = EstadoAutorizacion(estado)
    if (
        estado is EstadoAutorizacion.OTORGADA
        and politica.requiere_evidencia_autorizacion
        and not ((medio or "").strip() and (evidencia_ref or "").strip())
    ):
        return ResultadoOperacion(
            exito=False,
            motivo_rechazo="La política exige evidencia de la autorización: indique el medio y la referencia al soporte.",
        )
    if estado is EstadoAutorizacion.REVOCADA:
        vigente = estado_autorizacion(conn, paciente_id, codigo_politica, finalidad)
        if vigente is None or vigente.estado is not EstadoAutorizacion.OTORGADA:
            return ResultadoOperacion(
                exito=False, motivo_rechazo="No hay una autorización otorgada vigente que revocar para esa finalidad."
            )

    momento = _ahora(ahora)
    cursor = conn.execute(
        """
        INSERT INTO autorizaciones_tratamiento
            (paciente_id, politica_id, finalidad, base_legal, estado, medio, evidencia_ref, registrado_por, fecha)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (paciente_id, politica.id, finalidad, base_legal, estado.value, medio, evidencia_ref, usuario_id, momento.isoformat()),
    )
    autorizacion = _autorizacion_por_id(conn, cursor.lastrowid)
    _auditar(
        conn, usuario_id, TipoAccion.REGISTRAR_AUTORIZACION, paciente_id,
        f"Autorización {estado.value} para '{finalidad}' (política '{codigo_politica}' v{politica.version}, "
        f"base legal '{base_legal}').",
        momento,
    )
    return ResultadoOperacion(exito=True, registro=autorizacion)


def estado_autorizacion(
    conn: sqlite3.Connection, paciente_id: int, codigo_politica: str, finalidad: str
) -> Optional[Autorizacion]:
    """La autorización más reciente del paciente para esa finalidad (en
    cualquier versión de la política), o ``None`` si nunca se registró."""
    fila = conn.execute(
        """
        SELECT a.* FROM autorizaciones_tratamiento a
        JOIN politicas_tratamiento p ON p.id = a.politica_id
        WHERE a.paciente_id = ? AND p.codigo = ? AND a.finalidad = ?
        ORDER BY a.id DESC LIMIT 1
        """,
        (paciente_id, codigo_politica, finalidad),
    ).fetchone()
    return _fila_a_autorizacion(fila) if fila else None


def historial_autorizaciones(conn: sqlite3.Connection, paciente_id: int) -> Tuple[Autorizacion, ...]:
    filas = conn.execute(
        "SELECT * FROM autorizaciones_tratamiento WHERE paciente_id = ? ORDER BY id DESC", (paciente_id,)
    ).fetchall()
    return tuple(_fila_a_autorizacion(f) for f in filas)


def politica_de_autorizacion(conn: sqlite3.Connection, autorizacion: Autorizacion) -> PoliticaTratamiento:
    """La versión exacta de la política bajo la que se registró (AC3: con ella
    se identifica la descripción de la finalidad tal como estaba entonces)."""
    return _politica_por_id(conn, autorizacion.politica_id)


def verificar_tratamiento_permitido(
    conn: sqlite3.Connection, paciente_id: int, codigo_politica: str, finalidad: str
) -> DecisionTratamientoDatos:
    """¿Se puede tratar el dato del paciente para ``finalidad``?

    Fail-closed: política inexistente o finalidad no declarada se deniegan.
    Si la finalidad requiere autorización, la última registrada debe estar
    otorgada.
    """
    politica = politica_vigente(conn, codigo_politica)
    if politica is None:
        return DecisionTratamientoDatos(False, f"No existe la política '{codigo_politica}'.")
    definicion = politica.finalidad(finalidad)
    if definicion is None:
        return DecisionTratamientoDatos(
            False, f"La finalidad '{finalidad}' no está declarada en la política '{codigo_politica}'."
        )
    autorizacion = estado_autorizacion(conn, paciente_id, codigo_politica, finalidad)
    if not definicion.requiere_autorizacion:
        return DecisionTratamientoDatos(
            True,
            f"La política '{codigo_politica}' no exige autorización para '{finalidad}' "
            "(se ampara en otra base legal definida por la institución).",
            autorizacion,
        )
    if autorizacion is None:
        return DecisionTratamientoDatos(False, f"No hay autorización registrada para '{finalidad}'.")
    if autorizacion.estado is not EstadoAutorizacion.OTORGADA:
        return DecisionTratamientoDatos(
            False, f"La última autorización para '{finalidad}' está {autorizacion.estado.value}.", autorizacion
        )
    return DecisionTratamientoDatos(True, f"Autorización otorgada el {autorizacion.fecha}.", autorizacion)


# ---------------------------------------------------------------------------
# AC4 — Solicitudes de derechos del titular
# ---------------------------------------------------------------------------


def registrar_solicitud_derechos(
    conn: sqlite3.Connection,
    usuario_id: int,
    *,
    paciente_id: int,
    codigo_politica: str,
    tipo_derecho: str,
    descripcion: str,
    solicitante: str,
    ahora: Optional[datetime] = None,
) -> ResultadoOperacion:
    """Recibe una solicitud de derechos; su plazo sale de la política vigente."""
    politica = politica_vigente(conn, codigo_politica)
    if politica is None:
        return ResultadoOperacion(exito=False, motivo_rechazo=f"No existe la política '{codigo_politica}'.")
    if tipo_derecho not in politica.derechos:
        return ResultadoOperacion(
            exito=False,
            motivo_rechazo=f"La política '{codigo_politica}' no reconoce el derecho '{tipo_derecho}' "
            f"(reconoce: {', '.join(politica.derechos)}).",
        )
    if not (descripcion or "").strip() or not (solicitante or "").strip():
        return ResultadoOperacion(exito=False, motivo_rechazo="La solicitud necesita descripción y solicitante.")

    momento = _ahora(ahora)
    limite = momento + timedelta(days=politica.plazo_respuesta_dias)
    cursor = conn.execute(
        """
        INSERT INTO solicitudes_derechos
            (paciente_id, politica_id, tipo_derecho, descripcion, solicitante,
             fecha_recepcion, fecha_limite, registrado_por)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (paciente_id, politica.id, tipo_derecho, descripcion.strip(), solicitante.strip(),
         momento.isoformat(), limite.isoformat(), usuario_id),
    )
    solicitud_id = cursor.lastrowid
    conn.execute(
        "INSERT INTO eventos_solicitud_derechos (solicitud_id, estado, detalle, usuario_id, fecha) VALUES (?, ?, ?, ?, ?)",
        (solicitud_id, EstadoSolicitud.RECIBIDA.value, None, usuario_id, momento.isoformat()),
    )
    _auditar(
        conn, usuario_id, TipoAccion.GESTIONAR_DERECHOS_TITULAR, paciente_id,
        f"Solicitud #{solicitud_id} de '{tipo_derecho}' recibida; plazo hasta {limite.date().isoformat()}.",
        momento,
    )
    return ResultadoOperacion(exito=True, registro=obtener_solicitud(conn, solicitud_id, ahora=momento))


def actualizar_solicitud(
    conn: sqlite3.Connection,
    usuario_id: int,
    solicitud_id: int,
    estado: EstadoSolicitud,
    detalle: Optional[str] = None,
    ahora: Optional[datetime] = None,
) -> ResultadoOperacion:
    """Avanza una solicitud (en trámite, atendida o rechazada).

    Una solicitud cerrada no se reabre por este flujo, y cerrarla exige
    dejar escrito cómo se atendió o por qué se rechazó.
    """
    momento = _ahora(ahora)
    try:
        solicitud = obtener_solicitud(conn, solicitud_id, ahora=momento)
    except KeyError as exc:
        return ResultadoOperacion(exito=False, motivo_rechazo=str(exc.args[0]))
    estado = EstadoSolicitud(estado)
    if solicitud.estado in ESTADOS_FINALES:
        return ResultadoOperacion(
            exito=False, motivo_rechazo=f"La solicitud #{solicitud_id} ya está {solicitud.estado.value}."
        )
    if estado is EstadoSolicitud.RECIBIDA:
        return ResultadoOperacion(exito=False, motivo_rechazo="Una solicitud no puede volver a 'recibida'.")
    if estado in ESTADOS_FINALES and not (detalle or "").strip():
        return ResultadoOperacion(
            exito=False, motivo_rechazo="Para cerrar la solicitud se debe indicar cómo se atendió o por qué se rechazó."
        )

    conn.execute(
        "INSERT INTO eventos_solicitud_derechos (solicitud_id, estado, detalle, usuario_id, fecha) VALUES (?, ?, ?, ?, ?)",
        (solicitud_id, estado.value, detalle, usuario_id, momento.isoformat()),
    )
    _auditar(
        conn, usuario_id, TipoAccion.GESTIONAR_DERECHOS_TITULAR, solicitud.paciente_id,
        f"Solicitud #{solicitud_id} ({solicitud.tipo_derecho}) pasó a '{estado.value}'"
        + (f": {detalle.strip()}" if detalle else "."),
        momento,
    )
    return ResultadoOperacion(exito=True, registro=obtener_solicitud(conn, solicitud_id, ahora=momento))


def obtener_solicitud(
    conn: sqlite3.Connection, solicitud_id: int, ahora: Optional[datetime] = None
) -> SolicitudDerechos:
    fila = conn.execute("SELECT * FROM solicitudes_derechos WHERE id = ?", (solicitud_id,)).fetchone()
    if fila is None:
        raise KeyError(f"No existe ninguna solicitud de derechos con id={solicitud_id}.")
    eventos = tuple(
        EventoSolicitud(
            id=e["id"], solicitud_id=e["solicitud_id"], estado=EstadoSolicitud(e["estado"]),
            detalle=e["detalle"], usuario_id=e["usuario_id"], fecha=e["fecha"],
        )
        for e in conn.execute(
            "SELECT * FROM eventos_solicitud_derechos WHERE solicitud_id = ? ORDER BY id", (solicitud_id,)
        ).fetchall()
    )
    estado = eventos[-1].estado if eventos else EstadoSolicitud.RECIBIDA
    vencida = estado not in ESTADOS_FINALES and datetime.fromisoformat(fila["fecha_limite"]) < _ahora(ahora)
    return SolicitudDerechos(
        id=fila["id"], paciente_id=fila["paciente_id"], politica_id=fila["politica_id"],
        tipo_derecho=fila["tipo_derecho"], descripcion=fila["descripcion"], solicitante=fila["solicitante"],
        fecha_recepcion=fila["fecha_recepcion"], fecha_limite=fila["fecha_limite"],
        registrado_por=fila["registrado_por"], estado=estado, historial=eventos, vencida=vencida,
    )


def solicitudes_abiertas(conn: sqlite3.Connection, ahora: Optional[datetime] = None) -> Tuple[SolicitudDerechos, ...]:
    """Solicitudes sin cerrar, de la que vence primero a la última."""
    ids = [f["id"] for f in conn.execute("SELECT id FROM solicitudes_derechos ORDER BY fecha_limite, id").fetchall()]
    solicitudes = (obtener_solicitud(conn, i, ahora=ahora) for i in ids)
    return tuple(s for s in solicitudes if s.estado not in ESTADOS_FINALES)


def recopilar_informacion_titular(
    conn: sqlite3.Connection,
    usuario_id: int,
    paciente_id: int,
    *,
    conn_expediente: Optional[sqlite3.Connection] = None,
    conexiones_adicionales: Optional[Dict[str, sqlite3.Connection]] = None,
    solicitud_id: Optional[int] = None,
    ahora: Optional[datetime] = None,
) -> InformacionTitular:
    """Identifica y recupera la información del titular para atender su solicitud (AC4).

    Reúne:
      - ``privacidad``: sus autorizaciones y solicitudes;
      - ``auditoria``: quién accedió a su expediente (AUD-01), de ``conn``;
      - ``expediente``: sus filas en las tablas clínicas de ``conn_expediente``;
      - cualquier otra base con tablas de ``TABLAS_EXPEDIENTE`` en
        ``conexiones_adicionales`` (p. ej. la de ``patients``).

    La propia recopilación queda auditada.
    """
    momento = _ahora(ahora)
    secciones: Dict[str, List[Dict[str, Any]]] = {
        "privacidad.autorizaciones_tratamiento": _filas(
            conn, "SELECT * FROM autorizaciones_tratamiento WHERE paciente_id = ? ORDER BY id", paciente_id
        ),
        "privacidad.solicitudes_derechos": _filas(
            conn, "SELECT * FROM solicitudes_derechos WHERE paciente_id = ? ORDER BY id", paciente_id
        ),
        "auditoria.eventos_acceso": [e.__dict__ | {"accion": e.accion.value} for e in obtener_eventos_de_paciente(conn, paciente_id)],
    }
    fuentes = dict(conexiones_adicionales or {})
    if conn_expediente is not None:
        fuentes = {"expediente": conn_expediente, **fuentes}
    for nombre_fuente, conexion in fuentes.items():
        existentes = _tablas_existentes(conexion)
        for tabla, columna in TABLAS_EXPEDIENTE:
            if tabla in existentes:
                secciones[f"{nombre_fuente}.{tabla}"] = _filas(
                    conexion, f"SELECT * FROM {tabla} WHERE {columna} = ? ORDER BY id", paciente_id
                )

    informacion = InformacionTitular(paciente_id=paciente_id, generado_en=momento.isoformat(), secciones=secciones)
    referencia = f" para la solicitud #{solicitud_id}" if solicitud_id is not None else ""
    _auditar(
        conn, usuario_id, TipoAccion.GESTIONAR_DERECHOS_TITULAR, paciente_id,
        f"Información del titular recopilada{referencia}: {informacion.total_registros} registro(s) "
        f"de {len(secciones)} sección(es).",
        momento,
    )
    return informacion


# ---------------------------------------------------------------------------


def _filas(conn: sqlite3.Connection, sql: str, *parametros: Any) -> List[Dict[str, Any]]:
    cursor = conn.execute(sql, parametros)
    columnas = [c[0] for c in cursor.description]
    return [dict(zip(columnas, fila)) for fila in cursor.fetchall()]


def _tablas_existentes(conn: sqlite3.Connection) -> Iterable[str]:
    return {f[0] for f in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}


def _autorizacion_por_id(conn: sqlite3.Connection, autorizacion_id: int) -> Autorizacion:
    fila = conn.execute("SELECT * FROM autorizaciones_tratamiento WHERE id = ?", (autorizacion_id,)).fetchone()
    return _fila_a_autorizacion(fila)


def _fila_a_autorizacion(fila: sqlite3.Row) -> Autorizacion:
    return Autorizacion(
        id=fila["id"], paciente_id=fila["paciente_id"], politica_id=fila["politica_id"],
        finalidad=fila["finalidad"], base_legal=fila["base_legal"], estado=EstadoAutorizacion(fila["estado"]),
        medio=fila["medio"], evidencia_ref=fila["evidencia_ref"], registrado_por=fila["registrado_por"],
        fecha=fila["fecha"],
    )


def _fila_a_politica(fila: sqlite3.Row) -> PoliticaTratamiento:
    return PoliticaTratamiento(
        id=fila["id"], codigo=fila["codigo"], version=fila["version"], jurisdiccion=fila["jurisdiccion"],
        nombre=fila["nombre"], marco_normativo=fila["marco_normativo"],
        finalidades=tuple(Finalidad(**f) for f in json.loads(fila["finalidades_json"])),
        bases_legales=tuple(json.loads(fila["bases_legales_json"])),
        derechos=tuple(json.loads(fila["derechos_json"])),
        plazo_respuesta_dias=fila["plazo_respuesta_dias"],
        requiere_evidencia_autorizacion=bool(fila["requiere_evidencia_autorizacion"]),
        configurado_por=fila["configurado_por"], fecha=fila["fecha"],
    )
