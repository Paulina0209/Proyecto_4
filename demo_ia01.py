"""Demo unificada de IA-01 + IA-05 sobre el paciente activo.

Comandos:
- ``recomendaciones``: muestra únicamente recomendaciones del paciente activo,
  cada una con datos usados, evidencia, confianza y limitaciones.
- ``cambiar``: cambia de paciente sin mezclar expedientes.
- ``salir``: termina la demo.
"""

from clinical_query import MockSQLiteClinicalRepository, NaturalLanguageClinicalQueryService
from historia_clinica_mock.adapters import obtener_hallazgos_de_paciente
from historia_clinica_mock.db import crear_conexion
from historia_clinica_mock.repository import listar_pacientes
from historia_clinica_mock.seed import sembrar_datos_sinteticos
from ia_clinica.explainability import PatientRecommendationService


def seleccionar_paciente(conn) -> int:
    pacientes = listar_pacientes(conn)

    print("\nPacientes sintéticos disponibles:")
    for paciente in pacientes:
        print(
            f"  {paciente.id}. {paciente.nombre} | "
            f"{paciente.diagnostico_principal or 'Sin diagnóstico'} | "
            f"Estadio {paciente.estadio or 'N/D'}"
        )

    while True:
        choice = input("\nSeleccione paciente por ID > ").strip()
        try:
            patient_id = int(choice)
        except ValueError:
            print("Ingrese un ID numérico válido.")
            continue

        if any(p.id == patient_id for p in pacientes):
            return patient_id
        print("Ese paciente no existe en el mock.")


def obtener_paciente_activo(conn, patient_id: int):
    return next(p for p in listar_pacientes(conn) if p.id == patient_id)


def mostrar_trazabilidad_consulta(patient_id: int, response) -> None:
    """Hace visible de dónde salió la respuesta de IA-01."""
    print("\n  Trazabilidad:")
    print(f"  - Paciente interno consultado: {patient_id}")
    print("  - Repositorio: historia_clinica_mock (SQLite sintético)")

    if response.datum is not None:
        print(f"  - Concepto recuperado: {response.concept}")
        print(f"  - Registro fuente: {response.datum.source}")
        print(f"  - ID exacto de origen: {response.datum.source_id}")
        print(f"  - Fecha del dato: {response.datum.observed_at.strftime('%Y-%m-%d')}")
    elif response.concept is not None:
        print(f"  - Concepto buscado: {response.concept}")
        print("  - Resultado de recuperación: 0 registros para este paciente")
    else:
        print("  - No se ejecutó recuperación clínica porque la consulta no pudo interpretarse con seguridad.")


def mostrar_explicacion(explicacion, index: int) -> None:
    print("\n" + "-" * 78)
    print(f"RECOMENDACIÓN {index}")
    print("-" * 78)
    print(explicacion.recommendation)
    print(f"Origen: {explicacion.source_component}")
    print(f"Confianza: {explicacion.confidence.value} (cualitativa, no probabilística)")
    print(f"Por qué: {explicacion.rationale}")

    print("\nDatos de ESTE paciente utilizados:")
    if explicacion.patient_facts:
        for fact in explicacion.patient_facts:
            print(f"  - [{fact.fact_id}] {fact.value}")
            print(f"    origen={fact.source_type} | fecha={fact.date}")
    else:
        print("  - Ningún dato trazable disponible.")

    print("\nEvidencia / guía:")
    if explicacion.evidence:
        ev = explicacion.evidence
        print(f"  - {ev.organization} — {ev.title} ({ev.publication_year or 's/f'})")
        print(f"    DOI: {ev.doi or 'no registrado'}")
        print(f"    Módulo: {ev.module_id}")
        print(f"    Estado de validación clínica: {ev.validation_status or 'no especificado'}")
        print(f"    Fuente versionada: {ev.source_path}")
    else:
        print("  - No hay una guía o fuente de evidencia registrada para esta recomendación.")

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


def mostrar_recomendaciones(conn, paciente, recommendation_service) -> None:
    hallazgos = obtener_hallazgos_de_paciente(conn, paciente.id)
    result = recommendation_service.for_patient(paciente, hallazgos)

    print("\n" + "=" * 78)
    print(f"RECOMENDACIONES EXPLICABLES — {paciente.nombre}")
    print(f"Paciente interno: {paciente.id}")
    print("Fuente clínica: exclusivamente el expediente activo en historia_clinica_mock")
    print("=" * 78)

    if result.warning:
        print(f"\nAdvertencia: {result.warning}")

    if not result.explanations:
        print("\nNo hay recomendaciones con sustento clínico disponible para este paciente.")
        return

    for index, explanation in enumerate(result.explanations, start=1):
        mostrar_explicacion(explanation, index)


def main() -> None:
    conn = crear_conexion()
    sembrar_datos_sinteticos(conn)

    repository = MockSQLiteClinicalRepository(conn)
    query_service = NaturalLanguageClinicalQueryService(repository)
    recommendation_service = PatientRecommendationService()

    print("=" * 78)
    print("COPILOTO CLÍNICO — DEMO UNIFICADA IA-01 + IA-05")
    print("Fuente: historia_clinica_mock (SQLite, datos 100% sintéticos)")
    print("=" * 78)

    patient_id = seleccionar_paciente(conn)
    paciente = obtener_paciente_activo(conn, patient_id)
    print(f"\nPaciente activo: {paciente.nombre} [ID interno: {patient_id}]")
    print("Comandos: 'recomendaciones' | 'cambiar' | 'salir'")
    print("También puedes preguntar por un dato clínico disponible del paciente activo.")

    while True:
        question = input("\nOncólogo > ").strip()
        command = question.casefold()

        if command in {"salir", "exit", "quit"}:
            break

        if command == "cambiar":
            patient_id = seleccionar_paciente(conn)
            paciente = obtener_paciente_activo(conn, patient_id)
            print(f"\nPaciente activo: {paciente.nombre} [ID interno: {patient_id}]")
            continue

        if command in {"recomendaciones", "recomendacion", "recomendación", "recomendaciónes"}:
            mostrar_recomendaciones(conn, paciente, recommendation_service)
            continue

        if not question:
            continue

        response = query_service.ask(str(patient_id), question)
        print(f"Asistente > {response.answer}")
        mostrar_trazabilidad_consulta(patient_id, response)

    conn.close()


if __name__ == "__main__":
    main()
