"""Demo ejecutable de IA-05 sobre DX-02 + historia_clinica_mock + guidelines."""

from dx_clinica.builder import construir_diagnosticos_diferenciales
from historia_clinica_mock.adapters import obtener_hallazgos_de_paciente
from historia_clinica_mock.db import crear_conexion
from historia_clinica_mock.repository import obtener_paciente
from historia_clinica_mock.seed import sembrar_datos_sinteticos
from ia_clinica.explainability import ExplanationService


def _mostrar_explicacion(explicacion) -> None:
    print(f"Recomendación: {explicacion.recommendation}")
    print(f"Componente origen: {explicacion.source_component}")
    print(f"Nivel de confianza: {explicacion.confidence.value} (cualitativo, no probabilístico)")
    print(f"Razonamiento: {explicacion.rationale}")
    print("\nDatos del paciente utilizados:")
    if explicacion.patient_facts:
        for fact in explicacion.patient_facts:
            print(f"  - [{fact.fact_id}] {fact.value} | origen={fact.source_type} | fecha={fact.date}")
    else:
        print("  - Ningún dato trazable disponible.")

    print("\nEvidencia:")
    if explicacion.evidence:
        ev = explicacion.evidence
        print(f"  - {ev.organization} — {ev.title} ({ev.publication_year or 's/f'})")
        print(f"    DOI: {ev.doi or 'no registrado'}")
        print(f"    Módulo: {ev.module_id}")
        print(f"    Estado de validación clínica: {ev.validation_status or 'no especificado'}")
        print(f"    Fuente versionada: {ev.source_path}")
    else:
        print("  - No hay fuente de evidencia registrada para esta recomendación.")

    print("\nDatos/criterios faltantes:")
    if explicacion.missing_data:
        for item in explicacion.missing_data:
            print(f"  - {item}")
    else:
        print("  - Ninguno identificado.")

    print("\nLimitaciones / incertidumbre:")
    if explicacion.limitations:
        for item in explicacion.limitations:
            print(f"  - {item}")
    else:
        print("  - Sin limitaciones adicionales registradas.")


def main() -> None:
    conn = crear_conexion()
    ids = sembrar_datos_sinteticos(conn)
    service = ExplanationService()

    print("=" * 78)
    print("IA-05 — EXPLICABILIDAD DE RECOMENDACIONES")
    print("Datos sintéticos; la confianza NO es una probabilidad clínica.")
    print("=" * 78)

    # Caso 1: candidato con datos trazables y una guía versionada.
    paciente = obtener_paciente(conn, ids["paciente_maria"])
    hallazgos = obtener_hallazgos_de_paciente(conn, paciente.id)
    resultado = construir_diagnosticos_diferenciales(paciente, hallazgos)
    candidato = resultado.candidatos[0]

    print(f"\nPACIENTE: {paciente.nombre}")
    _mostrar_explicacion(service.explain_differential_candidate(candidato, hallazgos))

    # Caso 2: candidato que tiene sustento en el expediente, pero no una
    # guía asociada. Debe declarar la insuficiencia y NO dar falsa confianza.
    paciente = obtener_paciente(conn, ids["paciente_carlos"])
    hallazgos = obtener_hallazgos_de_paciente(conn, paciente.id)
    resultado = construir_diagnosticos_diferenciales(paciente, hallazgos)
    candidato_sin_evidencia = next(
        c for c in resultado.candidatos if c.perfil_id == "proceso_infeccioso_respiratorio"
    )

    print("\n" + "-" * 78)
    print(f"PACIENTE: {paciente.nombre}")
    _mostrar_explicacion(service.explain_differential_candidate(candidato_sin_evidencia, hallazgos))

    conn.close()


if __name__ == "__main__":
    main()
