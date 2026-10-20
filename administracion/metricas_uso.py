"""ADM-02 — Métricas de uso del sistema para la dirección médica.

Como director médico, quiero un tablero de métricas de uso del sistema
(adopción, tiempo ahorrado, alertas generadas), para evaluar el impacto de
la herramienta.

Qué calcula (siempre para un periodo, comparado con el periodo anterior de
igual duración):

    - Adopción: de los usuarios clínicos activos (oncólogos y enfermería),
      cuántos usaron el sistema en el periodo (AUD-01), cuántos pacientes se
      atendieron con él y cuánto se usaron las funciones de IA.
    - Tiempo ahorrado: una ESTIMACIÓN, nunca una medición (ver abajo).
    - Alertas generadas: alertas críticas de laboratorio (HC-02), su revisión
      y los conflictos de resultados detectados; sincronizaciones externas.
    - Aceptación de las recomendaciones de IA (TX-04 y EST-02), con las
      salvaguardas de privacidad de abajo.

Decisiones de diseño:

    - Solo agregados institucionales. Ninguna estructura de salida contiene
      un identificador de persona, y ninguna función acepta filtrar por
      usuario: no existe un camino para pedir "las cifras de la Dra. X". Es
      la forma de cumplir la nota de UX de la historia ("no debe usarse como
      métrica de desempeño individual") por construcción, no por convención.
    - La tasa de aceptación se presenta como una distribución (aceptadas /
      modificadas / rechazadas), nunca como un número suelto, con una nota de
      interpretación (una tasa baja no es mala por sí misma; una muy alta
      tampoco lo es) y se SUPRIME si hay pocas decisiones o pocos médicos
      distintos detrás (``Parametros``): con 2 médicos, el "agregado" es casi
      una calificación personal. Al suprimirla no se muestra ninguna cifra.
    - El desglose de adopción por rol también se suprime en grupos pequeños.
    - "Sin datos" no es "cero": cada sección indica si su fuente existe. Una
      base no conectada o una tabla que falta se informa como no disponible,
      no como 0 (que se leería como "nadie usa el sistema").
    - El tiempo ahorrado es estimado: eventos reales del sistema por unos
      minutos supuestos (``coeficientes_tiempo.yaml``), siempre como rango, con
      los supuestos a la vista. Si falta alguna fuente se suma solo lo que se
      puede contar y se avisa que el total es una subestimación.
    - Ver el tablero no cuenta como uso del sistema: solo VER, EDITAR y
      EXPORTAR (acciones sobre expedientes) cuentan como adopción. Si no,
      mirar las métricas inflaría las métricas.
    - Quién puede: solo el rol ``director_medico`` (``Accion.VER_METRICAS_USO``,
      fail-closed). El actor se relee de la base en cada consulta. Cada
      consulta, y cada intento denegado, queda en AUD-01 (también sin los
      datos: solo el periodo y la vía). Si la traza no se puede escribir, no se
      entregan las métricas.
    - Solo lectura: las bases clínicas se abren en modo solo-lectura por
      defecto; el único dato que escribe este módulo es el evento de auditoría
      en la base de usuarios.
    - Fechas: por día (UTC). Los periodos son de días completos, ambos
      extremos incluidos.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import yaml

from administracion.usuarios import ErrorValidacion, PermisoDenegadoError
from auditoria.models import TipoAccion
from auditoria.registro_acceso import registrar_acceso
from seguridad.autorizacion import Accion, verificar_permiso
from seguridad.models import Rol, Usuario

RUTA_COEFICIENTES = Path(__file__).resolve().parent / "coeficientes_tiempo.yaml"

PERIODO_POR_DEFECTO_DIAS = 30
PERIODO_MAXIMO_DIAS = 400

#: Acciones de AUD-01 que significan "se usó el sistema con un expediente".
ACCIONES_USO_CLINICO = (TipoAccion.VER, TipoAccion.EDITAR, TipoAccion.EXPORTAR)
#: Roles cuya adopción se mide: quienes atienden con el copiloto.
ROLES_USUARIOS_CLINICOS = (Rol.ONCOLOGO, Rol.ENFERMERIA)

NOTA_ACEPTACION = (
    "La aceptación describe cuánto coincide el criterio clínico con lo que sugiere el sistema, "
    "en conjunto para toda la institución. Una tasa baja no es negativa en sí misma: puede reflejar "
    "criterio clínico independiente, casos que la guía no cubre o recomendaciones por mejorar; una tasa "
    "muy alta tampoco es buena por sí sola (puede indicar exceso de confianza en el sistema). "
    "No es una medida del desempeño de ningún médico, y por eso no existe ningún dato por persona."
)
NOTA_TIEMPO = (
    "Estimación, no medición: cuenta eventos reales registrados por el sistema multiplicados por minutos "
    "supuestos (rango). Los supuestos están a la vista y deben calibrarse con un estudio de tiempos propio."
)


class ErrorMetricas(Exception):
    """Base de los errores de esta historia (configuración, no de permisos)."""


# --------------------------------------------------------------------------
# Parámetros y coeficientes
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Parametros:
    """Umbrales de privacidad. Subirlos protege más; bajarlos por debajo de
    estos valores por defecto no se recomienda."""

    #: Mínimo de médicos distintos detrás de una tasa de aceptación para mostrarla.
    min_medicos_tasa: int = 5
    #: Mínimo de decisiones detrás de una tasa de aceptación para mostrarla.
    min_decisiones_tasa: int = 30
    #: Tamaño mínimo de un grupo (p. ej. un rol) para mostrar su desglose.
    min_grupo_desglose: int = 5


@dataclass(frozen=True)
class Coeficiente:
    clave: str
    descripcion: str
    minutos_min: float
    minutos_max: float
    origen: str


_CLAVES_COEFICIENTES = (
    "notas_ia_aprobadas",
    "sincronizaciones_exitosas",
    "decisiones_tratamiento",
    "estadificaciones_con_sugerencia",
)


def cargar_coeficientes(ruta: Optional[Path] = None) -> Dict[str, Coeficiente]:
    """Supuestos de tiempo: ``ruta``, ``COPILOTO_COEFICIENTES_TIEMPO`` o el archivo
    incluido. Valida todo: un supuesto absurdo (negativo, mínimo > máximo)
    produciría cifras engañosas, así que falla en voz alta."""
    ruta = Path(ruta or os.environ.get("COPILOTO_COEFICIENTES_TIEMPO") or RUTA_COEFICIENTES)
    try:
        crudo = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ErrorMetricas(f"No se pudieron leer los coeficientes de tiempo ({ruta}): {exc}") from exc
    datos = crudo.get("coeficientes") if isinstance(crudo, dict) else None
    if not isinstance(datos, dict):
        raise ErrorMetricas(f"{ruta}: falta la sección 'coeficientes'.")
    problemas: List[str] = []
    resultado: Dict[str, Coeficiente] = {}
    for clave in _CLAVES_COEFICIENTES:
        item = datos.get(clave)
        if not isinstance(item, dict):
            problemas.append(f"falta el coeficiente '{clave}'")
            continue
        try:
            minimo, maximo = float(item["minutos_min"]), float(item["minutos_max"])
        except (KeyError, TypeError, ValueError):
            problemas.append(f"'{clave}' necesita minutos_min y minutos_max numéricos")
            continue
        if minimo < 0 or maximo < minimo:
            problemas.append(f"'{clave}': se requiere 0 <= minutos_min <= minutos_max (hay {minimo} y {maximo})")
            continue
        resultado[clave] = Coeficiente(
            clave, str(item.get("descripcion") or clave), minimo, maximo, str(item.get("origen") or "sin origen indicado")
        )
    desconocidos = sorted(set(datos) - set(_CLAVES_COEFICIENTES))
    if desconocidos:
        problemas.append("coeficientes desconocidos: " + ", ".join(desconocidos))
    if problemas:
        raise ErrorMetricas(f"{ruta}: " + "; ".join(problemas) + ".")
    return resultado


# --------------------------------------------------------------------------
# Resultado (todo agregado: ningún campo identifica a una persona)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Periodo:
    desde: str
    hasta: str
    dias: int
    desde_anterior: str
    hasta_anterior: str


@dataclass(frozen=True)
class DesgloseRol:
    rol: str
    #: None cuando el grupo es demasiado pequeño para mostrarlo.
    usuarios_activos: Optional[int]
    usuarios_elegibles: Optional[int]
    tasa_adopcion: Optional[float]
    suprimido: bool


@dataclass(frozen=True)
class UsoFuncion:
    clave: str
    etiqueta: str
    #: None = la fuente de este dato no está disponible (no es cero).
    total: Optional[int]
    total_periodo_anterior: Optional[int]


@dataclass(frozen=True)
class Adopcion:
    disponible: bool
    motivo: Optional[str]
    usuarios_elegibles: Optional[int]
    usuarios_activos: Optional[int]
    tasa_adopcion: Optional[float]
    tasa_adopcion_periodo_anterior: Optional[float]
    pacientes_atendidos: Optional[int]
    acciones_por_tipo: Tuple[Tuple[str, int], ...]
    por_rol: Tuple[DesgloseRol, ...]
    uso_funciones_ia: Tuple[UsoFuncion, ...]
    #: Eventos de uso cuyo usuario no es un clínico activo conocido (cuentas
    #: dadas de baja, cuentas de sistema, ids sin cuenta): no cuentan como adopción.
    eventos_no_atribuibles: Optional[int]


@dataclass(frozen=True)
class ComponenteTiempo:
    clave: str
    descripcion: str
    disponible: bool
    #: Eventos contados en el periodo; None si la fuente no está disponible.
    eventos: Optional[int]
    minutos_min_por_evento: float
    minutos_max_por_evento: float
    horas_min: Optional[float]
    horas_max: Optional[float]
    origen_supuesto: str


@dataclass(frozen=True)
class TiempoAhorrado:
    disponible: bool
    motivo: Optional[str]
    #: Siempre True: es una estimación, y la interfaz debe decirlo.
    es_estimacion: bool
    horas_min: Optional[float]
    horas_max: Optional[float]
    horas_min_periodo_anterior: Optional[float]
    horas_max_periodo_anterior: Optional[float]
    componentes: Tuple[ComponenteTiempo, ...]
    #: True si faltan fuentes: el total real sería mayor o igual al mostrado.
    subestimado: bool
    nota: str


@dataclass(frozen=True)
class Alertas:
    disponible: bool
    motivo: Optional[str]
    generadas: Optional[int]
    generadas_periodo_anterior: Optional[int]
    por_severidad: Tuple[Tuple[str, int], ...]
    revisadas: Optional[int]
    pendientes_actuales: Optional[int]
    conflictos_detectados: Optional[int]
    conflictos_pendientes_actuales: Optional[int]
    sincronizaciones_exitosas: Optional[int]
    sincronizaciones_fallidas: Optional[int]


@dataclass(frozen=True)
class AceptacionDominio:
    dominio: str
    etiqueta: str
    disponible: bool
    suprimida: bool
    motivo: Optional[str]
    #: Solo con ``suprimida`` en False.
    total: Optional[int]
    categorias: Tuple[Tuple[str, str, int], ...]
    tasa_aceptacion: Optional[float]


@dataclass(frozen=True)
class AceptacionIA:
    disponible: bool
    motivo: Optional[str]
    dominios: Tuple[AceptacionDominio, ...]
    nota_interpretacion: str
    #: Dominios con recomendación de IA pero sin comparación contra la decisión.
    dominios_sin_comparacion: Tuple[str, ...]


@dataclass(frozen=True)
class SemanaUso:
    inicio: str
    fin: str
    #: Semana de menos de 7 días (el final del periodo): no es comparable con las demás.
    parcial: bool
    usuarios_activos: Optional[int]
    alertas_generadas: Optional[int]
    horas_ahorradas_min: Optional[float]
    horas_ahorradas_max: Optional[float]


@dataclass(frozen=True)
class MetricasUso:
    generado_en: str
    periodo: Periodo
    adopcion: Adopcion
    tiempo_ahorrado: TiempoAhorrado
    alertas: Alertas
    aceptacion_ia: AceptacionIA
    semanas: Tuple[SemanaUso, ...]
    #: Fuentes de datos que no se pudieron leer (nombres de tablas).
    fuentes_no_disponibles: Tuple[str, ...]

    def a_dict(self) -> Dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------
# Fuentes
# --------------------------------------------------------------------------


class FuentesMetricas:
    """Las conexiones de las que salen las métricas.

    ``usuarios`` (obligatoria) es la base de SEC-01: de ahí salen las cuentas y
    los roles, y ahí se audita. ``otras`` son las demás bases del sistema
    (expediente, pacientes...): cada métrica suma las tablas que encuentre en
    las conexiones dadas, así que no importa en cuál base vive cada cosa. Una
    base pasada dos veces cuenta una sola vez.
    """

    def __init__(self, usuarios: sqlite3.Connection, otras: Iterable[sqlite3.Connection] = ()):
        self.usuarios = usuarios
        vistas: set = set()
        self.conexiones: List[sqlite3.Connection] = []
        for conn in (usuarios, *otras):
            clave = _identidad(conn)
            if clave is not None:
                if clave in vistas:
                    continue
                vistas.add(clave)
            self.conexiones.append(conn)

    def con_tabla(self, tabla: str) -> List[sqlite3.Connection]:
        return [c for c in self.conexiones if _tiene_tabla(c, tabla)]


def _identidad(conn: sqlite3.Connection) -> Optional[str]:
    """Archivo de la base (None para bases en memoria, que son siempre distintas)."""
    try:
        for fila in conn.execute("PRAGMA database_list").fetchall():
            if fila[1] == "main" and fila[2]:
                return os.path.realpath(fila[2])
    except sqlite3.Error:
        pass
    return None


def _tiene_tabla(conn: sqlite3.Connection, tabla: str) -> bool:
    try:
        return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (tabla,)).fetchone() is not None
    except sqlite3.Error:
        return False


def abrir_solo_lectura(ruta: Path) -> sqlite3.Connection:
    """Conexión de solo lectura: las métricas nunca pueden alterar una base clínica."""
    conn = sqlite3.connect(f"file:{Path(ruta).as_posix()}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def rutas_por_defecto() -> List[Path]:
    """Bases del sistema que existen: pacientes (donde la API registra accesos),
    expediente y las que se agreguen con ``COPILOTO_METRICAS_DBS`` (rutas
    separadas por ``os.pathsep``)."""
    from historia_clinica.db import ruta_expediente
    from patients.db import RUTA_DB

    candidatas = [Path(RUTA_DB), Path(ruta_expediente())]
    extra = os.environ.get("COPILOTO_METRICAS_DBS", "")
    candidatas += [Path(p) for p in extra.split(os.pathsep) if p.strip()]
    return [p for p in candidatas if p.is_file()]


# --------------------------------------------------------------------------
# Lectura de datos
# --------------------------------------------------------------------------


def _dia(texto: Optional[str]) -> str:
    return (texto or "")[:10]


def _contar_por_dia(
    fuentes: FuentesMetricas, tabla: str, columna_fecha: str, desde: date, hasta: date, donde: str = "", params: Sequence[Any] = ()
) -> Optional[Counter]:
    """Eventos por día (``AAAA-MM-DD``) en ``[desde, hasta]``, sumando todas las
    bases que tengan la tabla. None si ninguna la tiene."""
    conexiones = fuentes.con_tabla(tabla)
    if not conexiones:
        return None
    total: Counter = Counter()
    filtro = f" AND ({donde})" if donde else ""
    sql = (
        f"SELECT substr({columna_fecha}, 1, 10) AS d, COUNT(*) AS n FROM {tabla} "
        f"WHERE substr({columna_fecha}, 1, 10) BETWEEN ? AND ?{filtro} GROUP BY d"
    )
    for conn in conexiones:
        try:
            for fila in conn.execute(sql, (desde.isoformat(), hasta.isoformat(), *params)).fetchall():
                total[fila[0]] += fila[1]
        except sqlite3.Error:
            return None
    return total


def _suma(contador: Optional[Counter], desde: date, hasta: date) -> Optional[int]:
    if contador is None:
        return None
    return sum(n for d, n in contador.items() if desde.isoformat() <= d <= hasta.isoformat())


def _scalar(fuentes: FuentesMetricas, tabla: str, sql: str, params: Sequence[Any] = ()) -> Optional[int]:
    conexiones = fuentes.con_tabla(tabla)
    if not conexiones:
        return None
    total = 0
    for conn in conexiones:
        try:
            total += conn.execute(sql, params).fetchone()[0]
        except sqlite3.Error:
            return None
    return total


def _leer_uso(fuentes: FuentesMetricas, desde: date, hasta: date) -> Optional[List[Tuple[int, Optional[int], str, str]]]:
    """Filas (usuario_id, paciente_id, accion, día) de uso clínico, sin repetir."""
    conexiones = fuentes.con_tabla("eventos_acceso")
    if not conexiones:
        return None
    marcas = ",".join("?" for _ in ACCIONES_USO_CLINICO)
    sql = (
        f"SELECT usuario_id, paciente_id, accion, substr(fecha, 1, 10) AS d, COUNT(*) AS n FROM eventos_acceso "
        f"WHERE accion IN ({marcas}) AND substr(fecha, 1, 10) BETWEEN ? AND ? "
        f"GROUP BY usuario_id, paciente_id, accion, d"
    )
    filas: List[Tuple[int, Optional[int], str, str, int]] = []
    for conn in conexiones:
        try:
            cursor = conn.execute(sql, (*[a.value for a in ACCIONES_USO_CLINICO], desde.isoformat(), hasta.isoformat()))
            filas += [(f[0], f[1], f[2], f[3], f[4]) for f in cursor.fetchall()]
        except sqlite3.Error:
            return None
    return filas  # type: ignore[return-value]


def _clinicos_activos(conn: sqlite3.Connection) -> Dict[int, Rol]:
    """Cuentas activas con rol clínico: id → rol (solo ids; nunca sale de este módulo)."""
    marcas = ",".join("?" for _ in ROLES_USUARIOS_CLINICOS)
    filas = conn.execute(
        f"SELECT id, rol FROM usuarios WHERE activo = 1 AND rol IN ({marcas})", [r.value for r in ROLES_USUARIOS_CLINICOS]
    ).fetchall()
    return {f[0]: Rol(f[1]) for f in filas}


def _tasa(parte: Optional[int], todo: Optional[int]) -> Optional[float]:
    if parte is None or not todo:
        return None
    return round(parte / todo, 4)


# --------------------------------------------------------------------------
# Cálculo de cada sección
# --------------------------------------------------------------------------


def _adopcion(fuentes: FuentesMetricas, hoy_p: Tuple[date, date], ant_p: Tuple[date, date],
              params: Parametros, conteos_ia: Dict[str, Optional[Counter]]) -> Tuple[Adopcion, Dict[Tuple[int, str], bool]]:
    desde, hasta = hoy_p
    desde_a, hasta_a = ant_p
    ia = _uso_funciones_ia(conteos_ia, hoy_p, ant_p)
    if not _tiene_tabla(fuentes.usuarios, "usuarios"):
        return Adopcion(False, "No hay base de usuarios.", None, None, None, None, None, (), (), ia, None), {}
    filas = _leer_uso(fuentes, desde_a, hasta)
    if filas is None:
        return Adopcion(False, "No hay registro de accesos disponible.", None, None, None, None, None, (), (), ia, None), {}

    clinicos = _clinicos_activos(fuentes.usuarios)
    elegibles = len(clinicos)
    ahora_s, ant_s = (desde.isoformat(), hasta.isoformat()), (desde_a.isoformat(), hasta_a.isoformat())

    activos: set = set()
    activos_ant: set = set()
    pacientes: set = set()
    por_tipo: Counter = Counter()
    no_atribuibles = 0
    activos_por_dia: Dict[Tuple[int, str], bool] = {}
    for usuario_id, paciente_id, accion, dia, n in filas:
        if usuario_id not in clinicos:
            if ahora_s[0] <= dia <= ahora_s[1]:
                no_atribuibles += n
            continue
        activos_por_dia[(usuario_id, dia)] = True
        if ahora_s[0] <= dia <= ahora_s[1]:
            activos.add(usuario_id)
            por_tipo[accion] += n
            if paciente_id is not None:
                pacientes.add(paciente_id)
        elif ant_s[0] <= dia <= ant_s[1]:
            activos_ant.add(usuario_id)

    por_rol = []
    for rol in ROLES_USUARIOS_CLINICOS:
        ids_rol = {i for i, r in clinicos.items() if r == rol}
        if len(ids_rol) < params.min_grupo_desglose:
            por_rol.append(DesgloseRol(rol.value, None, None, None, True))
        else:
            n_act = len(activos & ids_rol)
            por_rol.append(DesgloseRol(rol.value, n_act, len(ids_rol), _tasa(n_act, len(ids_rol)), False))

    adopcion = Adopcion(
        disponible=True, motivo=None,
        usuarios_elegibles=elegibles, usuarios_activos=len(activos),
        tasa_adopcion=_tasa(len(activos), elegibles),
        tasa_adopcion_periodo_anterior=_tasa(len(activos_ant), elegibles),
        pacientes_atendidos=len(pacientes),
        acciones_por_tipo=tuple((a.value, por_tipo.get(a.value, 0)) for a in ACCIONES_USO_CLINICO),
        por_rol=tuple(por_rol), uso_funciones_ia=ia, eventos_no_atribuibles=no_atribuibles,
    )
    return adopcion, activos_por_dia


def _uso_funciones_ia(conteos: Dict[str, Optional[Counter]], hoy_p, ant_p) -> Tuple[UsoFuncion, ...]:
    etiquetas = {
        "notas_ia_aprobadas": "Notas con borrador de IA aprobadas",
        "decisiones_tratamiento": "Decisiones de tratamiento registradas",
        "estadificaciones_con_sugerencia": "Estadificaciones confirmadas con sugerencia",
        "juicios_diagnosticos": "Juicios diagnósticos registrados",
    }
    salida = []
    for clave, etiqueta in etiquetas.items():
        contador = conteos.get(clave)
        salida.append(UsoFuncion(clave, etiqueta, _suma(contador, *hoy_p), _suma(contador, *ant_p)))
    return tuple(salida)


def _tiempo(conteos: Dict[str, Optional[Counter]], coef: Dict[str, Coeficiente], hoy_p, ant_p,
            semanas: List[Tuple[date, date]]) -> Tuple[TiempoAhorrado, List[Tuple[Optional[float], Optional[float]]]]:
    componentes = []
    total_min = total_max = ant_min = ant_max = 0.0
    hay_alguno = False
    faltan = False
    for clave in _CLAVES_COEFICIENTES:
        c = coef[clave]
        contador = conteos.get(clave)
        n = _suma(contador, *hoy_p)
        if n is None:
            faltan = True
            componentes.append(ComponenteTiempo(clave, c.descripcion, False, None, c.minutos_min, c.minutos_max, None, None, c.origen))
            continue
        hay_alguno = True
        hmin, hmax = n * c.minutos_min / 60, n * c.minutos_max / 60
        total_min += hmin
        total_max += hmax
        na = _suma(contador, *ant_p) or 0
        ant_min += na * c.minutos_min / 60
        ant_max += na * c.minutos_max / 60
        componentes.append(ComponenteTiempo(clave, c.descripcion, True, n, c.minutos_min, c.minutos_max,
                                            round(hmin, 1), round(hmax, 1), c.origen))
    por_semana: List[Tuple[Optional[float], Optional[float]]] = []
    for inicio, fin in semanas:
        smin = smax = 0.0
        for clave in _CLAVES_COEFICIENTES:
            contador = conteos.get(clave)
            n = _suma(contador, inicio, fin)
            if n is not None:
                smin += n * coef[clave].minutos_min / 60
                smax += n * coef[clave].minutos_max / 60
        por_semana.append((round(smin, 1), round(smax, 1)) if hay_alguno else (None, None))
    if not hay_alguno:
        return TiempoAhorrado(False, "Ninguna de las fuentes de la estimación está disponible.", True, None, None, None, None,
                              tuple(componentes), False, NOTA_TIEMPO), por_semana
    return TiempoAhorrado(
        True, None, True, round(total_min, 1), round(total_max, 1), round(ant_min, 1), round(ant_max, 1),
        tuple(componentes), faltan, NOTA_TIEMPO,
    ), por_semana


def _alertas(fuentes: FuentesMetricas, hoy_p, ant_p) -> Tuple[Alertas, Optional[Counter]]:
    desde, hasta = hoy_p
    contador = _contar_por_dia(fuentes, "alertas_laboratorio", "fecha", ant_p[0], hasta)
    conf = _contar_por_dia(fuentes, "conflictos_laboratorio", "fecha_deteccion", desde, hasta)
    exitosas = _contar_por_dia(fuentes, "sincronizaciones_externas", "fecha", desde, hasta, "estado = ?", ("exitosa",))
    fallidas = _contar_por_dia(fuentes, "sincronizaciones_externas", "fecha", desde, hasta, "estado = ?", ("fallida",))
    if contador is None and conf is None and exitosas is None:
        return Alertas(False, "Ninguna fuente de alertas está disponible.", None, None, (), None, None, None, None, None, None), None

    severidades: Counter = Counter()
    revisadas: Optional[int] = None
    pendientes: Optional[int] = None
    if contador is not None:
        for conn in fuentes.con_tabla("alertas_laboratorio"):
            try:
                for fila in conn.execute(
                    "SELECT severidad, COUNT(*) FROM alertas_laboratorio WHERE substr(fecha, 1, 10) BETWEEN ? AND ? GROUP BY severidad",
                    (desde.isoformat(), hasta.isoformat()),
                ).fetchall():
                    severidades[fila[0]] += fila[1]
            except sqlite3.Error:
                pass  # esquema antiguo sin severidad: el total sigue siendo válido
        revisadas = _scalar(
            fuentes, "alertas_laboratorio",
            "SELECT COUNT(*) FROM alertas_laboratorio WHERE estado = 'revisada' AND substr(fecha, 1, 10) BETWEEN ? AND ?",
            (desde.isoformat(), hasta.isoformat()),
        )
        pendientes = _scalar(fuentes, "alertas_laboratorio", "SELECT COUNT(*) FROM alertas_laboratorio WHERE estado = 'activa'")
    return Alertas(
        disponible=True, motivo=None,
        generadas=_suma(contador, desde, hasta), generadas_periodo_anterior=_suma(contador, *ant_p),
        por_severidad=tuple(sorted(severidades.items())),
        revisadas=revisadas, pendientes_actuales=pendientes,
        conflictos_detectados=_suma(conf, desde, hasta),
        conflictos_pendientes_actuales=_scalar(fuentes, "conflictos_laboratorio",
                                               "SELECT COUNT(*) FROM conflictos_laboratorio WHERE estado = 'pendiente'"),
        sincronizaciones_exitosas=_suma(exitosas, desde, hasta),
        sincronizaciones_fallidas=_suma(fallidas, desde, hasta),
    ), contador


def _suprimir(dominio: str, etiqueta: str, motivo: str) -> AceptacionDominio:
    return AceptacionDominio(dominio, etiqueta, True, True, motivo, None, (), None)


def _aceptacion(fuentes: FuentesMetricas, hoy_p, params: Parametros) -> AceptacionIA:
    desde, hasta = hoy_p
    d0, d1 = desde.isoformat(), hasta.isoformat()
    dominios: List[AceptacionDominio] = []
    motivo_supresion = (
        "Hay pocas decisiones o pocos médicos en el periodo: mostrar la tasa permitiría atribuirla a personas concretas. "
        "Amplía el periodo para verla."
    )

    # TX-04: aceptada / modificada / rechazada.
    etiqueta_tx = "Tratamiento"
    if not fuentes.con_tabla("decisiones_tratamiento"):
        dominios.append(AceptacionDominio("TX", etiqueta_tx, False, False, "No hay registro de decisiones de tratamiento.", None, (), None))
    else:
        cuentas: Counter = Counter()
        medicos: set = set()
        for conn in fuentes.con_tabla("decisiones_tratamiento"):
            for f in conn.execute(
                "SELECT oncologo_id, tipo_decision, regimen_sugerido_id, regimen_final_id FROM decisiones_tratamiento "
                "WHERE substr(fecha, 1, 10) BETWEEN ? AND ?", (d0, d1),
            ).fetchall():
                medicos.add(f[0])
                if f[1] == "accept" or (f[1] == "modify" and f[3] == f[2]):
                    cuentas["aceptadas"] += 1
                elif f[1] == "modify":
                    cuentas["modificadas"] += 1
                elif f[1] == "reject":
                    cuentas["rechazadas"] += 1
        total = sum(cuentas.values())
        if total < params.min_decisiones_tasa or len(medicos) < params.min_medicos_tasa:
            dominios.append(_suprimir("TX", etiqueta_tx, motivo_supresion if total else "Sin decisiones en el periodo."))
        else:
            dominios.append(AceptacionDominio("TX", etiqueta_tx, True, False, None, total, (
                ("aceptadas", "Aceptadas tal cual", cuentas["aceptadas"]),
                ("modificadas", "Aceptadas con cambios", cuentas["modificadas"]),
                ("rechazadas", "No aceptadas", cuentas["rechazadas"]),
            ), _tasa(cuentas["aceptadas"], total)))

    # EST-02: coincide / difiere de la sugerencia (solo si había sugerencia).
    etiqueta_est = "Estadificación"
    if not fuentes.con_tabla("confirmaciones_estadificacion"):
        dominios.append(AceptacionDominio("EST", etiqueta_est, False, False, "No hay registro de confirmaciones de estadificación.", None, (), None))
    else:
        cuentas = Counter()
        medicos = set()
        for conn in fuentes.con_tabla("confirmaciones_estadificacion"):
            for f in conn.execute(
                "SELECT autor, difiere_de_sugerencia FROM confirmaciones_estadificacion "
                "WHERE sugerencia_disponible = 1 AND substr(registrado_en, 1, 10) BETWEEN ? AND ?", (d0, d1),
            ).fetchall():
                medicos.add(f[0])
                cuentas["difieren" if f[1] else "coinciden"] += 1
        total = sum(cuentas.values())
        if total < params.min_decisiones_tasa or len(medicos) < params.min_medicos_tasa:
            dominios.append(_suprimir("EST", etiqueta_est, motivo_supresion if total else "Sin confirmaciones con sugerencia en el periodo."))
        else:
            dominios.append(AceptacionDominio("EST", etiqueta_est, True, False, None, total, (
                ("coinciden", "Estadio confirmado igual a la sugerencia", cuentas["coinciden"]),
                ("difieren", "Estadio confirmado distinto", cuentas["difieren"]),
            ), _tasa(cuentas["coinciden"], total)))

    disponible = any(d.disponible for d in dominios)
    return AceptacionIA(
        disponible, None if disponible else "No hay registros de decisiones sobre recomendaciones de IA.",
        tuple(dominios), NOTA_ACEPTACION,
        dominios_sin_comparacion=("Diagnóstico: el sistema no compara el juicio del médico con su priorización",),
    )


# --------------------------------------------------------------------------
# Acceso y punto de entrada
# --------------------------------------------------------------------------


def _json(datos: Dict[str, Any]) -> str:
    return json.dumps(datos, ensure_ascii=False, sort_keys=True)


def _auditar(conn: sqlite3.Connection, actor_id: int, resultado: str, ahora: datetime, **datos: Any) -> None:
    detalle = {"operacion": "consultar_metricas", "resultado": resultado, **datos}
    registrar_acceso(conn, actor_id, TipoAccion.CONSULTAR_METRICAS, detalle=_json(detalle), ahora=ahora)


def _verificar_actor(conn: sqlite3.Connection, actor: Usuario, ahora: datetime, **contexto: Any) -> Usuario:
    """El actor vigente (releído de la base) o ``PermisoDenegadoError``; el intento
    denegado también queda auditado."""
    fila = conn.execute("SELECT id, nombre_usuario, rol, activo FROM usuarios WHERE id = ?", (actor.id,)).fetchone()
    vigente = None
    if fila is not None:
        try:
            vigente = Usuario(fila[0], fila[1], Rol(fila[2]), bool(fila[3]))
        except ValueError:
            vigente = None
    veredicto = verificar_permiso(vigente, Accion.VER_METRICAS_USO) if vigente else None
    if veredicto is None or not veredicto.permitido:
        motivo = veredicto.motivo_rechazo if veredicto else "El usuario no existe."
        _auditar(conn, actor.id, "denegado", ahora, motivo=motivo, **contexto)
        raise PermisoDenegadoError(motivo)
    return vigente


def resolver_periodo(desde: Optional[date], hasta: Optional[date], ahora: datetime) -> Tuple[date, date]:
    """Periodo pedido (por defecto, los últimos 30 días hasta hoy, UTC). ``ErrorValidacion`` si no es válido."""
    hoy = ahora.astimezone(timezone.utc).date()
    hasta = hasta or hoy
    desde = desde or (hasta - timedelta(days=PERIODO_POR_DEFECTO_DIAS - 1))
    errores: List[Tuple[str, str]] = []
    if desde > hasta:
        errores.append(("periodo", "'desde' no puede ser posterior a 'hasta'."))
    elif (hasta - desde).days + 1 > PERIODO_MAXIMO_DIAS:
        errores.append(("periodo", f"El periodo no puede superar {PERIODO_MAXIMO_DIAS} días."))
    if hasta > hoy:
        errores.append(("hasta", "'hasta' no puede ser una fecha futura."))
    if errores:
        raise ErrorValidacion(errores)
    return desde, hasta


def consultar_metricas(
    fuentes: FuentesMetricas,
    actor: Usuario,
    *,
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    via: str = "api",
    ahora: Optional[datetime] = None,
    parametros: Optional[Parametros] = None,
    coeficientes: Optional[Dict[str, Coeficiente]] = None,
) -> MetricasUso:
    """Las métricas de uso del periodo, para un actor con permiso (``director_medico``).

    Lanza ``PermisoDenegadoError`` (auditado) si el actor no puede, y
    ``ErrorValidacion`` si el periodo no es válido. La consulta queda en AUD-01."""
    ahora = ahora or datetime.now(timezone.utc)
    parametros = parametros or Parametros()
    _verificar_actor(fuentes.usuarios, actor, ahora, via=via)
    desde, hasta = resolver_periodo(desde, hasta, ahora)
    coef = coeficientes or cargar_coeficientes()

    dias = (hasta - desde).days + 1
    hasta_ant = desde - timedelta(days=1)
    desde_ant = hasta_ant - timedelta(days=dias - 1)
    hoy_p, ant_p = (desde, hasta), (desde_ant, hasta_ant)
    periodo = Periodo(desde.isoformat(), hasta.isoformat(), dias, desde_ant.isoformat(), hasta_ant.isoformat())

    # Eventos por día de cada función, en el periodo y el anterior (una consulta por fuente).
    conteos: Dict[str, Optional[Counter]] = {
        "notas_ia_aprobadas": _contar_por_dia(fuentes, "revision_notas", "aprobado_en", desde_ant, hasta, "estado = ?", ("APPROVED",)),
        "sincronizaciones_exitosas": _contar_por_dia(fuentes, "sincronizaciones_externas", "fecha", desde_ant, hasta, "estado = ?", ("exitosa",)),
        "decisiones_tratamiento": _contar_por_dia(fuentes, "decisiones_tratamiento", "fecha", desde_ant, hasta),
        "estadificaciones_con_sugerencia": _contar_por_dia(
            fuentes, "confirmaciones_estadificacion", "registrado_en", desde_ant, hasta, "sugerencia_disponible = 1"),
        "juicios_diagnosticos": _contar_por_dia(fuentes, "juicios_clinicos_dx", "registrado_en", desde_ant, hasta),
    }

    semanas_rangos: List[Tuple[date, date]] = []
    inicio = desde
    while inicio <= hasta:
        semanas_rangos.append((inicio, min(inicio + timedelta(days=6), hasta)))
        inicio += timedelta(days=7)

    adopcion, activos_por_dia = _adopcion(fuentes, hoy_p, ant_p, parametros, conteos)
    tiempo, tiempo_semanal = _tiempo(conteos, coef, hoy_p, ant_p, semanas_rangos)
    alertas, alertas_dia = _alertas(fuentes, hoy_p, ant_p)
    aceptacion = _aceptacion(fuentes, hoy_p, parametros)

    semanas = []
    for (ini, fin), (hmin, hmax) in zip(semanas_rangos, tiempo_semanal):
        activos_sem: Optional[int] = None
        if adopcion.disponible:
            activos_sem = len({u for (u, d) in activos_por_dia if ini.isoformat() <= d <= fin.isoformat()})
        semanas.append(SemanaUso(
            ini.isoformat(), fin.isoformat(), (fin - ini).days + 1 < 7, activos_sem, _suma(alertas_dia, ini, fin), hmin, hmax,
        ))

    no_disponibles = tuple(
        t for t in ("eventos_acceso", "usuarios", "alertas_laboratorio", "conflictos_laboratorio", "sincronizaciones_externas",
                    "revision_notas", "decisiones_tratamiento", "confirmaciones_estadificacion", "juicios_clinicos_dx")
        if not fuentes.con_tabla(t)
    )
    metricas = MetricasUso(ahora.isoformat(), periodo, adopcion, tiempo, alertas, aceptacion, tuple(semanas), no_disponibles)

    # Sin traza no hay datos: si la auditoría falla, no se entrega nada.
    try:
        _auditar(fuentes.usuarios, actor.id, "ok", ahora, desde=periodo.desde, hasta=periodo.hasta, via=via)
    except Exception:
        fuentes.usuarios.rollback()
        raise
    return metricas
