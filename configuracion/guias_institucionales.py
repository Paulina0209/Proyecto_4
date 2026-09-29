"""CFG-01 — Configuración de guías clínicas institucionales.

Como administrador clínico, quiero configurar qué guías clínicas usa la
institución por defecto, para adaptar el sistema a sus protocolos internos.

El administrador clínico elige qué organizaciones usa la institución (hoy
NCCN y/o ESMO), en orden de prioridad, y puede declarar un protocolo
interno propio. La configuración vigente es la que consume el resto del
sistema:

    - EV-01 (dependencia de la historia): ``buscar_evidencia_institucional``
      busca solo en las guías habilitadas y, a igual relevancia, pone
      primero la organización preferida.
    - TX-01 y otros consumidores: ``modulos_habilitados`` devuelve las
      carpetas de ``guidelines/`` que corresponden a la configuración.

Salvaguardas (riesgos CFG del backlog):

    - Solo el rol ``administrador_clinico`` puede cambiarla (SEC-01). Los
      intentos denegados también quedan auditados.
    - Cada cambio es una versión nueva con autor, fecha y motivo
      obligatorio, y queda en la auditoría de AUD-01. Nunca se edita.
    - Una organización desconocida se rechaza (evita erratas como "ESMOO").
    - Si la configuración dejaría al sistema sin ningún módulo de guía
      computable, se exige confirmarlo explícitamente
      (``confirmar_sin_modulos``): esa configuración afectaría a todos
      los pacientes de la institución.
    - Mientras nadie configure nada, se usan todas las guías disponibles y
      la configuración se marca ``es_por_defecto_del_sistema``.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from auditoria.models import TipoAccion
from auditoria.registro_acceso import inicializar_schema as inicializar_schema_auditoria
from auditoria.registro_acceso import registrar_acceso
from evidencia_clinica.catalog import load_guideline_catalog
from evidencia_clinica.models import EvidenceDocument, EvidenceSearchResult
from evidencia_clinica.service import EvidenceSearchService, organization_matches
from seguridad.autorizacion import Accion, verificar_permiso
from seguridad.models import Usuario

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema_configuracion.sql"
RAIZ_PROYECTO = Path(__file__).resolve().parents[1]

#: Organizaciones que la institución puede elegir. Agregar una es agregarla
#: aquí; que tenga o no módulos computables se calcula del catálogo real.
ORGANIZACIONES_RECONOCIDAS: Tuple[str, ...] = ("ESMO", "NCCN")


@dataclass(frozen=True)
class ProtocoloInterno:
    nombre: str
    #: Dónde está el documento oficial (código de documento, URL, ruta...).
    referencia: str


@dataclass(frozen=True)
class ConfiguracionGuias:
    #: None si es la configuración por defecto del sistema.
    version: Optional[int]
    organizaciones: Tuple[str, ...]
    protocolo_interno: Optional[ProtocoloInterno]
    motivo: Optional[str]
    configurado_por: Optional[int]
    fecha: Optional[str]
    es_por_defecto_del_sistema: bool
    #: Carpetas de ``guidelines/`` habilitadas por esta configuración.
    modulos_habilitados: Tuple[str, ...]
    advertencias: Tuple[str, ...]


@dataclass(frozen=True)
class ResultadoConfiguracion:
    exito: bool
    configuracion: Optional[ConfiguracionGuias] = None
    motivo_rechazo: Optional[str] = None
    advertencias: Tuple[str, ...] = ()


def crear_conexion(ruta: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(ruta)
    conn.row_factory = sqlite3.Row
    inicializar_esquema(conn)
    return conn


def inicializar_esquema(conn: sqlite3.Connection) -> None:
    """Crea la tabla de CFG-01 y la de auditoría (AUD-01), donde queda la traza."""
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    inicializar_schema_auditoria(conn)
    conn.commit()


# ---------------------------------------------------------------------------
# Escritura
# ---------------------------------------------------------------------------


def configurar_guias(
    conn: sqlite3.Connection,
    usuario: Usuario,
    organizaciones: Sequence[str],
    motivo: str,
    protocolo_interno: Optional[ProtocoloInterno] = None,
    confirmar_sin_modulos: bool = False,
    raiz: Path = RAIZ_PROYECTO,
    ahora: Optional[datetime] = None,
) -> ResultadoConfiguracion:
    """Publica una nueva versión de las guías institucionales por defecto.

    ``organizaciones`` va en orden de prioridad (la primera es la preferida).
    """
    momento = ahora or datetime.now(timezone.utc)

    autorizacion = verificar_permiso(usuario, Accion.CONFIGURAR_GUIAS_INSTITUCIONALES)
    if not autorizacion.permitido:
        registrar_acceso(
            conn, usuario.id, TipoAccion.CONFIGURAR_GUIAS,
            detalle=f"DENEGADO: intento de configurar guías institucionales ({autorizacion.motivo_rechazo})",
            ahora=momento,
        )
        return ResultadoConfiguracion(exito=False, motivo_rechazo=autorizacion.motivo_rechazo)

    seleccion, errores = _normalizar_organizaciones(organizaciones)
    if protocolo_interno is not None and not (
        protocolo_interno.nombre.strip() and protocolo_interno.referencia.strip()
    ):
        errores.append("El protocolo interno necesita nombre y referencia al documento oficial.")
    if not seleccion and protocolo_interno is None:
        errores.append("Seleccione al menos una organización o declare un protocolo interno.")
    if not (motivo or "").strip():
        errores.append("Indique el motivo del cambio (queda en el historial de configuración).")
    if errores:
        return ResultadoConfiguracion(exito=False, motivo_rechazo=" ".join(errores))

    catalogo = load_guideline_catalog(raiz)
    modulos = _modulos_de(catalogo, seleccion)
    advertencias = _advertencias(catalogo, seleccion, protocolo_interno)
    if not modulos and not confirmar_sin_modulos:
        return ResultadoConfiguracion(
            exito=False,
            motivo_rechazo=(
                "Con esta configuración el sistema no tendría ningún módulo de guía computable, "
                "lo que afecta a todos los pacientes de la institución. Si es intencional, "
                "confírmelo con confirmar_sin_modulos=True."
            ),
            advertencias=advertencias,
        )

    version = (conn.execute("SELECT MAX(version) FROM configuracion_guias_institucionales").fetchone()[0] or 0) + 1
    conn.execute(
        """
        INSERT INTO configuracion_guias_institucionales
            (version, organizaciones_json, protocolo_interno_nombre, protocolo_interno_referencia,
             motivo, configurado_por, fecha)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            version,
            json.dumps(seleccion),
            protocolo_interno.nombre.strip() if protocolo_interno else None,
            protocolo_interno.referencia.strip() if protocolo_interno else None,
            motivo.strip(),
            usuario.id,
            momento.isoformat(),
        ),
    )
    protocolo = f"; protocolo interno '{protocolo_interno.nombre.strip()}'" if protocolo_interno else ""
    registrar_acceso(  # hace commit: la versión y su evento se confirman juntos
        conn, usuario.id, TipoAccion.CONFIGURAR_GUIAS,
        detalle=(
            f"Guías institucionales v{version}: {', '.join(seleccion) or 'ninguna organización'}{protocolo}. "
            f"Motivo: {motivo.strip()}"
        ),
        ahora=momento,
    )
    configuracion = obtener_configuracion_vigente(conn, raiz)
    return ResultadoConfiguracion(exito=True, configuracion=configuracion, advertencias=configuracion.advertencias)


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------


