"""Demo end-to-end de DOC-02: exportación de expediente/resumen a PDF.

Ejecútalo con (desde la raíz del repositorio):

    python -m documentos_clinicos.demo_exportacion

No depende de OpenAI: usa ``RuleBasedSummaryLLMClient`` para el camino
del resumen de caso (igual que el demo de IA-04 cuando el modelo de
OpenAI no está disponible), porque lo que DOC-02 necesita probar es el renderizado
a PDF en sí, no la redacción del contenido — eso ya lo prueba IA-04 por
su cuenta.

Dos escenarios, uno por cada camino que permite la historia ("el resumen
del caso **o** el expediente completo"):

    - Escenario A: el resumen de caso de María (IA-04, vía
      ``resumen_caso_a_documento_exportable``) exportado a PDF.
    - Escenario B: el expediente clínico completo de María (directo desde
      ``historia_clinica_mock``, vía
      ``expediente_completo_a_documento_exportable``) exportado a PDF.

Ambos PDFs se escriben en ``./salida_demo_doc02/`` para poder abrirlos y
revisarlos manualmente.
"""

from __future__ import annotations

import os

from historia_clinica_mock.db import crear_conexion
from historia_clinica_mock.seed import sembrar_datos_sinteticos

from ia_clinica.summary.generator import CaseSummaryGenerator
from ia_clinica.summary.llm_client import RuleBasedSummaryLLMClient
from historia_clinica_mock.adapters import construir_contexto_resumen_caso

from documentos_clinicos.adaptadores import (
    expediente_completo_a_documento_exportable,
    resumen_caso_a_documento_exportable,
)
from documentos_clinicos.pdf_export import exportar_a_pdf

_DIRECTORIO_SALIDA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "salida_demo_doc02")


def main() -> None:
    conn = crear_conexion()
    ids = sembrar_datos_sinteticos(conn)
    paciente_maria = ids["paciente_maria"]

    print("=" * 70)
    print("ESCENARIO A: exportar el resumen de caso de María a PDF")
    print("=" * 70)
    contexto = construir_contexto_resumen_caso(conn, paciente_maria)
    generador = CaseSummaryGenerator(llm_client=RuleBasedSummaryLLMClient())
    resumen = generador.generate_summary(contexto)
    documento_resumen = resumen_caso_a_documento_exportable(resumen)
    ruta_resumen = os.path.join(_DIRECTORIO_SALIDA, "resumen_caso_maria.pdf")
    resultado_a = exportar_a_pdf(documento_resumen, ruta_resumen)
    print(f"PDF generado: {resultado_a.ruta} ({resultado_a.bytes_escritos} bytes)")
    assert resultado_a.bytes_escritos > 0

    print()
    print("=" * 70)
    print("ESCENARIO B: exportar el expediente clínico completo de María a PDF")
    print("=" * 70)
    documento_expediente = expediente_completo_a_documento_exportable(conn, paciente_maria)
    ruta_expediente = os.path.join(_DIRECTORIO_SALIDA, "expediente_completo_maria.pdf")
    resultado_b = exportar_a_pdf(documento_expediente, ruta_expediente)
    print(f"PDF generado: {resultado_b.ruta} ({resultado_b.bytes_escritos} bytes)")
    assert resultado_b.bytes_escritos > 0

    conn.close()


if __name__ == "__main__":
    main()
