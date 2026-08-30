"""Modelos de dominio para IA-03 — Revisión y aprobación de notas clínicas.

Como oncólogo, quiero revisar, editar y aprobar el borrador de una nota
clínica generada por IA, para asegurarme de que su contenido sea correcto
antes de convertirla en una nota clínica oficial.

Reglas de negocio no negociables (ver backlog, historia IA-03):
    1. Ninguna nota generada por IA puede adquirir el estado final u
       oficial ("APPROVED") sin una acción explícita de aprobación por
       parte de un médico autorizado. No existe ninguna transición
       automática hacia ese estado.
    2. Mientras una nota no haya sido aprobada, se identifica siempre
       como "borrador no confirmado" — sin importar si el usuario cierra
       sesión, recarga la página o retoma la revisión más tarde (por eso
       el estado se persiste en :mod:`ia_clinica.review.store`, no solo
       en memoria).
    3. Los estados de una nota se manejan de forma explícita: al menos
       ``DRAFT`` y ``APPROVED`` (nota técnica de IA-03). No hay estados
       intermedios ocultos ni un booleano genérico "aprobado: sí/no" que
       pueda confundirse con otra cosa.

Diseño deliberado: :class:`NotaEnRevision` es un *snapshot* inmutable de
solo lectura (igual que ``ClinicalNoteDraft`` en IA-02). No expone ningún
método que cambie su propio estado — toda mutación (editar una sección,
aprobar la nota) pasa exclusivamente por funciones de
:mod:`ia_clinica.review.store` / :mod:`ia_clinica.review.service`, que
además son las únicas que pueden escribir en el almacenamiento
persistente. Esto hace imposible, por construcción, que algún otro código
del proyecto marque una nota como aprobada "de paso" sin pasar por
``aprobar_nota()``.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Mapping, Optional, Tuple


class EstadoNota(str, enum.Enum):
    """Estados explícitos de una nota en revisión.

    Solo existen estos dos valores (nota técnica de IA-03). La única
    forma de pasar de ``DRAFT`` a ``APPROVED`` es a través de
    ``service.aprobar_nota()`` / ``store.aprobar_nota()``, que exigen un
    identificador no vacío del profesional autorizado.
    """

    DRAFT = "DRAFT"
    APPROVED = "APPROVED"


class RevisionNoEncontradaError(Exception):
    """La nota en revisión solicitada no existe en el almacenamiento."""


class RevisionYaExisteError(Exception):
    """Ya existe un proceso de revisión registrado para este identificador de nota."""


class NotaYaAprobadaError(Exception):
    """La nota ya fue aprobada: no se puede editar de nuevo ni volver a aprobar.

    Una vez que una nota es oficial (``APPROVED``), este módulo no ofrece
    ninguna forma de seguir editándola desde el flujo de borrador ni de
    "reabrirla" implícitamente. Si el equipo clínico necesita corregir una
    nota ya aprobada, eso es una historia distinta (enmienda de nota
    oficial), fuera del alcance de IA-03.
    """


@dataclass(frozen=True)
class EdicionRegistrada:
    """Un cambio guardado sobre el contenido de una sección de la nota.

    Se conserva el contenido anterior además del nuevo para poder
    reconstruir el historial completo de ediciones (importante dado el
    riesgo clínico/regulatorio de la historia: cualquier cambio sobre un
    borrador generado por IA debe quedar auditable).
    """

    autor: str
    seccion_key: str
    contenido_anterior: str
    contenido_nuevo: str
    editado_en: str

    def __post_init__(self) -> None:
        if not self.autor or not self.autor.strip():
            raise ValueError("EdicionRegistrada.autor no puede estar vacío.")
        if not self.seccion_key or not self.seccion_key.strip():
            raise ValueError("EdicionRegistrada.seccion_key no puede estar vacío.")


@dataclass(frozen=True)
class AprobacionRegistrada:
    """Evidencia de la acción explícita de aprobación (regla de negocio de IA-03)."""

    aprobado_por: str
    aprobado_en: str

    def __post_init__(self) -> None:
        if not self.aprobado_por or not self.aprobado_por.strip():
            raise ValueError(
                "AprobacionRegistrada.aprobado_por no puede estar vacío: la "
                "aprobación exige un identificador explícito del médico "
                "autorizado, nunca una aprobación anónima o implícita."
            )


@dataclass(frozen=True)
class NotaEnRevision:
    """Vista de solo lectura (snapshot) del estado actual de una nota en revisión.

    No expone ningún método que modifique su propio estado: es
    deliberadamente un objeto de lectura, análogo a ``ClinicalNoteDraft``
    de IA-02. Toda mutación pasa por :mod:`ia_clinica.review.store` /
    :mod:`ia_clinica.review.service`.
    """

    nota_id: str
    paciente_ref: str
    contenido_ia_original: Mapping[str, str]
    contenido_actual: Mapping[str, str]
    estado: EstadoNota
    creado_en: str
    historial_ediciones: Tuple[EdicionRegistrada, ...] = field(default_factory=tuple)
    aprobacion: Optional[AprobacionRegistrada] = None

    def es_nota_oficial(self) -> bool:
        """True únicamente si la nota fue aprobada explícitamente.

        Este es el único método que el resto del sistema debería usar
        para decidir si una nota puede presentarse como nota clínica
        oficial (criterio de aceptación: "una nota en estado borrador no
        puede presentarse como nota clínica oficial"). Nunca inferir
        "oficial" a partir de, por ejemplo, que ya tenga ediciones
        guardadas o que ya no tenga advertencias: solo ``estado``
        cuenta, y ``estado`` solo cambia dentro de ``aprobar_nota()``.
        """
        return self.estado is EstadoNota.APPROVED

    def fue_editada(self) -> bool:
        return len(self.historial_ediciones) > 0

    def etiqueta_estado(self) -> str:
        """Etiqueta legible para mostrar en cualquier UI/reporte/demo.

        Existe para que ningún otro módulo tenga que reinventar (y
        potencialmente redactar mal) el texto que distingue un borrador
        no confirmado de una nota oficial.
        """
        if self.es_nota_oficial():
            return "NOTA CLÍNICA APROBADA"
        return "BORRADOR NO CONFIRMADO (generado por IA, pendiente de aprobación)"
