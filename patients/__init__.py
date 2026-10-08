"""Módulo de pacientes.

Historias de usuario (un archivo por historia):
    registro.py       HC-01  Registro de paciente
    busqueda.py       PAC-02 Búsqueda y filtros (+ diagnósticos, tratamientos, consultas)
    resumen_360.py    PAC-03 Resumen 360 del paciente (+ alertas de HC-02 y
                      biomarcadores clave de HC-04 tomados del expediente)

Compartido:
    models.py         Modelos de dominio de las tres historias
    db/               Única base de datos: schema.sql y la conexión (sin datos de ejemplo)
    api.py            API HTTP (uvicorn patients.api:app)
    schemas.py        Esquemas de entrada/salida de la API
    demo.py           Cliente de consola (python -m patients.demo)
    expediente.py     Puente con el expediente clínico (HC-02, HC-04)

Documentación: docs/pacientes.md y docs/PACIENTES_DEMO.md.

Usados desde fuera del módulo:
    medicacion_actual.py    tx_clinica (chequeo de interacciones)
"""
