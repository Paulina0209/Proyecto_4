"""Revisión y aprobación de notas clínicas generadas por IA (IA-03).

Como oncólogo, quiero revisar, editar y aprobar el borrador de una nota
clínica generada por IA, para asegurarme de que su contenido sea correcto
antes de convertirla en una nota clínica oficial. Hasta que se otorgue
esa aprobación explícita, el documento permanece en estado de borrador y
no puede considerarse una nota clínica oficial.

Depende de IA-02 (``ia_clinica.notes``): este módulo recibe el
``ClinicalNoteDraft`` que produce IA-02 y le agrega el flujo de
edición/aprobación; no genera contenido clínico nuevo ni vuelve a validar
la trazabilidad contra la consulta (eso ya lo hizo IA-02).

Regla de negocio no negociable (ver backlog, historia IA-03): ninguna
nota generada por IA puede adquirir estado final u oficial sin una
acción explícita de aprobación por parte de un médico autorizado. No
existe ninguna transición automática hacia ese estado.

Componentes públicos:
    - :class:`ia_clinica.review.models.EstadoNota` (``DRAFT`` / ``APPROVED``)
    - :class:`ia_clinica.review.models.NotaEnRevision` (snapshot de solo lectura)
    - :mod:`ia_clinica.review.service`: ``iniciar_revision``,
      ``editar_seccion``, ``aprobar_nota``, ``obtener_revision``
    - :mod:`ia_clinica.review.store`: persistencia SQLite subyacente
"""

from ia_clinica.review.models import (
    AprobacionRegistrada,
    EdicionRegistrada,
    EstadoNota,
    NotaEnRevision,
    NotaYaAprobadaError,
    RevisionNoEncontradaError,
    RevisionYaExisteError,
)
from ia_clinica.review.service import (
    aprobar_nota,
    editar_seccion,
    iniciar_revision,
    obtener_revision,
)

__all__ = [
    "EstadoNota",
    "NotaEnRevision",
    "EdicionRegistrada",
    "AprobacionRegistrada",
    "RevisionNoEncontradaError",
    "RevisionYaExisteError",
    "NotaYaAprobadaError",
    "iniciar_revision",
    "editar_seccion",
    "aprobar_nota",
    "obtener_revision",
]
