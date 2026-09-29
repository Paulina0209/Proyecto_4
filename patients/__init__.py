"""Módulo de pacientes.

Historias de usuario (un archivo por historia):
    registro.py       HC-01  Registro de paciente
    busqueda.py       PAC-02 Búsqueda y filtros (+ diagnósticos, tratamientos, consultas)
    resumen_360.py    PAC-03 Resumen 360 del paciente

Compartido:
    models.py         Modelos de dominio de las tres historias
    db/               Única base de datos: schema.sql, datos_prueba.sql y la conexión
    api.py            API HTTP (uvicorn patients.api:app)
    schemas.py        Esquemas de entrada/salida de la API
    demo.py           Cliente de consola (python -m patients.demo)
    cbioportal.py     Importa pacientes reales desidentificados de cBioPortal
                      a la misma base (python -m patients.cbioportal)

Usados desde fuera del módulo:
    medicacion_actual.py    tx_clinica (chequeo de interacciones)
    paciente_de_prueba.sql  demo_tx.py (datos de historia_clinica_mock)
"""
