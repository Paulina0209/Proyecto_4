"""Expediente clínico oncológico (esquema SQLite y lecturas).

Es la base que leen DX, EST, TX, IA, HC-05 y DOC. Los datos reales llegan
desde cBioPortal (``python -m cbioportal``, camino de HC-01) a
``data/copiloto.db``; ver ``historia_clinica.db.conectar_expediente`` y
docs/cbioportal.md. Este paquete no trae datos: los datos sintéticos que
usan las pruebas automáticas viven en ``tests/datos_sinteticos.py``.

Tablas: pacientes, consultas, laboratorios, imagenología, biomarcadores,
datos clínicos estructurados y comorbilidades.

Componentes:
    - ``db``: creación de la conexión y del esquema.
    - ``repository``: consultas de lectura.
    - ``adapters``: construye los contextos de IA (IA-02, IA-04) y los
      hallazgos de DX-02, con trazabilidad hasta la fila exacta.
"""
