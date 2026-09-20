"""Gestión documental (épica DOC del backlog).

Como oncólogo, quiero exportar un resumen o expediente en PDF, para
compartirlo con el paciente, otro especialista o la aseguradora
(**DOC-02**).

Este paquete es deliberadamente independiente de qué produjo el
contenido que se exporta: no sabe nada de `ia_clinica`, `dx_clinica` ni
`historia_clinica_mock` en su núcleo (`pdf_export.py`). Recibe un
:class:`~documentos_clinicos.pdf_export.DocumentoExportable` — un modelo
genérico de "documento con secciones" — y produce el PDF. Los
adaptadores en `adaptadores.py` son los que sí conocen esos módulos
concretos y traducen su salida al modelo genérico:

    - :func:`adaptadores.resumen_caso_a_documento_exportable` — exporta
      el resumen de caso para junta médica/interconsulta
      (`ia_clinica.summary`).
    - :func:`adaptadores.expediente_completo_a_documento_exportable` —
      exporta el expediente completo de un paciente directamente desde
      `historia_clinica_mock` (consultas, laboratorios, imagenología,
      biomarcadores, comorbilidades).

Ninguno de los dos camino genera un PDF "profesional" a partir de la
nada: si el documento resultante no tiene ninguna sección con
contenido, `exportar_a_pdf` rechaza la exportación explícitamente
(`DocumentoInsuficienteError`) en vez de producir un PDF vacío que
aparente estar completo — coherente con el criterio de aceptación
("dado un expediente **con información suficiente**").

Componentes públicos:
    - :class:`pdf_export.DocumentoExportable`, :class:`pdf_export.SeccionDocumento`,
      :class:`pdf_export.BloqueTexto`, :class:`pdf_export.BloqueTabla`
    - :class:`pdf_export.ResultadoExportacionPDF`
    - :func:`pdf_export.exportar_a_pdf`
    - :func:`adaptadores.resumen_caso_a_documento_exportable`
    - :func:`adaptadores.expediente_completo_a_documento_exportable`
"""

from documentos_clinicos.pdf_export import (
    BloqueTabla,
    BloqueTexto,
    DocumentoExportable,
    DocumentoInsuficienteError,
    ResultadoExportacionPDF,
    SeccionDocumento,
    exportar_a_pdf,
)
from documentos_clinicos.adaptadores import (
    expediente_completo_a_documento_exportable,
    resumen_caso_a_documento_exportable,
)

__all__ = [
    "BloqueTexto",
    "BloqueTabla",
    "SeccionDocumento",
    "DocumentoExportable",
    "DocumentoInsuficienteError",
    "ResultadoExportacionPDF",
    "exportar_a_pdf",
    "resumen_caso_a_documento_exportable",
    "expediente_completo_a_documento_exportable",
]
