"""Catálogo de estudios clínicamente relevantes por sospecha diagnóstica (DX-01).

Igual que ``knowledge_base.py`` (DX-02), esto es una tabla de conocimiento
curada y explícita, no un modelo estadístico ni un LLM decidiendo qué
estudios pedir: cada entrada del catálogo indica, de forma legible por un
humano, qué sospecha diagnóstica la activa, qué estudio se sugiere y por
qué. Es deliberadamente un punto de partida pequeño para poder probar
DX-01 de punta a punta (pensado para los pacientes sintéticos de
``historia_clinica_mock``), no un catálogo clínico validado ni exhaustivo.

Cada :class:`EstudioCatalogado` incluye ``palabras_clave_equivalencia``:
las palabras clave que ``recomendacion_estudios`` usa para reconocer que
"ya existe un estudio equivalente" en el expediente del paciente (mismo
``tipo`` de hallazgo — laboratorio / imagenología / biomarcador — y texto
que menciona ese mismo estudio), para poder cumplir el criterio de
aceptación de no volver a sugerir un estudio redundante.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class EstudioCatalogado:
    """Un estudio (laboratorio, imagen o biomarcador) sugerible ante una sospecha."""

    id: str
    nombre: str
    #: "laboratorio" | "imagenologia" | "biomarcador" — debe coincidir con
    #: ``HallazgoClinico.origen`` para poder cruzar contra lo ya registrado.
    tipo: str
    #: Por qué este estudio es clínicamente relevante para la sospecha que
    #: lo activa (criterio de aceptación: "lista priorizada CON
    #: JUSTIFICACIÓN de cada estudio sugerido"). Nunca se sugiere un
    #: estudio sin esta justificación.
    justificacion: str
    #: Palabras clave para detectar, dentro de los hallazgos ya registrados
    #: del mismo ``tipo``, si un estudio equivalente ya existe. Deben ser
    #: lo bastante específicas para no confundir estudios distintos del
    #: mismo tipo (p. ej. una TAC de tórax no debería "cubrir" una TAC de
    #: abdomen).
    palabras_clave_equivalencia: Tuple[str, ...]
    #: Prioridad explícita (1 = más prioritario). Nunca un puntaje ni una
    #: probabilidad calculada — mismo principio que ``DiagnosticoDiferencialCandidato.orden``
    #: en DX-02: un orden explicable, curado por el catálogo.
    prioridad: int


@dataclass(frozen=True)
class PerfilSospechaDiagnostica:
    """Qué estudios sugerir cuando la sospecha diagnóstica de entrada coincide con este perfil."""

    id: str
    nombre: str
    #: Palabras clave para reconocer, en el texto de la sospecha
    #: diagnóstica que ingresa el oncólogo, que este perfil aplica.
    palabras_clave: Tuple[str, ...]
    estudios: Tuple[EstudioCatalogado, ...]


PERFIL_PROGRESION_ENFERMEDAD_METASTASICA = PerfilSospechaDiagnostica(
    id="progresion_enfermedad_metastasica",
    nombre="Sospecha de progresión de enfermedad oncológica metastásica",
    palabras_clave=("progresión", "progresion", "recaída", "recaida"),
    estudios=(
        EstudioCatalogado(
            id="hemograma_completo",
            nombre="Hemograma completo",
            tipo="laboratorio",
            justificacion=(
                "Evaluar reserva medular y descartar toxicidad hematológica "
                "concomitante antes de considerar un cambio de línea de tratamiento."
            ),
            palabras_clave_equivalencia=("hemograma",),
            prioridad=1,
        ),
        EstudioCatalogado(
            id="perfil_hepatico",
            nombre="Perfil hepático",
            tipo="laboratorio",
            justificacion=(
                "Descartar toxicidad hepática o compromiso hepático metastásico "
                "antes de definir el manejo."
            ),
            palabras_clave_equivalencia=("función hepática", "funcion hepatica", "perfil hepático"),
            prioridad=2,
        ),
        EstudioCatalogado(
            id="tac_torax_control",
            nombre="TAC de tórax de control",
            tipo="imagenologia",
            justificacion=(
                "Confirmar y cuantificar objetivamente la sospecha de progresión "
                "pulmonar con una imagen de control."
            ),
            palabras_clave_equivalencia=(
                "tac de tórax",
                "tac de torax",
                "tomografía de tórax",
                "tomografia de torax",
                "tomografía computarizada de tórax",
            ),
            prioridad=1,
        ),
        EstudioCatalogado(
            id="reevaluacion_biomarcadores_moleculares",
            nombre="Reevaluación de biomarcadores moleculares (nueva biopsia o biopsia líquida)",
            tipo="biomarcador",
            justificacion=(
                "Ante progresión, reevaluar el perfil molecular (p. ej. posibles "
                "mecanismos de resistencia) puede cambiar la conducta terapéutica."
            ),
            palabras_clave_equivalencia=("egfr", "alk", "ros1", "kras", "biomarcador"),
            prioridad=2,
        ),
    ),
)

PERFIL_TOXICIDAD_MUSCULOESQUELETICA_ESTUDIOS = PerfilSospechaDiagnostica(
    id="toxicidad_musculoesqueletica",
    nombre="Sospecha de toxicidad musculoesquelética asociada a tratamiento oncológico",
    palabras_clave=("toxicidad musculoesquelética", "toxicidad musculoesqueletica", "dolor articular", "artralgia"),
    estudios=(
        EstudioCatalogado(
            id="perfil_reumatologico_basico",
            nombre="Perfil reumatológico básico (factor reumatoide, anti-CCP, PCR)",
            tipo="laboratorio",
            justificacion=(
                "Diferenciar toxicidad musculoesquelética relacionada con el "
                "tratamiento de un proceso reumatológico concomitante."
            ),
            palabras_clave_equivalencia=("factor reumatoide", "anti-ccp", "anti ccp", "pcr", "reumatológico", "reumatologico"),
            prioridad=1,
        ),
        EstudioCatalogado(
            id="radiografia_articulacion_afectada",
            nombre="Radiografía simple de la articulación afectada",
            tipo="imagenologia",
            justificacion="Descartar compromiso óseo estructural como causa alternativa del dolor articular.",
            palabras_clave_equivalencia=("radiografía", "radiografia", "rx de"),
            prioridad=2,
        ),
    ),
)

PERFIL_PROCESO_INFECCIOSO_RESPIRATORIO_ESTUDIOS = PerfilSospechaDiagnostica(
    id="proceso_infeccioso_respiratorio",
    nombre="Sospecha de proceso infeccioso respiratorio concomitante",
    palabras_clave=("fiebre", "proceso infeccioso", "neumonía", "neumonia"),
    estudios=(
        EstudioCatalogado(
            id="hemograma_con_diferencial",
            nombre="Hemograma completo con diferencial",
            tipo="laboratorio",
            justificacion="Evaluar leucocitosis u otros signos de respuesta inflamatoria/infecciosa.",
            palabras_clave_equivalencia=("hemograma",),
            prioridad=1,
        ),
        EstudioCatalogado(
            id="radiografia_torax",
            nombre="Radiografía de tórax",
            tipo="imagenologia",
            justificacion="Estudio de primera línea para evaluar un foco infeccioso respiratorio.",
            palabras_clave_equivalencia=("radiografía de tórax", "radiografia de torax", "rx de tórax", "rx de torax"),
            prioridad=1,
        ),
    ),
)

CATALOGO_ESTUDIOS_POR_SOSPECHA: Tuple[PerfilSospechaDiagnostica, ...] = (
    PERFIL_PROGRESION_ENFERMEDAD_METASTASICA,
    PERFIL_TOXICIDAD_MUSCULOESQUELETICA_ESTUDIOS,
    PERFIL_PROCESO_INFECCIOSO_RESPIRATORIO_ESTUDIOS,
)