def obtener_configuracion_vigente(conn: sqlite3.Connection, raiz: Path = RAIZ_PROYECTO) -> ConfiguracionGuias:
    fila = conn.execute(
        "SELECT * FROM configuracion_guias_institucionales ORDER BY version DESC LIMIT 1"
    ).fetchone()
    catalogo = load_guideline_catalog(raiz)
    if fila is None:
        disponibles = tuple(o for o in ORGANIZACIONES_RECONOCIDAS if _modulos_de(catalogo, [o]))
        return ConfiguracionGuias(
            version=None,
            organizaciones=disponibles,
            protocolo_interno=None,
            motivo=None,
            configurado_por=None,
            fecha=None,
            es_por_defecto_del_sistema=True,
            modulos_habilitados=_modulos_de(catalogo, disponibles),
            advertencias=(
                "La institución todavía no ha configurado sus guías: se usan todas las disponibles.",
            ),
        )
    return _fila_a_configuracion(fila, catalogo)


def historial_configuracion(conn: sqlite3.Connection, raiz: Path = RAIZ_PROYECTO) -> Tuple[ConfiguracionGuias, ...]:
    """Todas las versiones, de la más reciente a la más antigua."""
    catalogo = load_guideline_catalog(raiz)
    filas = conn.execute("SELECT * FROM configuracion_guias_institucionales ORDER BY version DESC").fetchall()
    return tuple(_fila_a_configuracion(f, catalogo) for f in filas)


