"""HC-02 — Integración de resultados de laboratorio.

Como oncólogo, quiero que los resultados de laboratorio se integren
automáticamente al expediente, para monitorear tendencias sin pedir el dato
al paciente o a otro sistema.

Dos vías de recepción, que terminan en el mismo procesamiento:

    - **Interfaz de laboratorio** (HL7 v2 ORU, FHIR, cBioPortal): HC-01
      (``integracion_externa._importar``) guarda los resultados y llama a
      ``procesar_resultados`` dentro de la misma transacción.
    - **Registro manual** (``registrar_resultado_laboratorio``).

Criterios de aceptación:

    - AC1: el resultado queda asociado al paciente correcto y a su fecha.
      Riesgo de la historia: asociarlo a otro paciente es grave, así que se
      hace doble validación (identificación + nombre) antes de guardar
      nada; si no coinciden, no se guarda ningún dato.
    - AC2: un valor fuera del rango crítico (``rangos_criticos_laboratorio.yaml``)
      genera una alerta en ``alertas_laboratorio``, visible en el 360 hasta
      que se marca como revisada.
    - AC3: dos resultados del mismo marcador en el mismo momento con valores
      distintos no se sobrescriben: ambos se conservan y el conflicto queda
      en ``conflictos_laboratorio`` para revisión.

Reglas fail-closed:

    - Un resultado en una unidad distinta a la del rango crítico no se
      evalúa (no se convierten unidades). La tendencia separa las series por
      unidad en vez de mezclarlas.
    - Si de dos resultados del mismo día solo uno trae hora, no se puede
      descartar que sean del mismo momento: se comparan por día.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

import yaml

from historia_clinica.db import ahora_iso, normalizar_texto
from expediente.repository import obtener_paciente

RUTA_RANGOS_POR_DEFECTO = Path(__file__).resolve().parent / "rangos_criticos_laboratorio.yaml"

ORIGEN_MANUAL = "manual"

RESOLUCIONES_CONFLICTO = ("valido_a", "valido_b", "ambos_validos", "ninguno_valido")


class ErrorLaboratorio(ValueError):
    """Datos de laboratorio inválidos o una operación que no se puede hacer."""


class ErrorConfiguracionLaboratorio(ValueError):
    """El archivo de rangos críticos no es válido."""


class IdentidadNoCoincideError(ErrorLaboratorio):
    """La identificación o el nombre no corresponden al paciente del expediente."""


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RangoCritico:
    codigo: str
    nombre: str
    alias: Tuple[str, ...]
    unidades: Tuple[str, ...]
    critico_bajo: Optional[float]
    critico_alto: Optional[float]
    #: Las grafías tal como están en el YAML (para mostrar).
    unidades_originales: Tuple[str, ...] = ()


@dataclass(frozen=True)
class AlertaLaboratorio:
    id: int
    paciente_id: int
    laboratorio_id: int
    prueba: str
    valor: str
    unidad: Optional[str]
    limite_superado: str
    severidad: str
    estado: str
    fecha: str
    revisada_por: Optional[str]
    fecha_revision: Optional[str]


@dataclass(frozen=True)
class ConflictoLaboratorio:
    id: int
    paciente_id: int
    prueba_normalizada: str
    momento: str
    laboratorio_a_id: int
    laboratorio_b_id: int
    estado: str
    resolucion: Optional[str]
    resuelto_por: Optional[str]
    fecha_resolucion: Optional[str]
    nota: Optional[str]
    fecha_deteccion: str
    #: Los dos resultados en conflicto, para mostrarlos lado a lado.
    valor_a: str = ""
    valor_b: str = ""
    unidad_a: Optional[str] = None
    unidad_b: Optional[str] = None
    prueba: str = ""


@dataclass(frozen=True)
class ResultadoRegistroLaboratorio:
    laboratorio_id: int
    alerta: Optional[AlertaLaboratorio]
    conflictos: Tuple[ConflictoLaboratorio, ...]


@dataclass(frozen=True)
class ResultadoProcesamiento:
    alertas: Tuple[int, ...]
    conflictos: Tuple[int, ...]


@dataclass(frozen=True)
class ResumenMarcador:
    clave: str
    prueba: str
    cantidad: int
    ultima_fecha: str
    ultimo_valor: str
    unidad: Optional[str]


@dataclass(frozen=True)
class PuntoTendencia:
    laboratorio_id: int
    fecha: str
    fecha_hora: Optional[str]
    valor: str
    valor_numerico: Optional[float]
    unidad: Optional[str]
    alterado: bool
    critico: bool
    en_conflicto: bool


@dataclass(frozen=True)
class SerieTendencia:
    unidad: Optional[str]
    puntos: Tuple[PuntoTendencia, ...]


@dataclass(frozen=True)
class TendenciaMarcador:
    clave: str
    prueba: str
    series: Tuple[SerieTendencia, ...]
    advertencias: Tuple[str, ...]

    @property
    def vacia(self) -> bool:
        return not self.series


# ---------------------------------------------------------------------------
# Configuración de rangos críticos
# ---------------------------------------------------------------------------

_CACHE_RANGOS: Dict[Path, Dict[str, RangoCritico]] = {}


def normalizar_unidad(unidad: Optional[str]) -> str:
    texto = (unidad or "").strip().lower().replace("µ", "u").replace("μ", "u")
    return re.sub(r"\s+", "", texto)


def cargar_rangos_criticos(ruta: Union[str, Path] = RUTA_RANGOS_POR_DEFECTO) -> Dict[str, RangoCritico]:
    """Lee y valida el YAML de rangos críticos. Un archivo inválido se
    rechaza completo: una configuración a medias podría perder alertas."""
    ruta = Path(ruta)
    if ruta in _CACHE_RANGOS:
        return _CACHE_RANGOS[ruta]
    try:
        datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ErrorConfiguracionLaboratorio(f"No se pudo leer {ruta}: {exc}") from exc
    rangos = validar_rangos(datos)
    _CACHE_RANGOS[ruta] = rangos
    return rangos


def validar_rangos(datos: Dict[str, Any]) -> Dict[str, RangoCritico]:
    pruebas = datos.get("pruebas") if isinstance(datos, dict) else None
    if not isinstance(pruebas, dict) or not pruebas:
        raise ErrorConfiguracionLaboratorio("El archivo de rangos críticos debe tener una sección 'pruebas' no vacía.")

    rangos: Dict[str, RangoCritico] = {}
    vistos: Dict[str, str] = {}
    for codigo, item in pruebas.items():
        if not isinstance(item, dict):
            raise ErrorConfiguracionLaboratorio(f"La prueba '{codigo}' debe ser un diccionario.")
        nombre = item.get("nombre")
        alias = item.get("alias") or []
        unidades = item.get("unidades") or []
        if not nombre or not isinstance(alias, list) or not alias or not isinstance(unidades, list) or not unidades:
            raise ErrorConfiguracionLaboratorio(f"La prueba '{codigo}' necesita nombre, alias y unidades.")
        bajo, alto = item.get("critico_bajo"), item.get("critico_alto")
        for limite in (bajo, alto):
            if limite is not None and not isinstance(limite, (int, float)):
                raise ErrorConfiguracionLaboratorio(f"Los límites de '{codigo}' deben ser numéricos.")
        if bajo is None and alto is None:
            raise ErrorConfiguracionLaboratorio(f"La prueba '{codigo}' necesita al menos un límite crítico.")
        if bajo is not None and alto is not None and bajo >= alto:
            raise ErrorConfiguracionLaboratorio(f"En '{codigo}', critico_bajo debe ser menor que critico_alto.")

        alias_norm = tuple(normalizar_texto(str(a)) for a in alias)
        for a in alias_norm:
            if a in vistos:
                raise ErrorConfiguracionLaboratorio(f"El alias '{a}' está en '{vistos[a]}' y en '{codigo}'.")
            vistos[a] = codigo
        rangos[codigo] = RangoCritico(
            codigo=codigo,
            nombre=nombre,
            alias=alias_norm,
            unidades=tuple(normalizar_unidad(str(u)) for u in unidades),
            critico_bajo=float(bajo) if bajo is not None else None,
            critico_alto=float(alto) if alto is not None else None,
            unidades_originales=tuple(str(u) for u in unidades),
        )
    return rangos


def buscar_rango(prueba: str, rangos: Dict[str, RangoCritico]) -> Optional[RangoCritico]:
    nombre = normalizar_texto(prueba)
    return next((r for r in rangos.values() if nombre in r.alias), None)


def clave_marcador(prueba: str, rangos: Optional[Dict[str, RangoCritico]] = None) -> str:
    """Clave con la que se agrupa un marcador: el código del rango crítico
    si la prueba está configurada (así "Hb" y "Hemoglobina" son la misma
    serie), o su nombre normalizado."""
    rango = buscar_rango(prueba, rangos if rangos is not None else cargar_rangos_criticos())
    return rango.codigo if rango else normalizar_texto(prueba)


def evaluar_critico(prueba: str, valor: str, unidad: Optional[str], rangos: Dict[str, RangoCritico]) -> Optional[str]:
    """Descripción del límite superado, o ``None`` si no es crítico o no se
    puede evaluar (prueba sin rango, valor no numérico, unidad distinta)."""
    rango = buscar_rango(prueba, rangos)
    numero = _a_numero(valor)
    if rango is None or numero is None or normalizar_unidad(unidad) not in rango.unidades:
        return None
    if rango.critico_bajo is not None and numero < rango.critico_bajo:
        return f"< {_fmt(rango.critico_bajo)} {unidad} (crítico bajo)"
    if rango.critico_alto is not None and numero > rango.critico_alto:
        return f"> {_fmt(rango.critico_alto)} {unidad} (crítico alto)"
    return None


# ---------------------------------------------------------------------------
# AC1: registro manual con doble validación
# ---------------------------------------------------------------------------


def nombres_coinciden(nombre_expediente: str, nombre_recibido: str) -> bool:
    """Todas las palabras del nombre recibido están en el del expediente,
    sin importar el orden, las tildes ni las mayúsculas ("Pérez^Juan" y
    "Juan Carlos Pérez" coinciden; "Gómez^Juan" no). Se exigen al menos dos
    palabras: un solo nombre no basta para confirmar la identidad."""
    recibidas = set(normalizar_texto(nombre_recibido.replace("^", " ")).split())
    del_expediente = set(normalizar_texto(nombre_expediente).split())
    return len(recibidas) >= 2 and recibidas <= del_expediente


def verificar_identidad(conn: sqlite3.Connection, paciente_id: int, identificacion: str, nombre: str) -> None:
    """Doble validación (riesgo de HC-02): identificación exacta y nombre."""
    paciente = obtener_paciente(conn, paciente_id)
    if paciente is None:
        raise ErrorLaboratorio(f"No existe ningún paciente con id={paciente_id}.")
    if (identificacion or "").strip() != paciente.identificacion:
        raise IdentidadNoCoincideError(
            f"La identificación '{identificacion}' no corresponde al paciente {paciente_id}. No se guardó el resultado."
        )
    if not nombres_coinciden(paciente.nombre, nombre or ""):
        raise IdentidadNoCoincideError(
            f"El nombre '{nombre}' no coincide con el del paciente con identificación {paciente.identificacion}. "
            "No se guardó el resultado."
        )


def registrar_resultado_laboratorio(
    conn: sqlite3.Connection,
    paciente_id: int,
    *,
    identificacion: str,
    nombre: str,
    prueba: str,
    valor: str,
    unidad: Optional[str],
    fecha: date,
    hora: Optional[time] = None,
    rango_referencia: Optional[str] = None,
    origen: str = ORIGEN_MANUAL,
    rangos: Optional[Dict[str, RangoCritico]] = None,
    ahora: Optional[datetime] = None,
) -> ResultadoRegistroLaboratorio:
    """Guarda un resultado (vía manual) y lo procesa (AC1-AC3) en una sola
    transacción. Lanza ``IdentidadNoCoincideError`` o ``ErrorLaboratorio``
    sin guardar nada si la identidad o los datos no son válidos."""
    verificar_identidad(conn, paciente_id, identificacion, nombre)
    prueba, valor = (prueba or "").strip(), (valor or "").strip()
    if not prueba or not valor:
        raise ErrorLaboratorio("La prueba y el valor del resultado son obligatorios.")
    if fecha > date.today():
        raise ErrorLaboratorio("La fecha del resultado no puede ser futura.")
    if rango_referencia and not re.fullmatch(r"\s*-?[\d.]+\s*-\s*-?[\d.]+\s*", rango_referencia):
        raise ErrorLaboratorio("El rango de referencia debe tener el formato 'bajo-alto' (p. ej. 3.5-5.1).")

    from historia_clinica.integracion_externa import _calcular_alterado

    fecha_hora = datetime.combine(fecha, hora).isoformat(timespec="minutes") if hora else None
    try:
        cursor = conn.execute(
            "INSERT INTO laboratorios (paciente_id, fecha, prueba, valor, unidad, rango_referencia, alterado) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (paciente_id, fecha.isoformat(), prueba, valor, (unidad or "").strip() or None, rango_referencia,
             int(_calcular_alterado(valor, rango_referencia))),
        )
        laboratorio_id = cursor.lastrowid
        registrar_recepcion(conn, laboratorio_id, paciente_id, fecha_hora, origen, ahora)
        procesado = procesar_resultados(conn, [laboratorio_id], rangos, ahora)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    alerta = next((a for a in alertas_de_paciente(conn, paciente_id) if a.laboratorio_id == laboratorio_id), None)
    conflictos = tuple(c for c in conflictos_de_paciente(conn, paciente_id, solo_pendientes=False) if c.id in procesado.conflictos)
    return ResultadoRegistroLaboratorio(laboratorio_id, alerta, conflictos)


def registrar_recepcion(
    conn: sqlite3.Connection,
    laboratorio_id: int,
    paciente_id: int,
    fecha_hora: Optional[str],
    origen: str,
    ahora: Optional[datetime] = None,
) -> None:
    """Deja constancia de cómo y cuándo llegó un resultado. No hace commit."""
    conn.execute(
        "INSERT OR IGNORE INTO recepcion_laboratorio (laboratorio_id, paciente_id, fecha_hora, origen, recibido_en) "
        "VALUES (?, ?, ?, ?, ?)",
        (laboratorio_id, paciente_id, fecha_hora, origen, ahora_iso(ahora)),
    )


# ---------------------------------------------------------------------------
# AC2 + AC3: procesamiento de resultados recién guardados
# ---------------------------------------------------------------------------


def procesar_resultados(
    conn: sqlite3.Connection,
    laboratorio_ids: Iterable[int],
    rangos: Optional[Dict[str, RangoCritico]] = None,
    ahora: Optional[datetime] = None,
) -> ResultadoProcesamiento:
    """Evalúa valores críticos y conflictos de los resultados indicados.

    No hace commit: corre dentro de la transacción de quien guardó los
    resultados, así que si algo falla no queda ni el resultado ni su
    alerta a medias.
    """
    rangos = rangos if rangos is not None else cargar_rangos_criticos()
    alertas: List[int] = []
    conflictos: List[int] = []
    for laboratorio_id in laboratorio_ids:
        fila = _fila_laboratorio(conn, laboratorio_id)
        if fila is None:
            continue

        limite = evaluar_critico(fila["prueba"], fila["valor"], fila["unidad"], rangos)
        if limite:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO alertas_laboratorio "
                "(paciente_id, laboratorio_id, prueba, valor, unidad, limite_superado, fecha) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (fila["paciente_id"], laboratorio_id, fila["prueba"], fila["valor"], fila["unidad"], limite, fila["fecha"]),
            )
            if cursor.rowcount:
                alertas.append(cursor.lastrowid)

        clave = clave_marcador(fila["prueba"], rangos)
        for otra in _filas_del_mismo_dia(conn, fila["paciente_id"], fila["fecha"], laboratorio_id):
            if clave_marcador(otra["prueba"], rangos) != clave:
                continue
            momento = _momento_comun(fila, otra)
            if momento is None or _mismo_valor(fila, otra):
                continue
            a, b = sorted((laboratorio_id, otra["id"]))
            cursor = conn.execute(
                "INSERT OR IGNORE INTO conflictos_laboratorio "
                "(paciente_id, prueba_normalizada, momento, laboratorio_a_id, laboratorio_b_id, fecha_deteccion) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (fila["paciente_id"], clave, momento, a, b, ahora_iso(ahora)),
            )
            if cursor.rowcount:
                conflictos.append(cursor.lastrowid)
    return ResultadoProcesamiento(tuple(alertas), tuple(conflictos))


def _fila_laboratorio(conn: sqlite3.Connection, laboratorio_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT l.*, r.fecha_hora FROM laboratorios l "
        "LEFT JOIN recepcion_laboratorio r ON r.laboratorio_id = l.id WHERE l.id = ?",
        (laboratorio_id,),
    ).fetchone()


def _filas_del_mismo_dia(conn: sqlite3.Connection, paciente_id: int, fecha: str, excluir: int) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT l.*, r.fecha_hora FROM laboratorios l "
        "LEFT JOIN recepcion_laboratorio r ON r.laboratorio_id = l.id "
        "WHERE l.paciente_id = ? AND l.fecha = ? AND l.id != ?",
        (paciente_id, fecha, excluir),
    ).fetchall()


def _momento_comun(a: sqlite3.Row, b: sqlite3.Row) -> Optional[str]:
    """El momento compartido, o ``None`` si son de momentos distintos. Con
    hora en ambos se compara la hora; si a alguno le falta, el día (no se
    puede descartar que sean del mismo momento)."""
    if a["fecha_hora"] and b["fecha_hora"]:
        return a["fecha_hora"] if a["fecha_hora"][:16] == b["fecha_hora"][:16] else None
    return a["fecha"]


def _mismo_valor(a: sqlite3.Row, b: sqlite3.Row) -> bool:
    if normalizar_unidad(a["unidad"]) != normalizar_unidad(b["unidad"]):
        return False
    numero_a, numero_b = _a_numero(a["valor"]), _a_numero(b["valor"])
    if numero_a is not None and numero_b is not None:
        return numero_a == numero_b
    return normalizar_texto(a["valor"]) == normalizar_texto(b["valor"])


# ---------------------------------------------------------------------------
# Revisión de alertas y conflictos
# ---------------------------------------------------------------------------


def alertas_de_paciente(conn: sqlite3.Connection, paciente_id: int, solo_activas: bool = False) -> List[AlertaLaboratorio]:
    sql = "SELECT * FROM alertas_laboratorio WHERE paciente_id = ?"
    if solo_activas:
        sql += " AND estado = 'activa'"
    filas = conn.execute(sql + " ORDER BY fecha DESC, id DESC", (paciente_id,)).fetchall()
    return [AlertaLaboratorio(**dict(f)) for f in filas]


def alertas_activas(conn: sqlite3.Connection, paciente_id: int) -> List[AlertaLaboratorio]:
    return alertas_de_paciente(conn, paciente_id, solo_activas=True)


def marcar_alerta_revisada(
    conn: sqlite3.Connection, paciente_id: int, alerta_id: int, revisada_por: str, ahora: Optional[datetime] = None
) -> AlertaLaboratorio:
    if not (revisada_por or "").strip():
        raise ErrorLaboratorio("Indique quién revisó la alerta.")
    fila = conn.execute(
        "SELECT * FROM alertas_laboratorio WHERE id = ? AND paciente_id = ?", (alerta_id, paciente_id)
    ).fetchone()
    if fila is None:
        raise ErrorLaboratorio(f"El paciente {paciente_id} no tiene la alerta {alerta_id}.")
    if fila["estado"] != "revisada":
        conn.execute(
            "UPDATE alertas_laboratorio SET estado = 'revisada', revisada_por = ?, fecha_revision = ? WHERE id = ?",
            (revisada_por.strip(), ahora_iso(ahora), alerta_id),
        )
        conn.commit()
    return AlertaLaboratorio(**dict(conn.execute("SELECT * FROM alertas_laboratorio WHERE id = ?", (alerta_id,)).fetchone()))


def conflictos_de_paciente(
    conn: sqlite3.Connection, paciente_id: int, solo_pendientes: bool = True
) -> List[ConflictoLaboratorio]:
    sql = (
        "SELECT c.*, a.valor AS valor_a, b.valor AS valor_b, a.unidad AS unidad_a, b.unidad AS unidad_b, "
        "a.prueba AS prueba FROM conflictos_laboratorio c "
        "JOIN laboratorios a ON a.id = c.laboratorio_a_id JOIN laboratorios b ON b.id = c.laboratorio_b_id "
        "WHERE c.paciente_id = ?"
    )
    if solo_pendientes:
        sql += " AND c.estado = 'pendiente'"
    filas = conn.execute(sql + " ORDER BY c.momento DESC, c.id DESC", (paciente_id,)).fetchall()
    return [ConflictoLaboratorio(**dict(f)) for f in filas]


def conflictos_pendientes(conn: sqlite3.Connection, paciente_id: int) -> List[ConflictoLaboratorio]:
    return conflictos_de_paciente(conn, paciente_id, solo_pendientes=True)


def resolver_conflicto(
    conn: sqlite3.Connection,
    paciente_id: int,
    conflicto_id: int,
    resolucion: str,
    resuelto_por: str,
    nota: Optional[str] = None,
    ahora: Optional[datetime] = None,
) -> ConflictoLaboratorio:
    """Registra la decisión del oncólogo. Ninguno de los dos resultados se
    borra ni se modifica: la resolución queda como constancia."""
    if resolucion not in RESOLUCIONES_CONFLICTO:
        raise ErrorLaboratorio(f"Resolución inválida: use una de {', '.join(RESOLUCIONES_CONFLICTO)}.")
    if not (resuelto_por or "").strip():
        raise ErrorLaboratorio("Indique quién resolvió el conflicto.")
    fila = conn.execute(
        "SELECT estado FROM conflictos_laboratorio WHERE id = ? AND paciente_id = ?", (conflicto_id, paciente_id)
    ).fetchone()
    if fila is None:
        raise ErrorLaboratorio(f"El paciente {paciente_id} no tiene el conflicto {conflicto_id}.")
    if fila["estado"] == "resuelto":
        raise ErrorLaboratorio(f"El conflicto {conflicto_id} ya fue resuelto.")
    conn.execute(
        "UPDATE conflictos_laboratorio SET estado = 'resuelto', resolucion = ?, resuelto_por = ?, "
        "fecha_resolucion = ?, nota = ? WHERE id = ?",
        (resolucion, resuelto_por.strip(), ahora_iso(ahora), (nota or "").strip() or None, conflicto_id),
    )
    conn.commit()
    return next(c for c in conflictos_de_paciente(conn, paciente_id, solo_pendientes=False) if c.id == conflicto_id)


# ---------------------------------------------------------------------------
# Tendencias por marcador
# ---------------------------------------------------------------------------


def _laboratorios_con_recepcion(conn: sqlite3.Connection, paciente_id: int) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT l.*, r.fecha_hora FROM laboratorios l "
        "LEFT JOIN recepcion_laboratorio r ON r.laboratorio_id = l.id WHERE l.paciente_id = ? "
        "ORDER BY l.fecha, COALESCE(r.fecha_hora, l.fecha), l.id",
        (paciente_id,),
    ).fetchall()


def marcadores_de_paciente(
    conn: sqlite3.Connection, paciente_id: int, rangos: Optional[Dict[str, RangoCritico]] = None
) -> List[ResumenMarcador]:
    """Un resumen por marcador (las variantes del nombre se agrupan), del
    medido más recientemente al más antiguo."""
    rangos = rangos if rangos is not None else cargar_rangos_criticos()
    grupos: Dict[str, List[sqlite3.Row]] = {}
    for fila in _laboratorios_con_recepcion(conn, paciente_id):
        grupos.setdefault(clave_marcador(fila["prueba"], rangos), []).append(fila)
    resumenes = []
    for clave, filas in grupos.items():
        ultima = filas[-1]
        rango = rangos.get(clave)
        resumenes.append(ResumenMarcador(
            clave=clave,
            prueba=rango.nombre if rango else ultima["prueba"],
            cantidad=len(filas),
            ultima_fecha=ultima["fecha"],
            ultimo_valor=ultima["valor"],
            unidad=ultima["unidad"],
        ))
    return sorted(resumenes, key=lambda r: (r.ultima_fecha, r.prueba), reverse=True)


def tendencia_marcador(
    conn: sqlite3.Connection, paciente_id: int, prueba: str, rangos: Optional[Dict[str, RangoCritico]] = None
) -> TendenciaMarcador:
    """Serie histórica de un marcador, de la más antigua a la más reciente.

    Si hay resultados en unidades distintas se devuelve una serie por
    unidad y una advertencia: no se convierten ni se mezclan.
    """
    rangos = rangos if rangos is not None else cargar_rangos_criticos()
    clave = clave_marcador(prueba, rangos)
    filas = [f for f in _laboratorios_con_recepcion(conn, paciente_id) if clave_marcador(f["prueba"], rangos) == clave]
    criticos = {f[0] for f in conn.execute("SELECT laboratorio_id FROM alertas_laboratorio WHERE paciente_id = ?", (paciente_id,))}
    en_conflicto = set()
    for a, b in conn.execute(
        "SELECT laboratorio_a_id, laboratorio_b_id FROM conflictos_laboratorio WHERE paciente_id = ? AND estado = 'pendiente'",
        (paciente_id,),
    ):
        en_conflicto.update((a, b))

    por_unidad: Dict[str, List[PuntoTendencia]] = {}
    unidades_originales: Dict[str, Optional[str]] = {}
    for f in filas:
        unidad = normalizar_unidad(f["unidad"])
        unidades_originales.setdefault(unidad, f["unidad"])
        por_unidad.setdefault(unidad, []).append(PuntoTendencia(
            laboratorio_id=f["id"],
            fecha=f["fecha"],
            fecha_hora=f["fecha_hora"],
            valor=f["valor"],
            valor_numerico=_a_numero(f["valor"]),
            unidad=f["unidad"],
            alterado=bool(f["alterado"]),
            critico=f["id"] in criticos,
            en_conflicto=f["id"] in en_conflicto,
        ))

    advertencias: List[str] = []
    if len(por_unidad) > 1:
        advertencias.append(
            "Hay resultados en unidades distintas ("
            + ", ".join(u or "sin unidad" for u in unidades_originales.values())
            + "); se muestran por separado y no se convierten."
        )
    if any(p.en_conflicto for puntos in por_unidad.values() for p in puntos):
        advertencias.append("Hay resultados en conflicto pendientes de revisión: la tendencia puede no ser fiable.")
    series = tuple(
        SerieTendencia(unidades_originales[u], tuple(puntos))
        for u, puntos in sorted(por_unidad.items(), key=lambda kv: -len(kv[1]))
    )
    rango = rangos.get(clave)
    nombre = rango.nombre if rango else (filas[-1]["prueba"] if filas else prueba.strip())
    return TendenciaMarcador(clave=clave, prueba=nombre, series=series, advertencias=tuple(advertencias))


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------


def _a_numero(valor: Optional[str]) -> Optional[float]:
    try:
        return float(str(valor).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def _fmt(numero: float) -> str:
    return f"{numero:g}"


__all__ = [
    "AlertaLaboratorio",
    "ConflictoLaboratorio",
    "ErrorConfiguracionLaboratorio",
    "ErrorLaboratorio",
    "IdentidadNoCoincideError",
    "PuntoTendencia",
    "RangoCritico",
    "ResultadoProcesamiento",
    "ResultadoRegistroLaboratorio",
    "ResumenMarcador",
    "SerieTendencia",
    "TendenciaMarcador",
    "alertas_activas",
    "alertas_de_paciente",
    "buscar_rango",
    "cargar_rangos_criticos",
    "clave_marcador",
    "conflictos_de_paciente",
    "conflictos_pendientes",
    "evaluar_critico",
    "marcadores_de_paciente",
    "marcar_alerta_revisada",
    "nombres_coinciden",
    "procesar_resultados",
    "registrar_recepcion",
    "registrar_resultado_laboratorio",
    "resolver_conflicto",
    "tendencia_marcador",
    "validar_rangos",
    "verificar_identidad",
]
