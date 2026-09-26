from __future__ import annotations

from datetime import date, datetime

import requests

from .models import Sexo, TipoIdentificacion


BASE_URL = "http://localhost:8000"


def pedir(msg: str, obligatorio: bool = False) -> str:
    while True:
        valor = input(msg).strip()

        if valor or not obligatorio:
            return valor

        print("  (este dato es obligatorio para continuar)")


def pedir_fecha_nacimiento() -> str:
    """Solicita y valida la fecha de nacimiento."""

    while True:
        valor = input(
            "Fecha de nacimiento (YYYY-MM-DD): "
        ).strip()

        if not valor:
            print(
                "  (la fecha de nacimiento es obligatoria para continuar)"
            )
            continue

        try:
            fecha = datetime.strptime(
                valor,
                "%Y-%m-%d"
            ).date()

        except ValueError:
            print(
                "  Fecha inválida. Use el formato YYYY-MM-DD."
            )
            continue

        if fecha > date.today():
            print(
                "  La fecha de nacimiento no puede ser futura."
            )
            continue

        return valor


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


def construir_paciente_desde_formulario() -> dict:
    nombre = pedir(
        "Nombre completo: ",
        obligatorio=True,
    )

    fecha_nacimiento = pedir_fecha_nacimiento()

    sexo = elegir_enum(
        "Sexo:",
        Sexo,
    )

    tipo_id = elegir_enum(
        "Tipo de identificación:",
        TipoIdentificacion,
    )

    if tipo_id == TipoIdentificacion.TEMPORAL:
        # D5: antes se pedía un identificador temporal a
        # GET /identificadores-temporales/nuevo, un endpoint que no
        # existe en api.py -- esto siempre terminaba en un 404. El
        # servidor YA genera el identificador solo (crear_paciente, en
        # api.py) cuando numero_identificacion llega vacío, así que
        # basta con no mandar nada y dejar que la API lo resuelva.
        numero_id = None
        print(
            "  (el identificador temporal lo genera el servidor al registrar)"
        )

    else:
        numero_id = pedir(
            "Número de identificación: ",
            obligatorio=True,
        )

    telefono = pedir(
        "Teléfono (Enter para omitir si va a dar email): "
    )

    email = pedir(
        "Email (Enter para omitir si dio teléfono): "
    )

    completar_ahora = (
        pedir(
            "¿Completar antecedentes y motivo de consulta ahora? "
            "(s/n): "
        ).lower()
        == "s"
    )

    antecedentes_personales = None
    antecedentes_familiares = None
    motivo = None

    if completar_ahora:

        antecedentes_personales = pedir(
            "Antecedentes personales: "
        )

        antecedentes_familiares = pedir(
            "Antecedentes familiares: "
        )

        motivo = pedir(
            "Motivo de consulta inicial: "
        )

    else:
        print(
            "  (se guardará el registro corto; "
            "podrá completarse después)"
        )

    paciente = {
        "nombre_completo": nombre,
        "fecha_nacimiento": fecha_nacimiento,
        "sexo": sexo.value,
        "tipo_identificacion": tipo_id.value,
        "numero_identificacion": numero_id,
        "contacto": {
            "telefono": telefono or None,
            "email": email or None,
        },
        "oncologo_id": 1,
        "antecedentes": {
            "personales": antecedentes_personales,
            "familiares": antecedentes_familiares,
        },
        "motivo_consulta_inicial": motivo,
    }

    return paciente


def registrar_paciente_api(paciente: dict):
    """
    Registra el paciente llamando directamente a POST /pacientes.
    """

    try:
        response = requests.post(
            f"{BASE_URL}/pacientes",
            json=paciente,
            timeout=10,
        )

    except requests.ConnectionError:
        print(
            "\n✘ No se pudo conectar con la API."
        )
        print(
            f"  Verifique que el backend esté corriendo en "
            f"{BASE_URL}"
        )
        return None

    except requests.RequestException as e:
        print(
            f"\n✘ Error realizando la petición: {e}"
        )
        return None

    if response.status_code in (200, 201):

        return {
            "exito": True,
            "data": response.json(),
        }

    if response.status_code == 409:

        try:
            data = response.json()
        except ValueError:
            data = {}

        return {
            "exito": False,
            "posible_duplicado": data,
        }

    if response.status_code == 422:

        try:
            data = response.json()
        except ValueError:
            data = {}

        return {
            "exito": False,
            "errores": data,
        }

    try:
        data = response.json()
    except ValueError:
        data = response.text

    return {
        "exito": False,
        "error": data,
        "status_code": response.status_code,
    }


def mostrar_error(resultado: dict):
    print("\n✘ No se pudo registrar el paciente.")

    if "errores" in resultado:
        print("Errores de validación:")

        errores = resultado["errores"]

        if isinstance(errores, dict):
            print(f"  {errores}")

        else:
            for error in errores:
                print(f"  - {error}")

    elif "error" in resultado:
        print(f"  {resultado['error']}")

    print()


def main() -> None:

    print(
        "=== Registro de paciente (HC-01) "
        "— cliente de la API ===\n"
    )

    print(f"API: {BASE_URL}\n")

    while True:

        try:
            paciente = construir_paciente_desde_formulario()

        except RuntimeError as e:
            print(f"\n✘ {e}\n")
            break

        print("\nEnviando paciente a la API...")

        resultado = registrar_paciente_api(paciente)

        if resultado is None:
            break

        if resultado["exito"]:

            data = resultado["data"]

            paciente_id = data.get(
                "id",
                data.get("paciente_id", "desconocido"),
            )

            print(
                f"\n✔ Paciente registrado mediante la API "
                f"con id {paciente_id}.\n"
            )

            numero_asignado = data.get("numero_identificacion")
            if numero_asignado:
                print(f"  Número de identificación: {numero_asignado}\n")

            break

        if "posible_duplicado" in resultado:

            print(
                "\n⚠ Posible duplicado: "
                "la API indicó que el paciente ya existe."
            )

            print(
                f"  Información: "
                f"{resultado['posible_duplicado']}"
            )

        else:
            mostrar_error(resultado)

        de_nuevo = (
            pedir("¿Intentar de nuevo? (s/n): ")
            .lower()
            == "s"
        )

        if not de_nuevo:
            break


if __name__ == "__main__":
    main()