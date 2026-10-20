"""CFG-02 — Notificaciones y alertas.

Como oncólogo, quiero configurar notificaciones y alertas (ej. resultados
críticos, estudios pendientes), para no perder información relevante.

Cada oncólogo elige qué eventos le avisan y por qué canal:

    Eventos                                  De dónde salen (no se duplican datos)
    resultado_critico      Resultado crítico de laboratorio   HC-02: ``alertas_laboratorio`` activas del expediente
    estudio_pendiente      Estudio pendiente                  PAC-03: ``alertas`` de tipo estudio_pendiente sin resolver
    interaccion_detectada  Interacción detectada              PAC-03: ``alertas`` de tipo interaccion sin resolver

    Canales
    en_aplicacion   la bandeja de «Notificaciones» de la interfaz (el único por ahora)

Mientras el oncólogo no configure nada, todos los eventos avisan en la aplicación.
Solo ve notificaciones de SUS pacientes (los de su ``oncologo_id``, SEC-01). Marcar una
notificación como leída es solo de quien la lee: no resuelve la alerta de origen (eso se
hace donde corresponde, p. ej. revisar la alerta de laboratorio en HC-02).

Las tablas viven en la base de pacientes (``schema_notificaciones.sql``).
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema_notificaciones.sql"

EVENTOS: Dict[str, Dict[str, str]] = {
    "resultado_critico": {"etiqueta": "Resultado crítico de laboratorio",
                          "descripcion": "Un valor de laboratorio fuera del rango crítico."},
    "estudio_pendiente": {"etiqueta": "Estudio pendiente",
                          "descripcion": "Un estudio solicitado que aún no tiene resultado."},
    "interaccion_detectada": {"etiqueta": "Interacción detectada",
                              "descripcion": "Una interacción o contraindicación con la medicación del paciente."},
}

CANALES: Dict[str, Dict[str, object]] = {
    "en_aplicacion": {"etiqueta": "En la aplicación", "disponible": True, "nota": None},
}

CANALES_POR_DEFECTO: Tuple[str, ...] = ("en_aplicacion",)

#: Tipo de la tabla ``alertas`` (base de pacientes) -> evento.
_EVENTO_DE_ALERTA = {"estudio_pendiente": "estudio_pendiente", "interaccion": "interaccion_detectada"}
_ORDEN_SEVERIDAD = {"critica": 0, "alta": 1, "media": 2, "baja": 3}


class ErrorPreferencias(ValueError):
    """Preferencias inválidas. ``errores``: lista de (campo, mensaje), como el resto de la API."""

    def __init__(self, errores: List[Tuple[str, str]]):
        self.errores = errores
        super().__init__("; ".join(m for _c, m in errores))


class NotificacionNoEncontrada(LookupError):
    pass


@dataclass(frozen=True)
class PreferenciaNotificacion:
    evento: str
    activo: bool
    canales: Tuple[str, ...]


@dataclass(frozen=True)
class Notificacion:
    id: str                       # estable: "lab-<id>" (HC-02) o "alerta-<id>" (PAC-03)
    evento: str
    titulo: str
    mensaje: str
    severidad: str
    fecha: str
    paciente_id: int
    paciente: str
    canales: Tuple[str, ...]
    leida: bool = False

    def a_dict(self) -> dict:
        datos = asdict(self)
        datos["canales"] = list(self.canales)
        return datos


@dataclass(frozen=True)
class ConfiguracionNotificaciones:
    usuario_id: int
    preferencias: Tuple[PreferenciaNotificacion, ...]
    actualizado_en: Optional[str] = None
    eventos: Dict[str, Dict[str, str]] = field(default_factory=lambda: EVENTOS)

    def de(self, evento: str) -> PreferenciaNotificacion:
        return next(p for p in self.preferencias if p.evento == evento)

    def a_dict(self) -> dict:
        return {
            "eventos": [{"evento": p.evento, **EVENTOS[p.evento], "activo": p.activo, "canales": list(p.canales)}
                        for p in self.preferencias],
            "canales": [{"valor": c, **datos} for c, datos in CANALES.items()],
            "actualizado_en": self.actualizado_en,
            "es_por_defecto": self.actualizado_en is None,
        }


def inicializar_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


# ---------------------------------------------------------------------------
# Preferencias
# ---------------------------------------------------------------------------

def obtener_preferencias(conn: sqlite3.Connection, usuario_id: int) -> ConfiguracionNotificaciones:
    inicializar_schema(conn)
    guardadas = {f["evento"]: f for f in conn.execute(
        "SELECT evento, activo, canales, actualizado_en FROM preferencias_notificacion WHERE usuario_id = ?", (usuario_id,))}
    preferencias = []
    for evento in EVENTOS:
        fila = guardadas.get(evento)
        if fila is None:
            preferencias.append(PreferenciaNotificacion(evento, True, CANALES_POR_DEFECTO))
        else:
            canales = tuple(c for c in fila["canales"].split(",") if c in CANALES)
            if fila["activo"] and not canales:  # p. ej. guardada solo con el antiguo canal de correo
                canales = CANALES_POR_DEFECTO
            preferencias.append(PreferenciaNotificacion(evento, bool(fila["activo"]), canales))
    actualizado = max((f["actualizado_en"] for f in guardadas.values()), default=None)
    return ConfiguracionNotificaciones(usuario_id, tuple(preferencias), actualizado)


def _validar(preferencias: Iterable[Mapping]) -> List[PreferenciaNotificacion]:
    errores: List[Tuple[str, str]] = []
    validas: Dict[str, PreferenciaNotificacion] = {}
    for p in preferencias:
        evento = str((p or {}).get("evento") or "")
        if evento not in EVENTOS:
            errores.append(("evento", f"Evento desconocido: '{evento}'. Use uno de: {', '.join(EVENTOS)}."))
            continue
        canales, desconocidos = [], [c for c in (p.get("canales") or []) if c not in CANALES]
        for c in desconocidos:
            errores.append((f"canales.{evento}", f"Canal desconocido: '{c}'. Use uno de: {', '.join(CANALES)}."))
        for c in (p.get("canales") or []):
            if c in CANALES and c not in canales:
                canales.append(c)
        activo = bool(p.get("activo", True))
        if activo and not canales and not desconocidos:
            errores.append((f"canales.{evento}",
                            f"Elige al menos un canal para «{EVENTOS[evento]['etiqueta']}» o desactiva el aviso."))
        validas[evento] = PreferenciaNotificacion(evento, activo, tuple(canales))
    if errores:
        raise ErrorPreferencias(errores)
    if not validas:
        raise ErrorPreferencias([("preferencias", "No se recibió ninguna preferencia.")])
    return list(validas.values())


def guardar_preferencias(
    conn: sqlite3.Connection, usuario_id: int, preferencias: Iterable[Mapping], ahora: Optional[datetime] = None
) -> ConfiguracionNotificaciones:
    """Guarda las preferencias recibidas (los eventos que no vengan quedan como estaban).

    Todo o nada: si una preferencia es inválida no se guarda ninguna."""
    inicializar_schema(conn)
    validas = _validar(preferencias)
    momento = (ahora or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    with conn:
        for p in validas:
            conn.execute(
                "INSERT INTO preferencias_notificacion (usuario_id, evento, activo, canales, actualizado_en) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (usuario_id, evento) DO UPDATE SET activo = excluded.activo, canales = excluded.canales, "
                "actualizado_en = excluded.actualizado_en",
                (usuario_id, p.evento, int(p.activo), ",".join(p.canales), momento))
    return obtener_preferencias(conn, usuario_id)


# ---------------------------------------------------------------------------
# Bandeja
# ---------------------------------------------------------------------------

def _candidatas(conn: sqlite3.Connection, conn_exp: Optional[sqlite3.Connection], oncologo_id: int) -> List[Notificacion]:
    pacientes = {f["id"]: f for f in conn.execute(
        "SELECT id, nombre_completo, numero_identificacion FROM pacientes WHERE oncologo_id = ?", (oncologo_id,))}
    if not pacientes:
        return []
    encontradas: List[Notificacion] = []
    marcas = ",".join("?" * len(pacientes))
    for f in conn.execute(
            f"SELECT id, paciente_id, tipo, severidad, descripcion, fecha FROM alertas "
            f"WHERE resuelta = 0 AND paciente_id IN ({marcas})", tuple(pacientes)):
        evento = _EVENTO_DE_ALERTA.get(f["tipo"])
        if evento:
            encontradas.append(Notificacion(
                id=f"alerta-{f['id']}", evento=evento, titulo=EVENTOS[evento]["etiqueta"], mensaje=f["descripcion"],
                severidad=f["severidad"], fecha=f["fecha"], paciente_id=f["paciente_id"],
                paciente=pacientes[f["paciente_id"]]["nombre_completo"], canales=()))
    tiene_alertas_lab = conn_exp is not None and conn_exp.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'alertas_laboratorio'").fetchone() is not None
    if tiene_alertas_lab:
        # El mismo paciente en las dos bases se reconoce por su identificación (patients/expediente.py).
        por_identificacion = {p["numero_identificacion"]: p for p in pacientes.values()}
        for f in conn_exp.execute(
                "SELECT a.id, a.prueba, a.valor, a.unidad, a.limite_superado, a.severidad, a.fecha, p.identificacion "
                "FROM alertas_laboratorio a JOIN pacientes p ON p.id = a.paciente_id WHERE a.estado = 'activa'"):
            paciente = por_identificacion.get(f["identificacion"])
            if paciente is None:
                continue
            valor = f"{f['prueba']} {f['valor']} {f['unidad'] or ''}".strip()
            encontradas.append(Notificacion(
                id=f"lab-{f['id']}", evento="resultado_critico", titulo=EVENTOS["resultado_critico"]["etiqueta"],
                mensaje=f"{valor}: valor crítico ({f['limite_superado']}). Revísalo en Laboratorios.",
                severidad=f["severidad"] or "critica", fecha=f["fecha"], paciente_id=paciente["id"],
                paciente=paciente["nombre_completo"], canales=()))
    return encontradas


def notificaciones_de(
    conn: sqlite3.Connection, conn_exp: Optional[sqlite3.Connection], oncologo_id: int, usuario_id: Optional[int] = None,
) -> List[Notificacion]:
    """Lo que la bandeja de la aplicación muestra: eventos activos con el canal ``en_aplicacion``.

    Primero las no leídas; dentro de ellas, la más grave y la más reciente."""
    usuario_id = oncologo_id if usuario_id is None else usuario_id
    config = obtener_preferencias(conn, usuario_id)
    leidas = {f[0] for f in conn.execute("SELECT notificacion_id FROM notificaciones_leidas WHERE usuario_id = ?", (usuario_id,))}
    resultado = []
    for n in _candidatas(conn, conn_exp, oncologo_id):
        pref = config.de(n.evento)
        if not pref.activo or "en_aplicacion" not in pref.canales:
            continue
        resultado.append(Notificacion(**{**asdict(n), "canales": pref.canales, "leida": n.id in leidas}))
    resultado.sort(key=lambda n: n.fecha, reverse=True)
    resultado.sort(key=lambda n: (n.leida, _ORDEN_SEVERIDAD.get(n.severidad, 9)))
    return resultado


def marcar_leida(
    conn: sqlite3.Connection, conn_exp: Optional[sqlite3.Connection], oncologo_id: int, notificacion_id: str,
    usuario_id: Optional[int] = None, ahora: Optional[datetime] = None,
) -> Notificacion:
    """Marca como leída una notificación de la bandeja de quien la lee (idempotente)."""
    usuario_id = oncologo_id if usuario_id is None else usuario_id
    notificacion = next((n for n in notificaciones_de(conn, conn_exp, oncologo_id, usuario_id) if n.id == notificacion_id), None)
    if notificacion is None:
        raise NotificacionNoEncontrada(f"No tienes la notificación {notificacion_id}.")
    momento = (ahora or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    with conn:
        conn.execute("INSERT OR IGNORE INTO notificaciones_leidas (usuario_id, notificacion_id, leida_en) VALUES (?, ?, ?)",
                     (usuario_id, notificacion_id, momento))
    return Notificacion(**{**asdict(notificacion), "leida": True})
