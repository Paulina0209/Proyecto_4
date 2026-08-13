import pytest

from ia_clinica.notes.models import ClinicalContext, SourceSpan


@pytest.fixture
def consult_context() -> ClinicalContext:
    return ClinicalContext(
        consult_id="consulta-001",
        patient_ref="paciente-123",
        segments=[
            SourceSpan(id="seg-1", text="La paciente refiere dolor óseo progresivo desde hace tres semanas."),
            SourceSpan(id="seg-2", text="Examen físico: adenopatía axilar izquierda palpable de 2 cm."),
            SourceSpan(id="seg-3", text="Impresión diagnóstica: progresión de enfermedad ósea metastásica."),
            SourceSpan(id="seg-4", text="Plan: se solicita gammagrafía ósea y control en dos semanas."),
        ],
    )
