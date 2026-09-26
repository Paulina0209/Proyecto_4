"""Gestión documental (épica DOC del backlog).

Dos historias conviven en este paquete, cada una en su propio submódulo:

    - **DOC-01** (`carga_documentos.py`): como oncólogo, quiero cargar
      documentos clínicos (PDF, imágenes, DICOM) al expediente del
      paciente, para centralizar toda la documentación.
    - **DOC-02** (`pdf_export.py` + `adaptadores.py`): como oncólogo,
      quiero exportar un resumen o expediente en PDF, para compartirlo
      con el paciente, otro especialista o la aseguradora.

Ninguna de las dos historias genera nada a partir de la nada ni confía
ciegamente en una etiqueta: DOC-01 verifica la firma binaria real del
archivo antes de aceptar que "es" el formato que dice ser
(`carga_documentos.FORMATOS_SOPORTADOS`); DOC-02 rechaza exportar un PDF
si el documento resultante no tiene ninguna sección con contenido real
(`DocumentoInsuficienteError`) — coherente con el mismo principio de "no
aceptar una afirmación sin verificarla contra el dato real" que ya aplica
el resto del proyecto.

### DOC-01 — Carga de documentos clínicos

`carga_documentos.py` guarda el contenido binario en disco (bajo un
directorio configurable, nunca hardcodeado) y solo los metadatos —
paciente, tipo de documento, autor, fecha, ruta — en su propia tabla
SQLite de solo-inserción (mismo diseño que `dx_clinica/juicio_clinico.py`
para DX-03): el "historial de documentos" del paciente es, simplemente,
listar todas sus filas.

    - :func:`carga_documentos.cargar_documento_clinico` — valida que el
      paciente exista, que el formato esté soportado y que el contenido
      real corresponda a ese formato, y guarda el documento.
    - :func:`carga_documentos.listar_documentos_de_paciente` — el
      historial de documentos de un paciente.
    - :func:`carga_documentos.leer_contenido_documento` — lee de vuelta
      el contenido binario ya guardado.

### DOC-02 — Exportación a PDF

Este submódulo es deliberadamente independiente de qué produjo el
contenido que se exporta: `pdf_export.py` no sabe nada de `ia_clinica`,
`dx_clinica` ni `historia_clinica_mock`. Recibe un
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

Componentes públicos:
    - :class:`carga_documentos.DocumentoClinicoCargado`
    - :func:`carga_documentos.cargar_documento_clinico`
    - :func:`carga_documentos.listar_documentos_de_paciente`
    - :func:`carga_documentos.leer_contenido_documento`
    - :data:`carga_documentos.FORMATOS_SOPORTADOS`
    - :class:`pdf_export.DocumentoExportable`, :class:`pdf_export.SeccionDocumento`,
      :class:`pdf_export.BloqueTexto`, :class:`pdf_export.BloqueTabla`
    - :class:`pdf_export.ResultadoExportacionPDF`
    - :func:`pdf_export.exportar_a_pdf`
    - :func:`adaptadores.resumen_caso_a_documento_exportable`
    - :func:`adaptadores.expediente_completo_a_documento_exportable`
"""

from documentos_clinicos.carga_documentos import (
    ContenidoNoCoincideConFormatoError,
    DocumentoClinicoCargado,
    DocumentoInvalidoError,
    FormatoNoSoportadoError,
    FORMATOS_SOPORTADOS,
    cargar_documento_clinico,
    leer_contenido_documento,
    listar_documentos_de_paciente,
)
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
    "DocumentoClinicoCargado",
    "DocumentoInvalidoError",
    "FormatoNoSoportadoError",
    "ContenidoNoCoincideConFormatoError",
    "FORMATOS_SOPORTADOS",
    "cargar_documento_clinico",
    "listar_documentos_de_paciente",
    "leer_contenido_documento",
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
