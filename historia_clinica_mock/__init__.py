"""Base de datos mock de historia clínica oncológica.

Este paquete **no** implementa las historias HC-01 a HC-06 del backlog
(integración real con sistemas externos, laboratorios, PACS/DICOM,
biomarcadores). Es, a propósito, mucho más simple: una base de datos
SQLite pequeña con datos sintéticos, pensada para poder probar `ia_clinica`
(en particular IA-02) contra algo más parecido a un historial real que
construir un `ClinicalContext` a mano en cada prueba.

Cubre tres aspectos de una historia clínica oncológica, como se pidió:

    - pacientes y sus consultas (la parte de "consultas"),
    - laboratorios,
    - imagenología diagnóstica (como texto de hallazgos/reporte, no DICOM),

y además un cuarto aspecto oncológico relevante que se agregó por
completitud: biomarcadores/patología (HER2, EGFR, PD-L1, etc.), porque son
centrales para historias clínicas de oncología y ya estaban en el radar
del backlog (HC-04).

Ningún dato aquí es real: son pacientes y resultados sintéticos, igual que
los "casos sintéticos" que ya usa este repositorio en `tests/guidelines`.

Componentes:
    - ``db``: creación de la conexión y del esquema.
    - ``seed``: datos sintéticos de ejemplo.
    - ``repository``: consultas de lectura sobre la base de datos.
    - ``adapters``: construye un ``ia_clinica.notes.ClinicalContext`` a
      partir de una consulta guardada en la base de datos, con
      trazabilidad hasta la fila exacta (paciente, consulta, laboratorio,
      imagen o biomarcador) que originó cada fragmento.
"""
