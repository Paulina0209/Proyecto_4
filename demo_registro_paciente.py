"""
Demo interactivo de registro de pacientes (HC-01).

Formulario corto por consola, pensado para probar los tres criterios
de aceptación de la historia: registro exitoso, validación de campos
obligatorios y alerta de posible duplicado.

Ejecutar: python demo_registro_paciente.py
"""
from __future__ import annotations

import sqlite3

from patients.models import (
    Paciente,
    Sexo,
    TipoIdentificacion,
    DatosContacto,
    AntecedentesMedicos,
)
from patients.registro import registrar_paciente, generar_identificador_temporal
from patients.repository import inicializar_schema


def pedir(msg: str, obligatorio: bool = False) -> str:
    while True:
        valor = input(msg).strip()
        if valor or not obligatorio:
            return valor
        print("  (este dato es obligatorio para continuar)")


def elegir_enum(msg: str, enum_cls):
    opciones = list(enum_cls)
    print(msg)
    for i, op in enumerate(opciones, 1):
        print(f"  {i}. {op.value}")
    while True:
        try:
            idx = int(input("Opción: ")) - 1
            if 0 <= idx < len(opciones):
                return opciones[idx]
        except ValueError:
            pass
        print("  Opción inválida, intente de nuevo.")


def construir_paciente_desde_formulario() -> Paciente:
    nombre = pedir("Nombre completo: ")
    sexo = elegir_enum("Sexo:", Sexo)
    tipo_id = elegir_enum("Tipo de identificación:", TipoIdentificacion)

    if tipo_id == TipoIdentificacion.TEMPORAL:
        numero_id = generar_identificador_temporal()
        print(f"  Identificador temporal generado: {numero_id}")
    else:
        numero_id = pedir("Número de identificación: ")

    telefono = pedir("Teléfono (Enter para omitir si va a dar email): ")
    email = pedir("Email (Enter para omitir si dio teléfono): ")

    completar_ahora = pedir(
        "¿Completar antecedentes y motivo de consulta ahora? (s/n): "
    ).lower() == "s"

    antecedentes = AntecedentesMedicos()
    motivo = None
    if completar_ahora:
        antecedentes.personales = pedir("Antecedentes personales: ")
        antecedentes.familiares = pedir("Antecedentes familiares: ")
        motivo = pedir("Motivo de consulta inicial: ")
    else:
        print("  (se guardará el registro corto; podrá completarse después)")

    return Paciente(
        nombre_completo=nombre,
        fecha_nacimiento=None,
        sexo=sexo,
        tipo_identificacion=tipo_id,
        numero_identificacion=numero_id,
        contacto=DatosContacto(telefono=telefono or None, email=email or None),
        oncologo_id=1,  # oncólogo autenticado simulado
        antecedentes=antecedentes,
        motivo_consulta_inicial=motivo,
    )


def main() -> None:
    conn = sqlite3.connect("pacientes_demo.db")
    conn.row_factory = sqlite3.Row
    inicializar_schema(conn)

    print("=== Registro de paciente (HC-01) — formulario corto ===\n")

    while True:
        paciente = construir_paciente_desde_formulario()
        resultado = registrar_paciente(conn, paciente)

        if resultado.exito:
            print(f"\n✔ Paciente registrado con id {resultado.paciente.id}.\n")
            break

        if resultado.posible_duplicado:
            p = resultado.posible_duplicado
            print(
                f"\n⚠ Posible duplicado: ya existe un paciente con esta identificación "
                f"(id {p.id}, {p.nombre_completo}, registrado con oncólogo {p.oncologo_id})."
            )
            print("  No se creó el registro. Si fue un error de tipeo, corrija el número")
            print("  de identificación; si es el mismo paciente, use su registro existente.\n")
        else:
            print("\n✘ No se pudo guardar el registro. Faltan campos:")
            for err in resultado.errores:
                print(f"  - {err.campo}: {err.mensaje}")
            print()

        de_nuevo = pedir("¿Intentar de nuevo? (s/n): ").lower() == "s"
        if not de_nuevo:
            break

    conn.close()


if __name__ == "__main__":
    main()
