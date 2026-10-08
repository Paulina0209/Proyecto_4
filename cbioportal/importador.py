"""Importación de pacientes de cBioPortal al expediente clínico.

``FuenteCBioPortal`` cumple el protocolo ``FuenteHistoriaExterna`` de
HC-01, así que la carga pasa por el mismo camino que FHIR y HL7:
verificación de identidad, transacción todo-o-nada, idempotencia por
``registros_importados`` y registro de cada intento en
``sincronizaciones_externas``.

Lo único que agrega este módulo es lo que HC-01 no hace: crear (o
actualizar) la fila del paciente, elegir qué pacientes traer de un
estudio y vincular sus muestras con HC-04 (``vincular_biopsias``):
episodio diagnóstico, una biopsia por muestra y biomarcadores
potencialmente accionables pendientes de confirmación.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from historia_clinica.biopsias_biomarcadores import marcar_potencialmente_accionables
from historia_clinica.integracion_externa import (
    ResultadoSincronizacion,
    importar_historia,
    registrar_fallo_sincronizacion,
)

from .cliente import ClienteCBioPortal
from .mapeo import (
    FORMATO_CBIOPORTAL,
    GENES_POR_TIPO,
    FichaPaciente,
    calendario,
    ficha_paciente,
    identificacion_cbioportal,
    partes_identificacion,
    registros_desde_cbioportal,
    tipo_cancer,
)

log = logging.getLogger(__name__)

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
        return ResultadoImportacion(
            identificacion, existente, False, registrar_fallo_sincronizacion(conn, existente, fuente, exc)
        )

    ficha = ficha_paciente(contenido, fuente.fecha_referencia)
    paciente_id, nuevo = _guardar_paciente(conn, ficha)
    resultado = importar_historia(conn, paciente_id, contenido, fuente)
    if resultado.exito:
        try:
            vincular_biopsias(conn, paciente_id, contenido, fuente.fecha_referencia)
        except Exception:  # noqa: BLE001 -- la historia ya quedó importada; HC-04 se reintenta al re-importar
            conn.rollback()
            log.exception("No se pudieron vincular las biopsias de %s (HC-04).", identificacion)
    return ResultadoImportacion(identificacion, paciente_id, nuevo, resultado, contenido, ficha)


def vincular_biopsias(conn: sqlite3.Connection, paciente_id: int, contenido: Dict[str, Any], fecha_referencia: date) -> None:
    """HC-04 para un paciente importado. Idempotente (``identificador_externo``).

    - Un episodio diagnóstico por el diagnóstico primario. Con más de un
      primario no se crea ninguno: no se puede saber a cuál pertenece cada
      muestra (la misma regla fail-closed que el mapeo aplica al estadio).
    - Una biopsia por muestra secuenciada, vinculada a ese episodio.
    - Los biomarcadores accionables quedan pendientes de confirmación, sin
      escribir variables de tratamiento (ver ``mapeo``: una variante no es
      un "positivo" hasta que el oncólogo lo confirma).
    """
    estudio, paciente = contenido["estudio"], contenido["paciente"]
    primarios = [
        e for e in contenido.get("eventos") or []
        if e["tipo"] == "Diagnosis" and e["atributos"].get("SUBTYPE") == "Primary"
    ]
    if len(primarios) == 1:
        fecha = calendario(contenido, fecha_referencia)
        primario = primarios[0]
        clave_episodio = f"cbioportal:{estudio}:{paciente}:primario"
        episodio = conn.execute(
            "SELECT id FROM episodios_diagnosticos WHERE identificador_externo = ?", (clave_episodio,)
        ).fetchone()
        if episodio is None:
            ficha = ficha_paciente(contenido, fecha_referencia)
            cursor = conn.execute(
                "INSERT INTO episodios_diagnosticos (paciente_id, descripcion, tipo_cancer, fecha_diagnostico, origen, "
                "identificador_externo) VALUES (?, ?, ?, ?, ?, ?)",
                (paciente_id, ficha.diagnostico_principal or primario["atributos"].get("DX_DESCRIPTION") or "Diagnóstico primario",
                 tipo_cancer(contenido), fecha(primario.get("inicio")), FORMATO_CBIOPORTAL, clave_episodio),
            )
            episodio_id = cursor.lastrowid
        else:
            episodio_id = episodio[0]

        dia_muestra = {
            e["atributos"].get("SAMPLE_ID"): e.get("inicio")
            for e in contenido.get("eventos") or [] if e["tipo"] == "Sample acquisition"
        }
        for muestra in contenido.get("muestras") or []:
            datos = muestra["datos"]
            conn.execute(
                "INSERT OR IGNORE INTO biopsias (paciente_id, episodio_id, fecha, sitio, procedimiento, "
                "diagnostico_histologico, muestra_externa, origen, identificador_externo) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (paciente_id, episodio_id, fecha(dia_muestra.get(muestra["id"])),
                 datos.get("PRIMARY_SITE") or datos.get("SAMPLE_TYPE") or "no especificado",
                 "Muestra tumoral secuenciada (cBioPortal)", datos.get("CANCER_TYPE_DETAILED"),
                 muestra["id"], FORMATO_CBIOPORTAL, f"cbioportal:{estudio}:{muestra['id']}"),
            )
    marcar_potencialmente_accionables(conn, paciente_id, commit=False)
    conn.commit()


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
