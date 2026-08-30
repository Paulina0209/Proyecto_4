from datetime import datetime, timezone

import pytest

from ia_clinica.notes.models import ClinicalNoteDraft, NoteSectionDraft
from ia_clinica.review import store


@pytest.fixture
def conn():
    connection = store.crear_conexion(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def borrador_ia() -> ClinicalNoteDraft:
    """Un ClinicalNoteDraft de ejemplo, como el que produciría IA-02."""

    return ClinicalNoteDraft(
        consult_id="consulta-100",
        patient_ref="paciente-1",
        format_name="SOAP",
        generated_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        sections=[
            NoteSectionDraft(
                key="S",
                label="Subjetivo",
                content="La paciente refiere dolor óseo progresivo.",
                status="documented",
                source_span_ids=["seg-1"],
            ),
            NoteSectionDraft(
                key="A",
                label="Análisis",
                content="Impresión diagnóstica: progresión de enfermedad ósea.",
                status="documented",
                source_span_ids=["seg-2"],
            ),
            NoteSectionDraft(
                key="P",
                label="Plan",
                content="Información no disponible en el contexto clínico proporcionado.",
                status="missing",
                source_span_ids=[],
            ),
        ],
        traceability={"S": ["seg-1"], "A": ["seg-2"], "P": []},
        warnings=[],
    )