def configuracion_en_fecha(
    conn: sqlite3.Connection, fecha: datetime, raiz: Path = RAIZ_PROYECTO
) -> Optional[ConfiguracionGuias]:
    """La configuración que estaba vigente en ``fecha`` (None si todavía no
    había ninguna), para reconstruir decisiones pasadas."""
    fila = conn.execute(
        "SELECT * FROM configuracion_guias_institucionales WHERE fecha <= ? ORDER BY version DESC LIMIT 1",
        (fecha.isoformat(),),
    ).fetchone()
    return _fila_a_configuracion(fila, load_guideline_catalog(raiz)) if fila else None


def modulos_habilitados(conn: sqlite3.Connection, raiz: Path = RAIZ_PROYECTO) -> Tuple[str, ...]:
    """Carpetas de ``guidelines/`` que la institución usa por defecto."""
    return obtener_configuracion_vigente(conn, raiz).modulos_habilitados


def buscar_evidencia_institucional(
    conn: sqlite3.Connection,
    consulta: str,
    servicio: Optional[EvidenceSearchService] = None,
    limit: int = 5,
    raiz: Path = RAIZ_PROYECTO,
) -> List[EvidenceSearchResult]:
    """EV-01 restringido a las guías institucionales vigentes."""
    configuracion = obtener_configuracion_vigente(conn, raiz)
    servicio = servicio or EvidenceSearchService(raiz)
    return servicio.search(consulta, limit=limit, organizations=configuracion.organizaciones)


# ---------------------------------------------------------------------------


def _normalizar_organizaciones(organizaciones: Sequence[str]) -> Tuple[List[str], List[str]]:
    reconocidas = {o.casefold(): o for o in ORGANIZACIONES_RECONOCIDAS}
    seleccion: List[str] = []
    errores: List[str] = []
    for organizacion in organizaciones:
        canonica = reconocidas.get((organizacion or "").strip().casefold())
        if canonica is None:
            errores.append(
                f"Organización no reconocida: {organizacion!r} (reconocidas: {', '.join(ORGANIZACIONES_RECONOCIDAS)})."
            )
        elif canonica in seleccion:
            errores.append(f"La organización {canonica} está repetida.")
        else:
            seleccion.append(canonica)
    return seleccion, errores


def _carpeta(documento: EvidenceDocument) -> str:
    # source_path = "guidelines/<carpeta>/metadata.yaml"
    return Path(documento.source_path).parent.name


def _modulos_de(catalogo: Sequence[EvidenceDocument], organizaciones: Sequence[str]) -> Tuple[str, ...]:
    return tuple(
        sorted(
            _carpeta(d) for d in catalogo if any(organization_matches(d.organization, o) for o in organizaciones)
        )
    )


def _advertencias(
    catalogo: Sequence[EvidenceDocument],
    organizaciones: Sequence[str],
    protocolo_interno: Optional[ProtocoloInterno],
) -> Tuple[str, ...]:
    advertencias = [
        f"{o} está seleccionada, pero el sistema no tiene módulos de guía computables de {o}: "
        "sus recomendaciones no tendrán soporte automatizado hasta que se carguen."
        for o in organizaciones
        if not _modulos_de(catalogo, [o])
    ]
    if protocolo_interno is not None:
        advertencias.append(
            f"El protocolo interno '{protocolo_interno.nombre}' queda registrado como referencia "
            "institucional; el sistema no lo evalúa automáticamente."
        )
    return tuple(advertencias)


def _fila_a_configuracion(fila: sqlite3.Row, catalogo: Sequence[EvidenceDocument]) -> ConfiguracionGuias:
    organizaciones = tuple(json.loads(fila["organizaciones_json"]))
    protocolo = (
        ProtocoloInterno(fila["protocolo_interno_nombre"], fila["protocolo_interno_referencia"])
        if fila["protocolo_interno_nombre"]
        else None
    )
    return ConfiguracionGuias(
        version=fila["version"],
        organizaciones=organizaciones,
        protocolo_interno=protocolo,
        motivo=fila["motivo"],
        configurado_por=fila["configurado_por"],
        fecha=fila["fecha"],
        es_por_defecto_del_sistema=False,
        modulos_habilitados=_modulos_de(catalogo, organizaciones),
        advertencias=_advertencias(catalogo, organizaciones, protocolo),
    )
