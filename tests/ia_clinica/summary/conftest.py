import pytest

from ia_clinica.summary.models import CaseSummaryContext, SourceSpan


@pytest.fixture
def contexto_completo() -> CaseSummaryContext:
    """Contexto con todo lo necesario: diagnóstico, estadio y hallazgos."""

    return CaseSummaryContext(
        patient_ref="paciente-1",
        paciente_id=1,
        diagnostico_principal="Cáncer de mama triple negativo",
        estadio="II",
        segments=[
            SourceSpan(id="consulta-1-nota-1", text="La paciente recibió quimioterapia neoadyuvante.", origin="consulta"),
            SourceSpan(id="consulta-1-nota-2", text="Actualmente se siente mejor, sin dolor articular.", origin="consulta"),
            SourceSpan(id="lab-1", text="Hemograma dentro de rango.", origin="laboratorio"),
        ],
    )


@pytest.fixture
def contexto_incompleto() -> CaseSummaryContext:
    """Contexto con diagnóstico pero sin estadio ni hallazgos de tratamiento/estado."""

    return CaseSummaryContext(
        patient_ref="paciente-2",
        paciente_id=2,
        diagnostico_principal="Cáncer de ovario (sospecha inicial)",
        estadio=None,
        segments=[
            SourceSpan(
                id="consulta-2-nota-1",
                text="Paciente remitida para interconsulta oncológica inicial.",
                origin="consulta",
            ),
        ],
    )
