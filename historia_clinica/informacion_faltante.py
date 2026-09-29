"""HC-05 — Detección de información faltante.

Como oncólogo, quiero que el sistema me indique qué información clínica
falta para tomar una decisión (diagnóstico, estadificación o
tratamiento), para no avanzar con datos incompletos.

El expediente se evalúa contra un checklist configurable por tipo de
cáncer (``checklists_informacion.yaml``, o el archivo que indique la
institución). Tres resultados posibles, nunca más:

    - ``COMPLETA``: todos los ítems de las fases evaluadas están presentes
      con un valor concluyente. Es el único caso sin alerta (AC2).
    - ``INCOMPLETA``: falta al menos un ítem, o su valor no es
      concluyente ("pendiente", "equívoco", "unknown"...). La alerta lista
      cada ítem y el motivo (AC1).
    - ``NO_EVALUABLE``: no hay checklist para ese tipo de cáncer (o para
      esa fase), o no se sabe qué cáncer tiene el paciente. Se dice
      explícitamente que no se puede valorar la completitud (AC3).

Riesgo clínico de la historia: un falso "completo" es peor que no tener
la función. Por eso la regla es fail-closed: cualquier duda (sin
checklist, fase sin ítems, valor no interpretable) se reporta como
alerta, nunca como completo.

Este módulo solo lee el expediente (``expediente``): no
registra datos ni modifica nada.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

import yaml

from historia_clinica.db import normalizar_texto
from expediente.repository import (
    biomarcadores_de_paciente,
    datos_clinicos_estructurados_de_paciente,
    imagenologia_de_paciente,
    laboratorios_de_paciente,
    obtener_paciente,
)

RUTA_CHECKLIST_POR_DEFECTO = Path(__file__).resolve().parent / "checklists_informacion.yaml"

FASES = ("diagnostico", "estadificacion", "tratamiento")

#: Valores que significan "hay un registro, pero no responde la pregunta".
_VALORES_NO_CONCLUYENTES = {
    "unknown", "pending", "equivocal", "incomplete", "not_evaluable",
    "desconocido", "pendiente", "equivoco", "indeterminado", "no concluyente",
    "no evaluable", "insuficiente", "muestra insuficiente", "en proceso", "no realizado",
}


class EstadoCompletitud(str, Enum):
    COMPLETA = "completa"
    INCOMPLETA = "incompleta"
    NO_EVALUABLE = "no_evaluable"


@dataclass(frozen=True)
class ItemFaltante:
    id: str
    descripcion: str
    fases: Tuple[str, ...]
    #: "sin dato registrado" | "valor no concluyente"
    motivo: str
    #: El valor no concluyente encontrado, si lo hay (nunca se oculta).
    valor_registrado: Optional[str] = None
    #: Fila exacta de donde salió ese valor (p. ej. "biomarcador-3").
    fuente: Optional[str] = None


@dataclass(frozen=True)
class EvaluacionCompletitud:
    paciente_id: int
    estado: EstadoCompletitud
    tipo_cancer: Optional[str]
    fases_evaluadas: Tuple[str, ...]
    faltantes: Tuple[ItemFaltante, ...]
    #: Ítems que sí están presentes, con la fila que los respalda.
    presentes: Tuple[Tuple[str, str], ...]
    mensaje: str

    @property
    def mostrar_alerta(self) -> bool:
        """AC2: solo un expediente COMPLETO se muestra sin alerta."""
        return self.estado is not EstadoCompletitud.COMPLETA

    @property
    def alerta(self) -> Optional[str]:
        return self.mensaje if self.mostrar_alerta else None


def cargar_checklists(ruta: Union[str, Path] = RUTA_CHECKLIST_POR_DEFECTO) -> Dict[str, Any]:
    """Carga y valida el checklist institucional.

    Un checklist mal formado se rechaza al cargarlo, no al evaluar a un
    paciente: un ítem sin evidencias nunca podría cumplirse y uno con una
    fase inexistente nunca se evaluaría, ambos en silencio.
    """
    contenido = yaml.safe_load(Path(ruta).read_text(encoding="utf-8")) or {}
    tipos = contenido.get("tipos_cancer") or {}
    for codigo, definicion in tipos.items():
        for item in definicion.get("items") or []:
            if not item.get("id") or not item.get("evidencias"):
                raise ValueError(f"Checklist '{codigo}': cada ítem necesita 'id' y al menos una evidencia.")
            fases_invalidas = set(item.get("fases") or []) - set(FASES)
            if not item.get("fases") or fases_invalidas:
                raise ValueError(
                    f"Checklist '{codigo}', ítem '{item['id']}': fases inválidas o vacías "
                    f"({sorted(fases_invalidas) or 'ninguna'}); válidas: {', '.join(FASES)}."
                )
            for evidencia in item["evidencias"]:
                if len(evidencia) != 1 or next(iter(evidencia)) not in {"variable", "biomarcador", "imagen", "laboratorio"}:
                    raise ValueError(f"Checklist '{codigo}', ítem '{item['id']}': evidencia no reconocida {evidencia!r}.")
    return contenido


def evaluar_informacion_faltante(
    conn: sqlite3.Connection,
    paciente_id: int,
    fases: Optional[Sequence[str]] = None,
    tipo_cancer: Optional[str] = None,
    checklists: Optional[Dict[str, Any]] = None,
) -> EvaluacionCompletitud:
    """Evalúa qué información falta en el expediente para decidir con confianza.

    ``fases``: subconjunto de ``FASES``; por defecto, las tres.
    ``tipo_cancer``: el sospechado o confirmado; si se omite se toma de la
    variable ``cancer_type`` del expediente.
    """
    if obtener_paciente(conn, paciente_id) is None:
        raise ValueError(f"No existe ningún paciente con id={paciente_id}.")
    fases_pedidas = tuple(fases or FASES)
    desconocidas = set(fases_pedidas) - set(FASES)
    if desconocidas:
        raise ValueError(f"Fases no reconocidas: {sorted(desconocidas)}; válidas: {', '.join(FASES)}.")
    checklists = checklists if checklists is not None else cargar_checklists()

    variables = _ultimo_valor_por_variable(conn, paciente_id)
    tipo_declarado = tipo_cancer or variables.get("cancer_type", (None, None))[0]
    if not tipo_declarado:
        return _no_evaluable(
            paciente_id, None, fases_pedidas,
            "No se puede evaluar la completitud del expediente: no hay un tipo de cáncer "
            "registrado ni sospechado para este paciente. Esto no significa que la información esté completa.",
        )

    codigo, definicion = _resolver_tipo_cancer(checklists, tipo_declarado)
    if definicion is None:
        return _no_evaluable(
            paciente_id, tipo_declarado, fases_pedidas,
            f"No hay un checklist clínico definido para '{tipo_declarado}': el sistema no puede evaluar "
            "si falta información para este caso. Esto no significa que la información esté completa; "
            "verifique el expediente manualmente.",
        )

    items = [i for i in definicion.get("items") or [] if set(i["fases"]) & set(fases_pedidas)]
    if not items:
        return _no_evaluable(
            paciente_id, codigo, fases_pedidas,
            f"El checklist de {definicion.get('nombre', codigo)} no define ítems para "
            f"{', '.join(fases_pedidas)}: no se puede evaluar la completitud para esa fase.",
        )

    expediente = _Expediente(conn, paciente_id, variables)
    faltantes: List[ItemFaltante] = []
    presentes: List[Tuple[str, str]] = []
    for item in items:
        fases_item = tuple(f for f in item["fases"] if f in fases_pedidas)
        presente, no_concluyente = expediente.buscar(item["evidencias"])
        if presente:
            presentes.append((item["id"], presente))
        elif no_concluyente:
            valor, fuente = no_concluyente
            faltantes.append(ItemFaltante(item["id"], item["descripcion"], fases_item, "valor no concluyente", valor, fuente))
        else:
            faltantes.append(ItemFaltante(item["id"], item["descripcion"], fases_item, "sin dato registrado"))

    nombre = definicion.get("nombre", codigo)
    if not faltantes:
        return EvaluacionCompletitud(
            paciente_id, EstadoCompletitud.COMPLETA, codigo, fases_pedidas, (), tuple(presentes),
            f"La información requerida por el checklist de {nombre} para {', '.join(fases_pedidas)} está disponible.",
        )

    detalle = "; ".join(
        f"{f.descripcion} ({f.motivo}{': ' + repr(f.valor_registrado) if f.valor_registrado else ''})"
        for f in faltantes
    )
    return EvaluacionCompletitud(
        paciente_id, EstadoCompletitud.INCOMPLETA, codigo, fases_pedidas, tuple(faltantes), tuple(presentes),
        f"Falta información para decidir con confianza ({nombre}, {', '.join(fases_pedidas)}): {detalle}.",
    )


# ---------------------------------------------------------------------------


def _no_evaluable(paciente_id, tipo_cancer, fases, mensaje) -> EvaluacionCompletitud:
    return EvaluacionCompletitud(
        paciente_id, EstadoCompletitud.NO_EVALUABLE, tipo_cancer, tuple(fases), (), (), mensaje
    )


def _resolver_tipo_cancer(checklists: Dict[str, Any], tipo: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    buscado = normalizar_texto(tipo)
    for codigo, definicion in (checklists.get("tipos_cancer") or {}).items():
        nombres = {normalizar_texto(codigo), *(normalizar_texto(a) for a in definicion.get("alias") or [])}
        if buscado in nombres:
            return codigo, definicion
    return None, None


def _ultimo_valor_por_variable(conn: sqlite3.Connection, paciente_id: int) -> Dict[str, Tuple[str, str]]:
    """{variable: (valor, fuente)} con el registro más reciente de cada variable."""
    ultimos: Dict[str, Any] = {}
    for dato in datos_clinicos_estructurados_de_paciente(conn, paciente_id):
        actual = ultimos.get(dato.variable)
        if actual is None or (dato.fecha, dato.id) >= (actual.fecha, actual.id):
            ultimos[dato.variable] = dato
    return {v: (d.valor, f"dato-estructurado-{d.id}") for v, d in ultimos.items()}


def _es_concluyente(valor: Optional[str]) -> bool:
    normalizado = normalizar_texto(valor or "").replace("_", " ")
    if not normalizado:
        return False
    return not any(
        normalizado == n or normalizado.startswith(n + " ") for n in _VALORES_NO_CONCLUYENTES
    )


def _coincide(texto: str, terminos: Iterable[str]) -> bool:
    normalizado = f" {normalizar_texto(texto)} "
    return any(f" {normalizar_texto(t)} " in normalizado for t in terminos)


class _Expediente:
    """Vista de solo lectura del expediente, cargada una vez por evaluación."""

    def __init__(self, conn: sqlite3.Connection, paciente_id: int, variables: Dict[str, Tuple[str, str]]):
        self.variables = variables
        self.biomarcadores = biomarcadores_de_paciente(conn, paciente_id)
        self.imagenes = imagenologia_de_paciente(conn, paciente_id)
        self.laboratorios = laboratorios_de_paciente(conn, paciente_id)

    def buscar(self, evidencias: List[Dict[str, Any]]) -> Tuple[Optional[str], Optional[Tuple[str, str]]]:
        """Devuelve (fuente_presente, (valor, fuente)_no_concluyente)."""
        no_concluyente: Optional[Tuple[str, str]] = None
        for evidencia in evidencias:
            tipo, criterio = next(iter(evidencia.items()))
            for valor, fuente in self._candidatos(tipo, criterio):
                if _es_concluyente(valor):
                    return fuente, None
                no_concluyente = no_concluyente or (valor, fuente)
        return None, no_concluyente

    def _candidatos(self, tipo: str, criterio: Any) -> List[Tuple[str, str]]:
        if tipo == "variable":
            return [self.variables[criterio]] if criterio in self.variables else []
        if tipo == "biomarcador":
            # Más reciente primero: un resultado nuevo concluyente reemplaza a uno viejo pendiente.
            filas = sorted(self.biomarcadores, key=lambda b: (b.fecha, b.id), reverse=True)
            return [(b.resultado, f"biomarcador-{b.id}") for b in filas if _coincide(b.biomarcador, criterio)]
        if tipo == "imagen":
            return [
                (i.hallazgos, f"imagen-{i.id}") for i in self.imagenes
                if not criterio or _coincide(i.region, criterio)
            ]
        if tipo == "laboratorio":
            return [(lab.valor, f"lab-{lab.id}") for lab in self.laboratorios if _coincide(lab.prueba, criterio)]
        return []
