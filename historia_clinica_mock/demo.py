"""Demo end-to-end: base de datos mock -> ClinicalContext -> borrador de nota (IA-02).

Ejecútalo con:

    python -m historia_clinica_mock.demo

No requiere ninguna llave de API (usa RuleBasedLLMClient, el cliente de
referencia sin proveedor externo).
"""

from ia_clinica.notes.generator import ClinicalNoteGenerator
from ia_clinica.notes.llm_client import RuleBasedLLMClient

from historia_clinica_mock.adapters import construir_contexto_clinico
from historia_clinica_mock.db import crear_conexion
from historia_clinica_mock.seed import sembrar_datos_sinteticos


def _mostrar_borrador(titulo: str, conn, consulta_id: int) -> None:
    print("=" * 70)
    print(titulo)
    print("=" * 70)

    context = construir_contexto_clinico(conn, consulta_id)
    print(f"Fragmentos disponibles para esta consulta ({len(context.segments)}):")
    for segment in context.segments:
        print(f"  [{segment.origin}] {segment.id}: {segment.text}")
    print()

    generator = ClinicalNoteGenerator(llm_client=RuleBasedLLMClient())
    draft = generator.generate_draft(context)
    print(draft.to_text())
    print("Trazabilidad hasta la fila exacta de la base de datos:")
    for key, span_ids in draft.traceability.items():
        print(f"  {key}: {span_ids}")
    print()


def main() -> None:
    conn = crear_conexion()  # base de datos SQLite en memoria
    ids = sembrar_datos_sinteticos(conn)

    _mostrar_borrador(
        "DEMO A: consulta con laboratorio, imagenología y biomarcador vinculados",
        conn,
        ids["consulta_maria_1"],
    )
    _mostrar_borrador(
        "DEMO B: consulta de seguimiento SIN laboratorio/imagen vinculados "
        "(deben quedar marcados como faltantes, no inventados)",
        conn,
        ids["consulta_maria_2"],
    )
    _mostrar_borrador(
        "DEMO C: paciente distinto (NSCLC metastásico), con biomarcador EGFR",
        conn,
        ids["consulta_carlos_1"],
    )

    conn.close()


if __name__ == "__main__":
    main()
