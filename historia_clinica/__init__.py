"""Épica Historia Clínica: integración y completitud del expediente.

    - ``integracion_externa``: HC-01 — historia clínica externa (FHIR R4,
      HL7 v2 ORU^R01 o PDF vía DOC-01).
    - ``informacion_faltante``: HC-05 — qué información falta para
      diagnosticar, estadificar o tratar, según un checklist configurable
      por tipo de cáncer.

Trabaja sobre la misma base de datos que ``expediente``
(``db.crear_conexion`` aplica ambos esquemas), así que lo integrado aquí
queda disponible para DX, EST, TX e IA sin adaptadores adicionales.
"""
