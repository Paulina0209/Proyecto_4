from clinical_query import MockSQLiteClinicalRepository, NaturalLanguageClinicalQueryService
from historia_clinica_mock.db import crear_conexion
from historia_clinica_mock.repository import listar_pacientes
from historia_clinica_mock.seed import sembrar_datos_sinteticos


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
        choice = input("\nSeleccione paciente por ID > " ).strip()
        try:
            patient_id = int(choice)
        except ValueError:
            print("Ingrese un ID numérico válido.")
            continue

        if any(p.id == patient_id for p in pacientes):
            return patient_id
        print("Ese paciente no existe en el mock.")


def main() -> None:
    conn = crear_conexion()
    sembrar_datos_sinteticos(conn)

    repository = MockSQLiteClinicalRepository(conn)
    service = NaturalLanguageClinicalQueryService(repository)

    print("=" * 72)
    print("IA-01 — CONSULTA DE DATOS CLÍNICOS EN LENGUAJE NATURAL")
    print("Fuente: historia_clinica_mock (SQLite, datos 100% sintéticos)")
    print("=" * 72)

    patient_id = seleccionar_paciente(conn)
    paciente = next(p for p in listar_pacientes(conn) if p.id == patient_id)
    print(f"\nPaciente activo: {paciente.nombre} [ID interno: {patient_id}]")
    print("Escribe 'cambiar' para seleccionar otro paciente o 'salir' para terminar.")

    while True:
        question = input("\nOncólogo > " ).strip()
        command = question.casefold()
        if command in {"salir", "exit", "quit"}:
            break
        if command == "cambiar":
            patient_id = seleccionar_paciente(conn)
            paciente = next(p for p in listar_pacientes(conn) if p.id == patient_id)
            print(f"Paciente activo: {paciente.nombre} [ID interno: {patient_id}]")
            continue
        if not question:
            continue

        response = service.ask(str(patient_id), question)
        print(f"Asistente > {response.answer}")

    conn.close()


if __name__ == "__main__":
    main()
