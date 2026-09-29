"""Importación de pacientes de cBioPortal al expediente clínico.

``FuenteCBioPortal`` cumple el protocolo ``FuenteHistoriaExterna`` de
HC-01, así que la carga pasa por el mismo camino que FHIR y HL7:
verificación de identidad, transacción todo-o-nada, idempotencia por
``registros_importados`` y registro de cada intento en
``sincronizaciones_externas``.

Lo único que agrega este módulo es lo que HC-01 no hace: crear (o
actualizar) la fila del paciente y elegir qué pacientes traer de un
estudio.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from historia_clinica.integracion_externa import (
    ResultadoSincronizacion,
    importar_historia,
    sincronizar_paciente,
)

from .cliente import ClienteCBioPortal
from .mapeo import (
    FORMATO_CBIOPORTAL,
    GENES_POR_TIPO,
    FichaPaciente,
    ficha_paciente,
    identificacion_cbioportal,
    partes_identificacion,
    registros_desde_cbioportal,
    tipo_cancer,
)

ESTUDIO_POR_DEFECTO = "msk_chord_2024"
TIPOS_POR_DEFECTO = ("Breast Cancer", "Non-Small Cell Lung Cancer")


class FuenteCBioPortal:
    """``fecha_referencia``: fecha en la que se ubica el último evento de
    cada paciente (ver ``mapeo.calendario``). Conviene fijarla para que
    re-importar dé las mismas fechas."""

    formato = FORMATO_CBIOPORTAL
    nombre = "cbioportal"

    def __init__(self, cliente: Optional[ClienteCBioPortal] = None, fecha_referencia: Optional[date] = None):
        self.cliente = cliente or ClienteCBioPortal()
        self.fecha_referencia = fecha_referencia or date.today()
        self._perfiles: Dict[str, Dict[str, str]] = {}

    def obtener_historia(self, identificacion: str) -> Dict[str, Any]:
        return self.historia(*partes_identificacion(identificacion))

    def traducir(self, contenido: Dict[str, Any], paciente: Any):
        return registros_desde_cbioportal(contenido, paciente, self.fecha_referencia)

    def historia(self, estudio: str, paciente: str) -> Dict[str, Any]:
        """Todo lo que se importa de un paciente, en un solo diccionario."""
        c = self.cliente
        muestras = [{"id": m, "datos": c.datos_clinicos_muestra(estudio, m)} for m in c.muestras_de_paciente(estudio, paciente)]
        contenido: Dict[str, Any] = {
            "estudio": estudio,
            "paciente": paciente,
            "datos_paciente": c.datos_clinicos_paciente(estudio, paciente),
            "muestras": muestras,
            "eventos": c.eventos_clinicos(estudio, paciente),
            "mutaciones": [],
            "fusiones": [],
            "genes_fusiones": [],
            "genes_evaluados": {},
        }
        genes = GENES_POR_TIPO.get(tipo_cancer(contenido) or "")
        if genes and muestras:
            self._agregar_genomica(contenido, estudio, genes)
        return contenido

    def _agregar_genomica(self, contenido: Dict[str, Any], estudio: str, genes: Dict[str, Sequence[str]]) -> None:
        c = self.cliente
        if estudio not in self._perfiles:
            self._perfiles[estudio] = c.perfiles_moleculares(estudio)
        perfiles = self._perfiles[estudio]
        entrez = c.entrez_ids([*genes["mutaciones"], *genes["fusiones"]])
        ids = [m["id"] for m in contenido["muestras"]]

        consultados = {"mutaciones": [], "fusiones": []}
        if "MUTATION_EXTENDED" in perfiles:
            consultados["mutaciones"] = [g for g in genes["mutaciones"] if g in entrez]
            contenido["mutaciones"] = c.mutaciones(
                perfiles["MUTATION_EXTENDED"], ids, {g: entrez[g] for g in consultados["mutaciones"]}
            )
        if "STRUCTURAL_VARIANT" in perfiles:
            consultados["fusiones"] = [g for g in genes["fusiones"] if g in entrez]
            contenido["genes_fusiones"] = consultados["fusiones"]
            contenido["fusiones"] = c.fusiones(
                perfiles["STRUCTURAL_VARIANT"], ids, {g: entrez[g] for g in consultados["fusiones"]}
            )

        # "No detectada" solo para genes que el panel de la muestra cubre.
        for muestra in contenido["muestras"]:
            panel = muestra["datos"].get("GENE_PANEL")
            if not panel:
                continue
            cubiertos = c.genes_de_panel(panel)
            contenido["genes_evaluados"][muestra["id"]] = {
                clave: [g for g in lista if g in cubiertos] for clave, lista in consultados.items()
            }


@dataclass(frozen=True)
class ResultadoImportacion:
    identificacion: str
    #: ``None`` si el paciente no existía y no se pudo traer de cBioPortal.
    paciente_id: Optional[int]
    paciente_nuevo: bool
    sincronizacion: ResultadoSincronizacion
    #: Lo descargado de cBioPortal (para volcarlo también en otros módulos).
    contenido: Optional[Dict[str, Any]] = None
    ficha: Optional[FichaPaciente] = None


def importar_paciente(
    conn: sqlite3.Connection, fuente: FuenteCBioPortal, estudio: str, paciente: str
) -> ResultadoImportacion:
    """Trae un paciente de cBioPortal y lo carga (o actualiza) en el expediente.

    No lanza por fallos de red o de contenido: devuelve ``exito=False`` en
    ``sincronizacion`` y, si el paciente ya existía, el fallo queda en
    ``sincronizaciones_externas`` como en cualquier otra fuente de HC-01.
    """
    identificacion = identificacion_cbioportal(estudio, paciente)
    try:
        contenido = fuente.historia(estudio, paciente)
    except Exception as exc:  # noqa: BLE001 -- se reporta, no se propaga
        existente = _paciente_por_identificacion(conn, identificacion)
        if existente is None:
            mensaje = f"No se pudo traer {identificacion} de cBioPortal ({type(exc).__name__}: {exc}). No se creó el paciente."
            return ResultadoImportacion(identificacion, None, False, ResultadoSincronizacion(False, None, mensaje=mensaje))
        # Reintenta por el camino de HC-01, que registra el fallo si persiste.
        return ResultadoImportacion(identificacion, existente, False, sincronizar_paciente(conn, existente, fuente))

    ficha = ficha_paciente(contenido, fuente.fecha_referencia)
    paciente_id, nuevo = _guardar_paciente(conn, ficha)
    resultado = importar_historia(conn, paciente_id, contenido, fuente)
    return ResultadoImportacion(identificacion, paciente_id, nuevo, resultado, contenido, ficha)


def seleccionar_pacientes(
    cliente: ClienteCBioPortal, estudio: str, tipos: Iterable[str] = TIPOS_POR_DEFECTO, por_tipo: int = 25
) -> List[str]:
    """Los primeros ``por_tipo`` pacientes (por id, reproducible) de cada
    tipo de cáncer. Se descartan los que tienen muestras de más de un
    tipo, porque su ``cancer_type`` sería ambiguo."""
    tipos_por_paciente: Dict[str, set] = {}
    for fila in cliente.tipo_de_cancer_por_muestra(estudio):
        tipos_por_paciente.setdefault(fila["paciente"], set()).add(fila["tipo_cancer"])
    elegidos: List[str] = []
    for tipo in tipos:
        candidatos = sorted(p for p, t in tipos_por_paciente.items() if t == {tipo})
        elegidos.extend(candidatos[:por_tipo])
    return elegidos


def importar_estudio(
    conn: sqlite3.Connection,
    fuente: FuenteCBioPortal,
    estudio: str = ESTUDIO_POR_DEFECTO,
    pacientes: Optional[Sequence[str]] = None,
    tipos: Iterable[str] = TIPOS_POR_DEFECTO,
    por_tipo: int = 25,
    al_importar: Optional[Callable[[int, int, ResultadoImportacion], None]] = None,
) -> List[ResultadoImportacion]:
    """Importa ``pacientes`` (o una selección por tipo de cáncer) de ``estudio``.

    Un paciente que falla no detiene a los demás. ``al_importar(i, total,
    resultado)`` se llama después de cada uno (para mostrar progreso).
    """
    if pacientes is None:
        pacientes = seleccionar_pacientes(fuente.cliente, estudio, tipos, por_tipo)
    resultados = []
    for i, paciente in enumerate(pacientes, start=1):
        resultado = importar_paciente(conn, fuente, estudio, paciente)
        resultados.append(resultado)
        if al_importar:
            al_importar(i, len(pacientes), resultado)
    return resultados


def _paciente_por_identificacion(conn: sqlite3.Connection, identificacion: str) -> Optional[int]:
    fila = conn.execute("SELECT id FROM pacientes WHERE identificacion = ?", (identificacion,)).fetchone()
    return fila[0] if fila else None


def _guardar_paciente(conn: sqlite3.Connection, ficha: FichaPaciente):
    """Crea el paciente o actualiza sus datos demográficos y de diagnóstico."""
    existente = _paciente_por_identificacion(conn, ficha.identificacion)
    valores = (ficha.nombre, ficha.fecha_nacimiento, ficha.sexo, ficha.diagnostico_principal, ficha.estadio)
    if existente is not None:
        conn.execute(
            "UPDATE pacientes SET nombre = ?, fecha_nacimiento = ?, sexo = ?, diagnostico_principal = ?, estadio = ? "
            "WHERE id = ?",
            (*valores, existente),
        )
        conn.commit()
        return existente, False
    cursor = conn.execute(
        "INSERT INTO pacientes (nombre, fecha_nacimiento, sexo, diagnostico_principal, estadio, identificacion) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (*valores, ficha.identificacion),
    )
    conn.commit()
    return cursor.lastrowid, True
