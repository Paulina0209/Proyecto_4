"""HC-04 — Integración de resultados de biopsias y biomarcadores.

Como oncólogo, quiero integrar resultados de biopsias y biomarcadores, para
contar con la información molecular relevante al decidir tratamiento.

Criterios de aceptación:

    - AC1: una biopsia registrada queda vinculada a su episodio diagnóstico
      (``episodios_diagnosticos``). Si el paciente tiene un solo episodio se
      vincula a ese; con cero o con varios hay que indicarlo (fail-closed:
      el sistema no adivina a qué diagnóstico pertenece una biopsia).
    - AC2: un biomarcador relevante para una terapia dirigida disponible se
      destaca como información clave (``biomarcadores_clave``) y su
      variable de tratamiento (``egfr_status``, ``her2_status``,
      ``pdl1_tps``...) queda en ``datos_clinicos_estructurados``, que es lo
      que lee TX-01.

Riesgo de la historia: un biomarcador mal registrado (positivo/negativo
invertido) puede llevar a un tratamiento equivocado. Por eso:

    - Todo resultado se valida contra ``catalogo_biomarcadores.yaml``:
      estados, métodos y rangos permitidos; nada de texto libre.
    - Las reglas de coherencia se verifican (HER2 IHC 3+ no puede ser
      "negativo"; IHC 2+ sin ISH es "equívoco"; un receptor con >= 1 % de
      células teñidas es positivo).
    - Doble ingreso: el resultado clave se escribe dos veces (``estado`` y
      ``confirmacion``) y deben coincidir.
    - Lo que viene de una fuente externa (cBioPortal) nunca escribe una
      variable de tratamiento por sí solo: se destaca como "pendiente de
      confirmación" y solo al confirmarlo el oncólogo pasa a TX-01.

La fila de ``biomarcadores`` conserva un texto legible (lo que leen HC-05,
DX e IA sin cambios); el dato validado vive en ``detalle_biomarcador``.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import yaml

from historia_clinica.db import ahora_iso, normalizar_texto
from expediente.repository import obtener_paciente

RUTA_CATALOGO_POR_DEFECTO = Path(__file__).resolve().parent / "catalogo_biomarcadores.yaml"
RUTA_GUIAS_POR_DEFECTO = Path(__file__).resolve().parent.parent / "guidelines"

ORIGEN_MANUAL = "manual"

ACCIONABLE_CONFIRMADO = "accionable_confirmado"
PENDIENTE_CONFIRMACION = "pendiente_confirmacion"
INFORMATIVO = "informativo"
DESCARTADO = "descartado"

#: Estados válidos de cada formato, y cuál es el "positivo" (el que puede
#: ser accionable).
FORMATOS: Dict[str, Dict[str, Any]] = {
    "alteracion": {"estados": ("detectada", "no_detectada", "no_concluyente"), "positivo": "detectada"},
    "reordenamiento": {"estados": ("reordenado", "no_reordenado", "no_concluyente"), "positivo": "reordenado"},
    "ihc_her2": {"estados": ("positivo", "negativo", "equivoco", "no_concluyente"), "positivo": "positivo"},
    "receptor": {"estados": ("positivo", "negativo", "no_concluyente"), "positivo": "positivo"},
    "porcentaje": {"estados": ("cuantificado", "no_concluyente"), "positivo": "cuantificado"},
}
IHC_SCORES = ("0", "1+", "2+", "3+")
RESULTADOS_ISH = ("amplificado", "no_amplificado")

_TEXTO_ESTADO = {
    "detectada": "detectada",
    "no_detectada": "no detectada",
    "reordenado": "reordenado",
    "no_reordenado": "no reordenado",
    "positivo": "positivo",
    "negativo": "negativo",
    "equivoco": "equívoco",
    "no_concluyente": "no concluyente",
}


class ErrorBiomarcador(ValueError):
    """Datos de biopsia o biomarcador inválidos. ``errores`` lista
    ``(campo, mensaje)`` para mostrarlos todos juntos."""

    def __init__(self, errores: Union[str, Sequence[Tuple[str, str]]], campo: str = "biomarcador"):
        self.errores: List[Tuple[str, str]] = [(campo, errores)] if isinstance(errores, str) else list(errores)
        super().__init__("; ".join(f"{c}: {m}" for c, m in self.errores))


class ErrorConfiguracionBiomarcadores(ValueError):
    """El catálogo de biomarcadores no es válido."""


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReglaAccionable:
    variantes: Tuple[str, ...]
    terapia: str
    variable_tx: Optional[str]
    valor_tx: Optional[str]

    def coincide(self, variante: Optional[str]) -> bool:
        if not self.variantes:
            return True
        return bool(variante) and any(re.search(p, variante, re.IGNORECASE) for p in self.variantes)


@dataclass(frozen=True)
class DefinicionBiomarcador:
    codigo: str
    nombre: str
    alias: Tuple[str, ...]
    formato: str
    tipos_cancer: Tuple[str, ...]
    metodos: Tuple[str, ...]
    accionable: Tuple[ReglaAccionable, ...]
    #: estado no positivo -> (variable_tx, valor_tx)
    otros_tx: Dict[str, Tuple[str, str]]


@dataclass(frozen=True)
class EpisodioDiagnostico:
    id: int
    paciente_id: int
    descripcion: str
    tipo_cancer: Optional[str]
    fecha_diagnostico: Optional[str]
    origen: str
    identificador_externo: Optional[str]


@dataclass(frozen=True)
class Biopsia:
    id: int
    paciente_id: int
    episodio_id: int
    fecha: str
    sitio: str
    procedimiento: str
    diagnostico_histologico: Optional[str]
    muestra_externa: Optional[str]
    origen: str
    registrado_por: Optional[str]
    identificador_externo: Optional[str]


@dataclass(frozen=True)
class BiomarcadorRegistrado:
    """Un biomarcador con su dato validado (fila de ``biomarcadores`` +
    ``detalle_biomarcador``)."""

    biomarcador_id: int
    paciente_id: int
    biopsia_id: Optional[int]
    episodio_id: Optional[int]
    fecha: str
    biomarcador: str
    resultado: str
    codigo: str
    estado: str
    valor_numerico: Optional[float]
    unidad: Optional[str]
    metodo: Optional[str]
    variante: Optional[str]
    relevancia: str
    terapia_asociada: Optional[str]
    variable_tx: Optional[str]
    valor_tx: Optional[str]
    confirmado_por: Optional[str]
    fecha_confirmacion: Optional[str]
    origen: str

    @property
    def clave(self) -> bool:
        """Información clave para decidir tratamiento (AC2)."""
        return self.relevancia in (ACCIONABLE_CONFIRMADO, PENDIENTE_CONFIRMACION)


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------

_CACHE_CATALOGO: Dict[Tuple[Path, Path], Dict[str, DefinicionBiomarcador]] = {}


def cargar_catalogo(
    ruta: Union[str, Path] = RUTA_CATALOGO_POR_DEFECTO, ruta_guias: Union[str, Path] = RUTA_GUIAS_POR_DEFECTO
) -> Dict[str, DefinicionBiomarcador]:
    clave = (Path(ruta), Path(ruta_guias))
    if clave not in _CACHE_CATALOGO:
        try:
            datos = yaml.safe_load(Path(ruta).read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise ErrorConfiguracionBiomarcadores(f"No se pudo leer {ruta}: {exc}") from exc
        _CACHE_CATALOGO[clave] = validar_catalogo(datos, variables_de_guias(ruta_guias))
    return _CACHE_CATALOGO[clave]


def variables_de_guias(ruta_guias: Union[str, Path] = RUTA_GUIAS_POR_DEFECTO) -> Dict[str, Dict[str, Any]]:
    """``{variable: {"tipo", "valores"}}`` de todos los ``variables.yaml``."""
    variables: Dict[str, Dict[str, Any]] = {}
    for archivo in sorted(Path(ruta_guias).glob("*/variables.yaml")):
        datos = yaml.safe_load(archivo.read_text(encoding="utf-8")) or {}
        for nombre, definicion in (datos.get("variables") or {}).items():
            entrada = variables.setdefault(nombre, {"tipo": definicion.get("type"), "valores": set()})
            entrada["valores"].update(str(v) for v in definicion.get("allowed_values") or [])
    return variables


def validar_catalogo(datos: Dict[str, Any], variables_tx: Dict[str, Dict[str, Any]]) -> Dict[str, DefinicionBiomarcador]:
    entradas = datos.get("biomarcadores") if isinstance(datos, dict) else None
    if not isinstance(entradas, dict) or not entradas:
        raise ErrorConfiguracionBiomarcadores("El catálogo debe tener una sección 'biomarcadores' no vacía.")

    def variable_valida(codigo: str, variable: Optional[str], valor: Optional[str], formato: str) -> None:
        if (variable is None) != (valor is None):
            raise ErrorConfiguracionBiomarcadores(f"En '{codigo}', variable_tx y valor_tx van juntos.")
        if variable is None:
            return
        if variable not in variables_tx:
            raise ErrorConfiguracionBiomarcadores(
                f"En '{codigo}', la variable '{variable}' no existe en ninguna guía de guidelines/."
            )
        definicion = variables_tx[variable]
        if definicion["tipo"] in ("number", "integer"):
            if valor != "{valor}" or formato != "porcentaje":
                raise ErrorConfiguracionBiomarcadores(
                    f"En '{codigo}', la variable numérica '{variable}' solo puede tomar el valor registrado ('{{valor}}')."
                )
        elif str(valor) not in definicion["valores"]:
            raise ErrorConfiguracionBiomarcadores(
                f"En '{codigo}', '{valor}' no es un valor permitido de '{variable}' "
                f"({', '.join(sorted(definicion['valores']))})."
            )

    catalogo: Dict[str, DefinicionBiomarcador] = {}
    vistos: Dict[str, str] = {}
    for codigo, item in entradas.items():
        if not isinstance(item, dict):
            raise ErrorConfiguracionBiomarcadores(f"El biomarcador '{codigo}' debe ser un diccionario.")
        formato = item.get("formato")
        if formato not in FORMATOS:
            raise ErrorConfiguracionBiomarcadores(f"Formato inválido en '{codigo}': {formato!r}.")
        for campo in ("nombre", "alias", "metodos", "tipos_cancer", "accionable"):
            if not item.get(campo):
                raise ErrorConfiguracionBiomarcadores(f"Al biomarcador '{codigo}' le falta '{campo}'.")

        reglas = []
        for regla in item["accionable"]:
            if not isinstance(regla, dict) or not regla.get("terapia"):
                raise ErrorConfiguracionBiomarcadores(f"Cada regla accionable de '{codigo}' necesita 'terapia'.")
            variantes = tuple(str(v) for v in regla.get("variantes") or ())
            for patron in variantes:
                try:
                    re.compile(patron)
                except re.error as exc:
                    raise ErrorConfiguracionBiomarcadores(f"Expresión inválida en '{codigo}': {patron} ({exc}).") from exc
            if variantes and formato != "alteracion":
                raise ErrorConfiguracionBiomarcadores(f"Solo el formato 'alteracion' admite variantes ('{codigo}').")
            variable_valida(codigo, regla.get("variable_tx"), regla.get("valor_tx"), formato)
            reglas.append(ReglaAccionable(variantes, regla["terapia"], regla.get("variable_tx"),
                                          None if regla.get("valor_tx") is None else str(regla["valor_tx"])))

        otros: Dict[str, Tuple[str, str]] = {}
        for estado, destino in (item.get("otros_tx") or {}).items():
            if estado not in FORMATOS[formato]["estados"] or estado == FORMATOS[formato]["positivo"]:
                raise ErrorConfiguracionBiomarcadores(f"En '{codigo}', otros_tx usa un estado inválido: {estado!r}.")
            variable_valida(codigo, destino.get("variable_tx"), destino.get("valor_tx"), formato)
            otros[estado] = (destino["variable_tx"], str(destino["valor_tx"]))

        alias = tuple(normalizar_texto(str(a)) for a in [codigo, *item["alias"]])
        for a in set(alias):
            if a in vistos and vistos[a] != codigo:
                raise ErrorConfiguracionBiomarcadores(f"El alias '{a}' está en '{vistos[a]}' y en '{codigo}'.")
            vistos[a] = codigo
        catalogo[codigo] = DefinicionBiomarcador(
            codigo=codigo,
            nombre=str(item["nombre"]),
            alias=alias,
            formato=formato,
            tipos_cancer=tuple(str(t) for t in item["tipos_cancer"]),
            metodos=tuple(str(m) for m in item["metodos"]),
            accionable=tuple(reglas),
            otros_tx=otros,
        )
    return catalogo


def buscar_definicion(nombre: str, catalogo: Dict[str, DefinicionBiomarcador]) -> Optional[DefinicionBiomarcador]:
    normalizado = normalizar_texto(nombre)
    return next((d for d in catalogo.values() if normalizado in d.alias), None)


# ---------------------------------------------------------------------------
# AC1: episodios y biopsias
# ---------------------------------------------------------------------------


def _verificar_paciente(conn: sqlite3.Connection, paciente_id: int) -> None:
    if obtener_paciente(conn, paciente_id) is None:
        raise ErrorBiomarcador(f"No existe ningún paciente con id={paciente_id}.", "paciente_id")


def _no_futura(campo: str, fecha: Optional[date]) -> None:
    if fecha is not None and fecha > date.today():
        raise ErrorBiomarcador("La fecha no puede ser futura.", campo)


def registrar_episodio(
    conn: sqlite3.Connection,
    paciente_id: int,
    descripcion: str,
    tipo_cancer: Optional[str] = None,
    fecha_diagnostico: Optional[date] = None,
    origen: str = ORIGEN_MANUAL,
    identificador_externo: Optional[str] = None,
    commit: bool = True,
) -> EpisodioDiagnostico:
    _verificar_paciente(conn, paciente_id)
    if not (descripcion or "").strip():
        raise ErrorBiomarcador("La descripción del diagnóstico es obligatoria.", "descripcion")
    _no_futura("fecha_diagnostico", fecha_diagnostico)
    cursor = conn.execute(
        "INSERT INTO episodios_diagnosticos (paciente_id, descripcion, tipo_cancer, fecha_diagnostico, origen, "
        "identificador_externo) VALUES (?, ?, ?, ?, ?, ?)",
        (paciente_id, descripcion.strip(), (tipo_cancer or "").strip() or None,
         fecha_diagnostico.isoformat() if fecha_diagnostico else None, origen, identificador_externo),
    )
    if commit:
        conn.commit()
    return obtener_episodio(conn, cursor.lastrowid)


def obtener_episodio(conn: sqlite3.Connection, episodio_id: int) -> Optional[EpisodioDiagnostico]:
    fila = conn.execute("SELECT * FROM episodios_diagnosticos WHERE id = ?", (episodio_id,)).fetchone()
    return EpisodioDiagnostico(**dict(fila)) if fila else None


def episodios_de_paciente(conn: sqlite3.Connection, paciente_id: int) -> List[EpisodioDiagnostico]:
    filas = conn.execute(
        "SELECT * FROM episodios_diagnosticos WHERE paciente_id = ? ORDER BY fecha_diagnostico DESC, id DESC",
        (paciente_id,),
    ).fetchall()
    return [EpisodioDiagnostico(**dict(f)) for f in filas]


def registrar_biopsia(
    conn: sqlite3.Connection,
    paciente_id: int,
    *,
    fecha: date,
    sitio: str,
    procedimiento: str,
    diagnostico_histologico: Optional[str] = None,
    episodio_id: Optional[int] = None,
    registrado_por: Optional[str] = None,
    muestra_externa: Optional[str] = None,
    origen: str = ORIGEN_MANUAL,
    identificador_externo: Optional[str] = None,
    commit: bool = True,
) -> Biopsia:
    """AC1: la biopsia queda vinculada a un episodio diagnóstico del paciente."""
    _verificar_paciente(conn, paciente_id)
    errores = []
    if not (sitio or "").strip():
        errores.append(("sitio", "El sitio de la biopsia es obligatorio."))
    if not (procedimiento or "").strip():
        errores.append(("procedimiento", "El procedimiento es obligatorio."))
    if fecha is None:
        errores.append(("fecha", "La fecha de la biopsia es obligatoria."))
    elif fecha > date.today():
        errores.append(("fecha", "La fecha no puede ser futura."))
    if errores:
        raise ErrorBiomarcador(errores)

    episodios = episodios_de_paciente(conn, paciente_id)
    if episodio_id is None:
        if len(episodios) != 1:
            raise ErrorBiomarcador(
                "El paciente no tiene un episodio diagnóstico registrado; registre el diagnóstico antes de la biopsia."
                if not episodios else
                f"El paciente tiene {len(episodios)} episodios diagnósticos; indique a cuál corresponde la biopsia.",
                "episodio_id",
            )
        episodio_id = episodios[0].id
    elif episodio_id not in {e.id for e in episodios}:
        raise ErrorBiomarcador(f"El episodio {episodio_id} no es del paciente {paciente_id}.", "episodio_id")

    cursor = conn.execute(
        "INSERT INTO biopsias (paciente_id, episodio_id, fecha, sitio, procedimiento, diagnostico_histologico, "
        "muestra_externa, origen, registrado_por, identificador_externo) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (paciente_id, episodio_id, fecha.isoformat(), sitio.strip(), procedimiento.strip(),
         (diagnostico_histologico or "").strip() or None, muestra_externa, origen, registrado_por, identificador_externo),
    )
    if commit:
        conn.commit()
    return obtener_biopsia(conn, cursor.lastrowid)


def obtener_biopsia(conn: sqlite3.Connection, biopsia_id: int) -> Optional[Biopsia]:
    fila = conn.execute("SELECT * FROM biopsias WHERE id = ?", (biopsia_id,)).fetchone()
    return Biopsia(**dict(fila)) if fila else None


def biopsias_de_paciente(conn: sqlite3.Connection, paciente_id: int) -> List[Biopsia]:
    filas = conn.execute(
        "SELECT * FROM biopsias WHERE paciente_id = ? ORDER BY fecha DESC, id DESC", (paciente_id,)
    ).fetchall()
    return [Biopsia(**dict(f)) for f in filas]


# ---------------------------------------------------------------------------
# AC2 + validación estricta: registro de biomarcadores
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Validado:
    estado: str
    valor_numerico: Optional[float]
    unidad: Optional[str]
    texto: str
    metodo: str


def _validar(
    definicion: DefinicionBiomarcador,
    estado: str,
    confirmacion: str,
    metodo: Optional[str],
    variante: Optional[str],
    valor: Optional[float],
    ihc_score: Optional[str],
    ish: Optional[str],
) -> _Validado:
    errores: List[Tuple[str, str]] = []
    formato = FORMATOS[definicion.formato]
    estado = (estado or "").strip().lower()
    variante = (variante or "").strip() or None

    if estado not in formato["estados"]:
        errores.append(("estado", f"Estado inválido para {definicion.nombre}: use uno de {', '.join(formato['estados'])}."))
    metodos = {m.lower(): m for m in definicion.metodos}
    if not metodo or metodo.strip().lower() not in metodos:
        errores.append(("metodo", f"Método inválido para {definicion.nombre}: use uno de {', '.join(definicion.metodos)}."))
    else:
        metodo = metodos[metodo.strip().lower()]

    # Doble ingreso del resultado clave.
    clave = (f"{valor:g}" if valor is not None else "") if definicion.formato == "porcentaje" else estado
    if (confirmacion or "").strip().lower().rstrip("%").strip() != clave.lower():
        errores.append(("confirmacion", "La confirmación no coincide con el resultado ingresado: revise el dato."))

    unidad = None
    detalle: List[str] = []
    if definicion.formato == "alteracion":
        if estado == "detectada" and not variante:
            errores.append(("variante", "Indique la variante detectada (p. ej. L858R)."))
        if estado != "detectada" and variante:
            errores.append(("variante", "Solo se registra variante cuando la alteración fue detectada."))
    elif variante:
        errores.append(("variante", f"{definicion.nombre} no admite variante."))

    if definicion.formato == "ihc_her2":
        if ihc_score not in IHC_SCORES and estado != "no_concluyente":
            errores.append(("ihc_score", f"Indique el puntaje IHC ({', '.join(IHC_SCORES)})."))
        if ish is not None and ish not in RESULTADOS_ISH:
            errores.append(("ish", f"Resultado ISH inválido: use {', '.join(RESULTADOS_ISH)}."))
        if ihc_score in IHC_SCORES:
            esperado = {"3+": "positivo", "0": "negativo", "1+": "negativo"}.get(ihc_score)
            if ihc_score == "2+":
                esperado = {"amplificado": "positivo", "no_amplificado": "negativo"}.get(ish, "equivoco")
            if estado in formato["estados"] and estado != "no_concluyente" and estado != esperado:
                errores.append(("estado", f"Con IHC {ihc_score}" + (f" e ISH {ish}" if ish else "")
                                + f" el estado de HER2 es '{esperado}', no '{estado}'."))
            detalle.append(f"IHC {ihc_score}")
            if ish:
                detalle.append(f"ISH {ish.replace('_', ' ')}")
    elif ihc_score is not None or ish is not None:
        errores.append(("ihc_score", f"{definicion.nombre} no usa puntaje IHC/ISH."))

    if definicion.formato == "receptor":
        if valor is not None:
            if not 0 <= valor <= 100:
                errores.append(("valor", "El porcentaje de células teñidas debe estar entre 0 y 100."))
            elif estado in ("positivo", "negativo") and (valor >= 1) != (estado == "positivo"):
                errores.append(("estado", f"Con {valor:g} % de células teñidas el receptor es "
                                          f"{'positivo' if valor >= 1 else 'negativo'} (umbral 1 %)."))
            unidad = "%"
            detalle.append(f"{valor:g} % de células")
    elif definicion.formato == "porcentaje":
        if estado == "cuantificado":
            if valor is None:
                errores.append(("valor", f"Indique el valor de {definicion.nombre} (0-100)."))
            elif not 0 <= valor <= 100:
                errores.append(("valor", f"{definicion.nombre} debe estar entre 0 y 100."))
        elif valor is not None:
            errores.append(("valor", "Un resultado no concluyente no lleva valor."))
        unidad = "%"
    elif valor is not None:
        errores.append(("valor", f"{definicion.nombre} no lleva valor numérico."))

    if errores:
        raise ErrorBiomarcador(errores)

    if definicion.formato == "porcentaje" and estado == "cuantificado":
        texto = f"{valor:g} %"
    else:
        texto = _TEXTO_ESTADO.get(estado, estado)
        if variante:
            texto += f": {variante}"
    extras = [*detalle, metodo]
    texto += f" ({', '.join(e for e in extras if e)})"
    return _Validado(estado, valor, unidad, texto, metodo)


def tipo_cancer_del_paciente(conn: sqlite3.Connection, paciente_id: int, episodio_id: Optional[int] = None) -> Optional[str]:
    """El del episodio si lo tiene; si no, el último ``cancer_type`` registrado."""
    if episodio_id is not None:
        episodio = obtener_episodio(conn, episodio_id)
        if episodio and episodio.tipo_cancer:
            return episodio.tipo_cancer
    fila = conn.execute(
        "SELECT valor FROM datos_clinicos_estructurados WHERE paciente_id = ? AND variable = 'cancer_type' "
        "ORDER BY fecha DESC, id DESC LIMIT 1",
        (paciente_id,),
    ).fetchone()
    return fila[0] if fila else None


def clasificar(
    definicion: DefinicionBiomarcador, estado: str, variante: Optional[str], valor: Optional[float], tipo_cancer: Optional[str]
) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
    """``(accionable, terapia, variable_tx, valor_tx)``.

    Accionable solo si el tipo de cáncer es uno de los del catálogo: sin
    tipo de cáncer conocido no se puede afirmar (fail-closed)."""
    if tipo_cancer not in definicion.tipos_cancer:
        return False, None, None, None
    if estado == FORMATOS[definicion.formato]["positivo"]:
        for regla in definicion.accionable:
            if regla.coincide(variante):
                valor_tx = regla.valor_tx
                if valor_tx == "{valor}":
                    valor_tx = f"{valor:g}" if valor is not None else None
                return True, regla.terapia, regla.variable_tx, valor_tx
        return False, None, None, None
    if estado in definicion.otros_tx:
        variable, valor_tx = definicion.otros_tx[estado]
        return False, None, variable, valor_tx
    return False, None, None, None


def registrar_biomarcador(
    conn: sqlite3.Connection,
    paciente_id: int,
    *,
    biopsia_id: int,
    biomarcador: str,
    estado: str,
    confirmacion: str,
    metodo: str,
    variante: Optional[str] = None,
    valor: Optional[float] = None,
    ihc_score: Optional[str] = None,
    ish: Optional[str] = None,
    registrado_por: Optional[str] = None,
    catalogo: Optional[Dict[str, DefinicionBiomarcador]] = None,
    ahora: Optional[datetime] = None,
) -> BiomarcadorRegistrado:
    """Registra un biomarcador validado, vinculado a una biopsia (y por ella
    al episodio). Si es accionable para el tipo de cáncer, escribe la
    variable que lee TX-01; un resultado negativo también la escribe (p. ej.
    ``egfr_status=wild_type``), porque es igual de decisivo.

    Lanza ``ErrorBiomarcador`` (con todos los errores) sin guardar nada si
    el dato no es válido."""
    catalogo = catalogo if catalogo is not None else cargar_catalogo()
    _verificar_paciente(conn, paciente_id)
    biopsia = obtener_biopsia(conn, biopsia_id)
    if biopsia is None or biopsia.paciente_id != paciente_id:
        raise ErrorBiomarcador(f"La biopsia {biopsia_id} no es del paciente {paciente_id}.", "biopsia_id")
    definicion = buscar_definicion(biomarcador or "", catalogo)
    if definicion is None:
        raise ErrorBiomarcador(
            f"Biomarcador no reconocido: '{biomarcador}'. Use uno del catálogo: "
            + ", ".join(d.nombre for d in catalogo.values()) + ".",
            "biomarcador",
        )
    validado = _validar(definicion, estado, confirmacion, metodo, variante, valor, ihc_score, ish)
    variante = (variante or "").strip() or None

    accionable, terapia, variable_tx, valor_tx = clasificar(
        definicion, validado.estado, variante, validado.valor_numerico,
        tipo_cancer_del_paciente(conn, paciente_id, biopsia.episodio_id),
    )
    relevancia = ACCIONABLE_CONFIRMADO if accionable else INFORMATIVO
    momento = ahora_iso(ahora)
    try:
        cursor = conn.execute(
            "INSERT INTO biomarcadores (paciente_id, fecha, biomarcador, resultado) VALUES (?, ?, ?, ?)",
            (paciente_id, biopsia.fecha, definicion.nombre, validado.texto),
        )
        biomarcador_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO detalle_biomarcador (biomarcador_id, paciente_id, biopsia_id, codigo, estado, valor_numerico, "
            "unidad, metodo, variante, relevancia, terapia_asociada, variable_tx, valor_tx, confirmado_por, "
            "fecha_confirmacion, origen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (biomarcador_id, paciente_id, biopsia_id, definicion.codigo, validado.estado, validado.valor_numerico,
             validado.unidad, validado.metodo, variante, relevancia, terapia, variable_tx, valor_tx,
             registrado_por if variable_tx else None, momento if variable_tx else None, ORIGEN_MANUAL),
        )
        if variable_tx and valor_tx is not None:
            _escribir_variable_tx(conn, paciente_id, biopsia.fecha, variable_tx, valor_tx)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return obtener_biomarcador(conn, paciente_id, biomarcador_id)


def _escribir_variable_tx(conn: sqlite3.Connection, paciente_id: int, fecha: str, variable: str, valor: str) -> None:
    """Fila nueva (nunca se sobrescribe): TX-01 usa la más reciente."""
    conn.execute(
        "INSERT INTO datos_clinicos_estructurados (paciente_id, fecha, variable, valor) VALUES (?, ?, ?, ?)",
        (paciente_id, fecha, variable, valor),
    )


# ---------------------------------------------------------------------------
# Biomarcadores importados: destacar y confirmar
# ---------------------------------------------------------------------------

_HALLAZGO_IMPORTADO = re.compile(r"(mutación|fusión) detectada: ([^;(—]+)")
_MUESTRA = re.compile(r"— muestra (\S+)")


def marcar_potencialmente_accionables(
    conn: sqlite3.Connection,
    paciente_id: int,
    catalogo: Optional[Dict[str, DefinicionBiomarcador]] = None,
    commit: bool = True,
) -> List[int]:
    """Destaca, sin escribir ninguna variable de tratamiento, los
    biomarcadores importados que el catálogo considera accionables para el
    tipo de cáncer del paciente ("mutación detectada: L858R", "fusión
    detectada: EML4-ALK", HER2 "positivo"). Quedan como
    ``pendiente_confirmacion`` hasta que el oncólogo los confirma.
    Idempotente: un biomarcador que ya tiene detalle no se toca."""
    catalogo = catalogo if catalogo is not None else cargar_catalogo()
    tipo_cancer = tipo_cancer_del_paciente(conn, paciente_id)
    marcados: List[int] = []
    filas = conn.execute(
        "SELECT b.* FROM biomarcadores b LEFT JOIN detalle_biomarcador d ON d.biomarcador_id = b.id "
        "WHERE b.paciente_id = ? AND d.biomarcador_id IS NULL ORDER BY b.id",
        (paciente_id,),
    ).fetchall()
    for fila in filas:
        definicion = buscar_definicion(fila["biomarcador"], catalogo)
        if definicion is None:
            continue
        estado, variante = _leer_hallazgo_importado(definicion, fila["resultado"])
        if estado is None:
            continue
        accionable, terapia, variable_tx, valor_tx = clasificar(definicion, estado, variante, None, tipo_cancer)
        if not accionable:
            continue
        muestra = _MUESTRA.search(fila["resultado"] or "")
        biopsia = conn.execute(
            "SELECT id FROM biopsias WHERE paciente_id = ? AND muestra_externa = ?",
            (paciente_id, muestra.group(1) if muestra else None),
        ).fetchone()
        conn.execute(
            "INSERT INTO detalle_biomarcador (biomarcador_id, paciente_id, biopsia_id, codigo, estado, variante, "
            "relevancia, terapia_asociada, variable_tx, valor_tx, origen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (fila["id"], paciente_id, biopsia[0] if biopsia else None, definicion.codigo, estado, variante,
             PENDIENTE_CONFIRMACION, terapia, variable_tx, valor_tx, "importado"),
        )
        marcados.append(fila["id"])
    if commit:
        conn.commit()
    return marcados


def _leer_hallazgo_importado(definicion: DefinicionBiomarcador, resultado: str) -> Tuple[Optional[str], Optional[str]]:
    texto = resultado or ""
    if definicion.formato in ("alteracion", "reordenamiento"):
        for tipo, hallazgo in _HALLAZGO_IMPORTADO.findall(texto):
            hallazgo = hallazgo.strip()
            if tipo == "mutación" and definicion.formato == "alteracion":
                return "detectada", hallazgo.split(" ")[0]
            if tipo == "fusión" and definicion.formato == "reordenamiento":
                return "reordenado", hallazgo.split(" ")[0]
        return None, None
    if definicion.formato in ("ihc_her2", "receptor") and normalizar_texto(texto) == "positivo":
        return "positivo", None
    return None, None


def confirmar_biomarcador(
    conn: sqlite3.Connection,
    paciente_id: int,
    biomarcador_id: int,
    confirmado_por: str,
    confirmacion: str,
    ahora: Optional[datetime] = None,
) -> BiomarcadorRegistrado:
    """El oncólogo confirma un biomarcador pendiente: pasa a accionable y
    su variable de tratamiento queda disponible para TX-01. ``confirmacion``
    debe repetir el estado registrado (doble verificación)."""
    registrado = obtener_biomarcador(conn, paciente_id, biomarcador_id)
    if registrado is None:
        raise ErrorBiomarcador(f"El paciente {paciente_id} no tiene el biomarcador {biomarcador_id}.", "biomarcador_id")
    if registrado.relevancia != PENDIENTE_CONFIRMACION:
        raise ErrorBiomarcador("Solo se confirman biomarcadores pendientes de confirmación.", "biomarcador_id")
    if not (confirmado_por or "").strip():
        raise ErrorBiomarcador("Indique quién confirma el biomarcador.", "confirmado_por")
    if (confirmacion or "").strip().lower() != registrado.estado:
        raise ErrorBiomarcador(
            f"La confirmación no coincide con el resultado registrado ('{registrado.estado}').", "confirmacion"
        )
    try:
        conn.execute(
            "UPDATE detalle_biomarcador SET relevancia = ?, confirmado_por = ?, fecha_confirmacion = ? "
            "WHERE biomarcador_id = ?",
            (ACCIONABLE_CONFIRMADO, confirmado_por.strip(), ahora_iso(ahora), biomarcador_id),
        )
        if registrado.variable_tx and registrado.valor_tx is not None:
            _escribir_variable_tx(conn, paciente_id, registrado.fecha, registrado.variable_tx, registrado.valor_tx)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return obtener_biomarcador(conn, paciente_id, biomarcador_id)


def descartar_biomarcador(
    conn: sqlite3.Connection, paciente_id: int, biomarcador_id: int, revisado_por: str, ahora: Optional[datetime] = None
) -> BiomarcadorRegistrado:
    """El oncólogo decide que un pendiente no es accionable para este
    paciente: deja de destacarse y no se escribe ninguna variable."""
    registrado = obtener_biomarcador(conn, paciente_id, biomarcador_id)
    if registrado is None or registrado.relevancia != PENDIENTE_CONFIRMACION:
        raise ErrorBiomarcador("Solo se descartan biomarcadores pendientes de confirmación.", "biomarcador_id")
    if not (revisado_por or "").strip():
        raise ErrorBiomarcador("Indique quién revisó el biomarcador.", "revisado_por")
    conn.execute(
        "UPDATE detalle_biomarcador SET relevancia = ?, confirmado_por = ?, fecha_confirmacion = ? WHERE biomarcador_id = ?",
        (DESCARTADO, revisado_por.strip(), ahora_iso(ahora), biomarcador_id),
    )
    conn.commit()
    return obtener_biomarcador(conn, paciente_id, biomarcador_id)


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------

_SQL_REGISTRADOS = (
    "SELECT b.id AS biomarcador_id, b.paciente_id, d.biopsia_id, bi.episodio_id, b.fecha, b.biomarcador, b.resultado, "
    "d.codigo, d.estado, d.valor_numerico, d.unidad, d.metodo, d.variante, d.relevancia, d.terapia_asociada, "
    "d.variable_tx, d.valor_tx, d.confirmado_por, d.fecha_confirmacion, d.origen "
    "FROM biomarcadores b JOIN detalle_biomarcador d ON d.biomarcador_id = b.id "
    "LEFT JOIN biopsias bi ON bi.id = d.biopsia_id WHERE b.paciente_id = ?"
)


def obtener_biomarcador(conn: sqlite3.Connection, paciente_id: int, biomarcador_id: int) -> Optional[BiomarcadorRegistrado]:
    fila = conn.execute(_SQL_REGISTRADOS + " AND b.id = ?", (paciente_id, biomarcador_id)).fetchone()
    return BiomarcadorRegistrado(**dict(fila)) if fila else None


def biomarcadores_registrados(conn: sqlite3.Connection, paciente_id: int) -> List[BiomarcadorRegistrado]:
    filas = conn.execute(_SQL_REGISTRADOS + " ORDER BY b.fecha DESC, b.id DESC", (paciente_id,)).fetchall()
    return [BiomarcadorRegistrado(**dict(f)) for f in filas]


def biomarcadores_clave(conn: sqlite3.Connection, paciente_id: int) -> List[BiomarcadorRegistrado]:
    """AC2: la información molecular clave para decidir tratamiento, con
    los confirmados primero y luego los pendientes de confirmación."""
    orden = {ACCIONABLE_CONFIRMADO: 0, PENDIENTE_CONFIRMACION: 1}
    clave = [b for b in biomarcadores_registrados(conn, paciente_id) if b.clave]
    return sorted(clave, key=lambda b: orden[b.relevancia])


__all__ = [
    "ACCIONABLE_CONFIRMADO",
    "Biopsia",
    "BiomarcadorRegistrado",
    "DESCARTADO",
    "DefinicionBiomarcador",
    "EpisodioDiagnostico",
    "ErrorBiomarcador",
    "ErrorConfiguracionBiomarcadores",
    "FORMATOS",
    "INFORMATIVO",
    "PENDIENTE_CONFIRMACION",
    "biomarcadores_clave",
    "biomarcadores_registrados",
    "biopsias_de_paciente",
    "buscar_definicion",
    "cargar_catalogo",
    "clasificar",
    "confirmar_biomarcador",
    "descartar_biomarcador",
    "episodios_de_paciente",
    "marcar_potencialmente_accionables",
    "obtener_biomarcador",
    "obtener_biopsia",
    "obtener_episodio",
    "registrar_biomarcador",
    "registrar_biopsia",
    "registrar_episodio",
    "tipo_cancer_del_paciente",
    "validar_catalogo",
    "variables_de_guias",
]
