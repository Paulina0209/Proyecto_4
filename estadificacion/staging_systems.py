"""Catálogo versionado de sistemas de estadificación (EST-01).

Cada ``SistemaEstadificacion`` declara, de forma explícita y legible por un
humano, qué componentes usa (T, N, M), de qué variable del expediente sale cada
uno, y cómo se combinan esos componentes en un grupo de estadio. No hay ningún
modelo estadístico ni LLM decidiendo el estadio: es una tabla de conocimiento
curada y versionada, en el mismo espíritu que ``guidelines/`` y que
``dx_clinica/knowledge_base.py``.

Nota de alcance (igual que DX-02): las tablas de agrupación aquí son un
**subconjunto ilustrativo mínimo**, suficiente para probar EST-01 de punta a
punta contra los pacientes sintéticos de ``historia_clinica_mock``. No
reproducen la totalidad de una edición de AJCC/UICC y **no están validadas
clínicamente**. El estadio propuesto es siempre apoyo a la decisión y debe
validarlo el profesional (regla de negocio de EST-01).

Regla de negocio clave: al estadificar un tipo de cáncer solo se usan los
criterios del sistema y versión seleccionados para ese cáncer. El builder nunca
lee variables que no pertenezcan al sistema elegido.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Tuple

_NOTA_ALCANCE = (
    "Subconjunto ilustrativo mínimo de la agrupación por estadios; no reproduce "
    "la edición completa del sistema y no está validado clínicamente. El estadio "
    "propuesto es apoyo a la decisión y debe validarlo el profesional."
)

#: Comodín para una casilla de la tabla de grupos que aplica a cualquier valor.
CUALQUIERA = "*"


@dataclass(frozen=True)
class ComponenteDef:
    """Un componente del sistema (T, N o M) y de dónde se lee en el expediente."""

    codigo: str  # "T" | "N" | "M"
    variable_expediente: str
    descripcion_criterio: str
    valores_reconocidos: Tuple[str, ...]
    #: Qué información clínica hace falta para poder determinar este componente
    #: (EST-03). Depende del sistema/versión, por eso vive aquí y no en el motor.
    informacion_requerida: str = ""

    def familias_para_enumerar(self) -> Tuple[str, ...]:
        """Familias posibles de este componente, para explorar estadios candidatos.

        Cada valor reconocido se normaliza a su familia (``"cT2"`` -> ``"T2"``);
        los que no se pueden normalizar (``"Tis"``) se conservan tal cual, que es
        como aparecen en ``tabla_grupos``.
        """

        vistas: dict[str, None] = {}
        for valor in self.valores_reconocidos:
            vistas.setdefault(familia_de_valor(valor) or valor, None)
        return tuple(vistas)


@dataclass(frozen=True)
class SistemaEstadificacion:
    id: str  # p. ej. "AJCC"
    version: str  # p. ej. "8"
    nombre: str
    fuente: str
    cancer_types: Tuple[str, ...]
    componentes: Tuple[ComponenteDef, ...]
    #: Filas ``((T, N, M), grupo)``. Cada casilla admite el comodín ``"*"``.
    #: El orden importa: la primera fila que coincide gana.
    tabla_grupos: Tuple[Tuple[Tuple[str, str, str], str], ...]
    nota_alcance: str = _NOTA_ALCANCE

    def identificador_legible(self) -> str:
        return f"{self.id} {self.nombre} (v{self.version})"

    def componente(self, codigo: str) -> Optional[ComponenteDef]:
        for comp in self.componentes:
            if comp.codigo == codigo:
                return comp
        return None

    def variables_requeridas(self) -> Tuple[str, ...]:
        return tuple(c.variable_expediente for c in self.componentes)


_FAMILIA = re.compile(r"([TNM])\s*(\d)", re.IGNORECASE)


def familia_de_valor(valor: str) -> Optional[str]:
    """Normaliza un valor de componente a su familia: ``"cT2"`` -> ``"T2"``.

    Ignora los prefijos clínicos/patológicos (``c``, ``p``, ``yc``, ``yp``,
    ``r``) y los sufijos de subcategoría (``T4b`` -> ``T4``). Devuelve ``None``
    si el valor no tiene la forma esperada.
    """

    if not valor:
        return None
    match = _FAMILIA.search(valor.strip())
    if not match:
        return None
    return f"{match.group(1).upper()}{match.group(2)}"


_INFO_T = (
    "Evaluación de la extensión del tumor primario (tamaño e invasión local) por "
    "examen físico, imágenes diagnósticas y/o estudio anatomopatológico."
)
_INFO_N = (
    "Evaluación de los ganglios linfáticos regionales por imágenes, biopsia de "
    "ganglio centinela o disección ganglionar."
)
_INFO_M = (
    "Estudios de extensión (imágenes de tórax/abdomen/pelvis, u otros según el "
    "cuadro) para confirmar o descartar metástasis a distancia."
)

_TNM_BREAST = (
    ComponenteDef(
        "T",
        "clinical_t_category",
        "Extensión del tumor primario (categoría T clínica).",
        ("T0", "Tis", "T1", "T2", "T3", "T4"),
        _INFO_T,
    ),
    ComponenteDef(
        "N",
        "clinical_n_status",
        "Compromiso de ganglios linfáticos regionales (categoría N clínica).",
        ("N0", "N1", "N2", "N3"),
        _INFO_N,
    ),
    ComponenteDef(
        "M",
        "clinical_m_status",
        "Presencia de metástasis a distancia (categoría M).",
        ("M0", "M1"),
        _INFO_M,
    ),
)

_TNM_GENERICO = (
    ComponenteDef(
        "T", "clinical_t_category", "Extensión del tumor primario (categoría T).",
        ("T0", "T1", "T2", "T3", "T4"), _INFO_T,
    ),
    ComponenteDef(
        "N", "clinical_n_status", "Compromiso ganglionar regional (categoría N).",
        ("N0", "N1", "N2", "N3"), _INFO_N,
    ),
    ComponenteDef(
        "M", "clinical_m_status", "Metástasis a distancia (categoría M).",
        ("M0", "M1"), _INFO_M,
    ),
)


AJCC_BREAST_8 = SistemaEstadificacion(
    id="AJCC",
    version="8",
    nombre="Breast Cancer Staging (anatómico)",
    fuente="AJCC Cancer Staging Manual, 8th Edition (2017), capítulo de mama — agrupación anatómica.",
    cancer_types=("breast",),
    componentes=_TNM_BREAST,
    tabla_grupos=(
        ((CUALQUIERA, CUALQUIERA, "M1"), "IV"),
        (("Tis", "N0", "M0"), "0"),
        (("T1", "N0", "M0"), "IA"),
        (("T0", "N1", "M0"), "IIA"),
        (("T1", "N1", "M0"), "IIA"),
        (("T2", "N0", "M0"), "IIA"),
        (("T2", "N1", "M0"), "IIB"),
        (("T3", "N0", "M0"), "IIB"),
        (("T3", "N1", "M0"), "IIIA"),
        (("T0", "N2", "M0"), "IIIA"),
        (("T1", "N2", "M0"), "IIIA"),
        (("T2", "N2", "M0"), "IIIA"),
        (("T3", "N2", "M0"), "IIIA"),
        (("T4", CUALQUIERA, "M0"), "IIIB"),
        ((CUALQUIERA, "N3", "M0"), "IIIC"),
    ),
)

AJCC_NSCLC_8 = SistemaEstadificacion(
    id="AJCC",
    version="8",
    nombre="Lung Cancer Staging (agrupación simplificada)",
    fuente="AJCC Cancer Staging Manual, 8th Edition (2017), capítulo de pulmón — agrupación simplificada.",
    cancer_types=("NSCLC", "lung"),
    componentes=_TNM_GENERICO,
    tabla_grupos=(
        ((CUALQUIERA, CUALQUIERA, "M1"), "IV"),
        (("T1", "N0", "M0"), "I"),
        (("T2", "N0", "M0"), "IB"),
        (("T1", "N1", "M0"), "IIB"),
        (("T2", "N1", "M0"), "IIB"),
        (("T3", "N0", "M0"), "IIB"),
        (("T3", "N1", "M0"), "IIIA"),
        (("T4", "N0", "M0"), "IIIA"),
        (("T4", "N1", "M0"), "IIIA"),
        ((CUALQUIERA, "N2", "M0"), "IIIB"),
        ((CUALQUIERA, "N3", "M0"), "IIIC"),
    ),
)

AJCC_MELANOMA_8 = SistemaEstadificacion(
    id="AJCC",
    version="8",
    nombre="Cutaneous Melanoma Staging (agrupación clínica simplificada)",
    fuente="AJCC Cancer Staging Manual, 8th Edition (2017), capítulo de melanoma cutáneo — agrupación clínica simplificada.",
    cancer_types=("melanoma",),
    componentes=_TNM_GENERICO,
    tabla_grupos=(
        ((CUALQUIERA, CUALQUIERA, "M1"), "IV"),
        (("T1", "N0", "M0"), "I"),
        (("T2", "N0", "M0"), "I"),
        (("T3", "N0", "M0"), "II"),
        (("T4", "N0", "M0"), "II"),
        ((CUALQUIERA, "N1", "M0"), "III"),
        ((CUALQUIERA, "N2", "M0"), "III"),
        ((CUALQUIERA, "N3", "M0"), "III"),
    ),
)

AJCC_RCC_8 = SistemaEstadificacion(
    id="AJCC",
    version="8",
    nombre="Renal Cell Carcinoma Staging",
    fuente="AJCC Cancer Staging Manual, 8th Edition (2017), capítulo de riñón.",
    cancer_types=("renal_cell_carcinoma",),
    componentes=_TNM_GENERICO,
    tabla_grupos=(
        ((CUALQUIERA, CUALQUIERA, "M1"), "IV"),
        (("T1", "N0", "M0"), "I"),
        (("T2", "N0", "M0"), "II"),
        (("T3", "N0", "M0"), "III"),
        (("T1", "N1", "M0"), "III"),
        (("T2", "N1", "M0"), "III"),
        (("T3", "N1", "M0"), "III"),
        (("T4", CUALQUIERA, "M0"), "IV"),
    ),
)

CATALOGO_SISTEMAS: Tuple[SistemaEstadificacion, ...] = (
    AJCC_BREAST_8,
    AJCC_NSCLC_8,
    AJCC_MELANOMA_8,
    AJCC_RCC_8,
)

# Asociación explícita y curada entre el tipo de cáncer registrado en el
# expediente y el sistema de estadificación aplicable. Es deliberadamente una
# tabla explícita (no un emparejamiento difuso): si un tipo de cáncer no está
# aquí, se devuelve None en vez de adivinar un sistema que nadie validó.
_CANCER_A_SISTEMA = {
    cancer_type: sistema
    for sistema in CATALOGO_SISTEMAS
    for cancer_type in sistema.cancer_types
}


def sistema_para_cancer(cancer_type: Optional[str]) -> Optional[SistemaEstadificacion]:
    """Sistema de estadificación aplicable a un tipo de cáncer, o ``None``."""

    if not cancer_type:
        return None
    return _CANCER_A_SISTEMA.get(cancer_type)


def _casilla_coincide(patron: str, valor: Optional[str]) -> bool:
    return patron == CUALQUIERA or patron == valor


def agrupar_estadio(
    sistema: SistemaEstadificacion,
    familia_t: Optional[str],
    familia_n: Optional[str],
    familia_m: Optional[str],
) -> Optional[str]:
    """Aplica la tabla de grupos del sistema a las familias T/N/M normalizadas.

    Devuelve ``None`` si falta algún componente o si la combinación no está en
    la tabla (EST-01 no inventa un grupo: reporta que no se pudo determinar).
    """

    if not (familia_t and familia_n and familia_m):
        return None
    for (patron_t, patron_n, patron_m), grupo in sistema.tabla_grupos:
        if (
            _casilla_coincide(patron_t, familia_t)
            and _casilla_coincide(patron_n, familia_n)
            and _casilla_coincide(patron_m, familia_m)
        ):
            return grupo
    return None


def estadios_candidatos(
    sistema: SistemaEstadificacion,
    familias_conocidas: dict,
) -> Tuple[str, ...]:
    """Estadios posibles cuando solo se conocen algunos componentes (EST-03).

    ``familias_conocidas`` mapea código de componente ("T"/"N"/"M") a su familia
    determinada. Los componentes ausentes se exploran sobre todos sus valores
    reconocidos y se recogen los grupos distintos que resultan, ordenados de
    menor a mayor. No se asume ningún valor: si la información conocida ya
    determina un único grupo, la tupla trae un solo elemento.
    """

    from itertools import product

    ejes: list[list[str]] = []
    codigos: list[str] = []
    for comp in sistema.componentes:
        codigos.append(comp.codigo)
        conocida = familias_conocidas.get(comp.codigo)
        if conocida:
            ejes.append([conocida])
        else:
            ejes.append(list(comp.familias_para_enumerar()))

    grupos: dict = {}
    for combinacion in product(*ejes):
        asignacion = dict(zip(codigos, combinacion))
        grupo = agrupar_estadio(
            sistema, asignacion.get("T"), asignacion.get("N"), asignacion.get("M")
        )
        if grupo is not None:
            grupos.setdefault(grupo, None)

    return tuple(sorted(grupos, key=orden_estadio))


_ORDEN_ROMANO = {"0": 0, "I": 1, "II": 2, "III": 3, "IV": 4}
_ESTADIO_RE = re.compile(r"^(0|IV|III|II|I)([A-D]?)")


def orden_estadio(grupo: str) -> tuple:
    """Clave de orden para un grupo de estadio ("IIA" < "IIB" < "III")."""

    match = _ESTADIO_RE.match(grupo.strip())
    if not match:
        return (99, 99)
    base = _ORDEN_ROMANO.get(match.group(1), 99)
    sub = ord(match.group(2)) - ord("A") + 1 if match.group(2) else 0
    return (base, sub)
