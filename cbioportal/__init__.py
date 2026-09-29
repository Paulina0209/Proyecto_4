"""Base de datos real del copiloto a partir de cBioPortal.

Importa pacientes reales (desidentificados) de estudios públicos de
cBioPortal —por defecto MSK-CHORD (``msk_chord_2024``), que trae línea de
tiempo clínica, biomarcadores, marcadores tumorales, tratamientos y
hallazgos de imagen— al mismo expediente SQLite que ya leen DX, EST, TX,
IA y HC-05 (esquema de ``historia_clinica_mock`` + ``historia_clinica``).

La carga reutiliza HC-01 (``historia_clinica.integracion_externa``):
cBioPortal es una fuente externa más, con verificación de identidad,
transacción todo-o-nada, idempotencia y trazabilidad por registro.

Componentes:
    - ``cliente``: cliente HTTP de la API de cBioPortal.
    - ``mapeo``: traducción pura de la respuesta a filas del expediente
      (reglas clínicas fail-closed documentadas en el módulo).
    - ``importador``: ``FuenteCBioPortal`` e importación por paciente o
      por estudio.
    - ``modulo_pacientes``: volcado en la base de ``patients`` para que
      los pacientes aparezcan en la búsqueda (PAC-02) y el 360 (PAC-03).
    - ``indice``: índice de un estudio completo (datos básicos, en
      segundos) y carga del detalle de cada paciente al abrirlo.

Uso: ``python -m cbioportal --help``. Documentación: ``docs/cbioportal.md``.
"""

from .cliente import URL_PUBLICA, ClienteCBioPortal
from .importador import (
    ESTUDIO_POR_DEFECTO,
    FuenteCBioPortal,
    ResultadoImportacion,
    importar_estudio,
    importar_paciente,
    seleccionar_pacientes,
)
from .indice import CargadorDetalle, ResultadoIndice, importar_indice
from .mapeo import FORMATO_CBIOPORTAL, identificacion_cbioportal
from .modulo_pacientes import volcar_en_modulo_pacientes

__all__ = [
    "CargadorDetalle",
    "ClienteCBioPortal",
    "ResultadoIndice",
    "importar_indice",
    "ESTUDIO_POR_DEFECTO",
    "FORMATO_CBIOPORTAL",
    "FuenteCBioPortal",
    "ResultadoImportacion",
    "URL_PUBLICA",
    "identificacion_cbioportal",
    "importar_estudio",
    "importar_paciente",
    "seleccionar_pacientes",
    "volcar_en_modulo_pacientes",
]
