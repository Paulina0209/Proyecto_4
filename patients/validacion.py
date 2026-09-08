from __future__ import annotations

from .models import Paciente, ErrorValidacion


def validar_campos_obligatorios(paciente: Paciente) -> list:
    errores: list = []

    if not paciente.nombre_completo or not paciente.nombre_completo.strip():
        errores.append(ErrorValidacion("nombre_completo", "El nombre completo es obligatorio."))

    if paciente.sexo is None:
        errores.append(ErrorValidacion("sexo", "El sexo es obligatorio."))

    if paciente.tipo_identificacion is None:
        errores.append(ErrorValidacion("tipo_identificacion", "El tipo de identificación es obligatorio."))
    elif not paciente.numero_identificacion or not paciente.numero_identificacion.strip():
        errores.append(ErrorValidacion(
            "numero_identificacion",
            "El número de identificación es obligatorio "
            "(use un identificador temporal si el paciente no tiene documento).",
        ))

    if not paciente.contacto or not paciente.contacto.tiene_al_menos_un_dato():
        errores.append(ErrorValidacion("contacto", "Debe registrar al menos un teléfono o email de contacto."))

    if not paciente.oncologo_id:
        errores.append(ErrorValidacion("oncologo_id", "No hay un oncólogo autenticado para asociar el registro."))

    return errores
