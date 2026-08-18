"""Demo manual de IA-02: genera un borrador de nota a partir de una consulta de ejemplo.

Ejecútalo con:

    python ia_clinica/notes/demo.py

No requiere ninguna llave de API: usa el cliente de referencia
(RuleBasedLLMClient) para que se pueda probar el flujo completo sin
conexión a un proveedor de LLM real.
"""

from ia_clinica.notes.generator import ClinicalNoteGenerator
from ia_clinica.notes.llm_client import RuleBasedLLMClient
from ia_clinica.notes.models import ClinicalContext, SourceSpan

PARRAFO_CONSULTA = (
    "Paciente de 45 años que refiere dolor óseo progresivo de tres semanas. "
    "Al examen físico se palpa adenopatía axilar izquierda de 2 cm. "
    "Impresión diagnóstica: progresión de enfermedad ósea metastásica. "
    "Plan: se solicita gammagrafía ósea y control en dos semanas."
)


def demo_parrafo_unico() -> None:
    """Muestra que también funciona pegando la consulta como un solo párrafo.

    ClinicalContext.from_text separa el texto en oraciones automáticamente
    antes de pasarlo al generador, así no es necesario entregar la
    información ya fragmentada a mano.
    """
    print("=" * 70)
    print("DEMO 2: consulta entregada como un solo párrafo (ClinicalContext.from_text)")
    print("=" * 70)
    context = ClinicalContext.from_text(consult_id="demo-002", patient_ref="paciente-demo-2", text=PARRAFO_CONSULTA)
    generator = ClinicalNoteGenerator(llm_client=RuleBasedLLMClient())
    draft = generator.generate_draft(context, format_name="SOAP")
    print(draft.to_text())


def demo_fragmentos_manuales() -> None:
    # Esto simula la información "registrada durante la consulta" ya
    # separada por fragmento (por ejemplo, una transcripción con
    # marcas de turno, o campos ya capturados por otra pantalla). En un
    # flujo real este contexto lo construiría la captura de la consulta
    # (fuera del alcance de IA-02), no un script de demo.
    print("=" * 70)
    print("DEMO 1: consulta entregada como fragmentos ya separados")
    print("=" * 70)
    context = ClinicalContext(
        consult_id="demo-001",
        patient_ref="paciente-demo",
        segments=[
            SourceSpan(id="s1", text="La paciente refiere dolor óseo progresivo desde hace tres semanas."),
            SourceSpan(id="s2", text="Examen físico: adenopatía axilar izquierda palpable de 2 cm."),
            SourceSpan(id="s3", text="Impresión diagnóstica: progresión de enfermedad ósea metastásica."),
            # A propósito no incluimos ningún fragmento de "plan" para
            # que puedas ver cómo esa sección queda marcada como
            # faltante en vez de inventada.
        ],
    )

    generator = ClinicalNoteGenerator(llm_client=RuleBasedLLMClient())
    draft = generator.generate_draft(context, format_name="SOAP")

    print(draft.to_text())
    print("¿Es un borrador de IA?:", draft.is_ai_generated_draft)
    print("Trazabilidad (sección -> fragmentos de la consulta usados):")
    for key, span_ids in draft.traceability.items():
        print(f"  {key}: {span_ids}")
    print()


def main() -> None:
    demo_fragmentos_manuales()
    demo_parrafo_unico()


if __name__ == "__main__":
    main()
