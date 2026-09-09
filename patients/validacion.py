from __future__ import annotations

import re
from datetime import date

from .models import Paciente, ErrorValidacion, TipoIdentificacion

LONGITUD_MIN_NOMBRE = 3
LONGITUD_MAX_NOMBRE = 200
LONGITUD_MAX_DIRECCION = 300
LONGITUD_MAX_ANTECEDENTE = 2000
LONGITUD_MAX_MOTIVO = 1000
EDAD_MAXIMA_ANIOS = 120

REGEX_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
REGEX_TELEFONO = re.compile(r"^\+?[0-9()\-\s]{7,20}$")

# (longitud_min, longitud_max, patrón) por tipo de identificación.
# TEMPORAL se valida aparte porque su formato lo define generar_identificador_temporal().
REGLAS_IDENTIFICACION = {
    TipoIdentificacion.CEDULA: (6, 10, re.compile(r"^\d+$")),
    TipoIdentificacion.TARJETA_IDENTIDAD: (6, 11, re.compile(r"^\d+$")),
    TipoIdentificacion.REGISTRO_CIVIL: (8, 15, re.compile(r"^\d+$")),
    TipoIdentificacion.PASAPORTE: (5, 15, re.compile(r"^[A-Za-z0-9]+$")),
}


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


def validar_formato_y_longitud(paciente: Paciente) -> list:
    """Valida tipo/formato/longitud de los campos que sí vinieron con dato.
    No repite las validaciones de 'obligatorio' — esas las hace
    validar_campos_obligatorios."""
    errores: list = []

    # --- nombre_completo ---
    nombre = (paciente.nombre_completo or "").strip()
    if nombre:
        if len(nombre) < LONGITUD_MIN_NOMBRE:
            errores.append(ErrorValidacion(
                "nombre_completo", f"El nombre debe tener al menos {LONGITUD_MIN_NOMBRE} caracteres.",
            ))
        elif len(nombre) > LONGITUD_MAX_NOMBRE:
            errores.append(ErrorValidacion(
                "nombre_completo", f"El nombre no puede superar {LONGITUD_MAX_NOMBRE} caracteres.",
            ))
        elif any(c.isdigit() for c in nombre):
            errores.append(ErrorValidacion("nombre_completo", "El nombre no puede contener números."))

    # --- fecha_nacimiento ---
    if paciente.fecha_nacimiento is not None:
        if paciente.fecha_nacimiento > date.today():
            errores.append(ErrorValidacion("fecha_nacimiento", "La fecha de nacimiento no puede ser futura."))
        else:
            edad = (date.today() - paciente.fecha_nacimiento).days / 365.25
            if edad > EDAD_MAXIMA_ANIOS:
                errores.append(ErrorValidacion(
                    "fecha_nacimiento",
                    f"La fecha de nacimiento implica una edad mayor a {EDAD_MAXIMA_ANIOS} años.",
                ))

    # --- numero_identificacion (según tipo) ---
    numero = (paciente.numero_identificacion or "").strip()
    if numero and paciente.tipo_identificacion is not None:
        if paciente.tipo_identificacion == TipoIdentificacion.TEMPORAL:
            if not numero.startswith("TEMP-"):
                errores.append(ErrorValidacion(
                    "numero_identificacion",
                    "El identificador temporal debe tener el formato TEMP-xxxxxxxxxx.",
                ))
        else:
            regla = REGLAS_IDENTIFICACION.get(paciente.tipo_identificacion)
            if regla:
                minimo, maximo, patron = regla
                if not (minimo <= len(numero) <= maximo):
                    errores.append(ErrorValidacion(
                        "numero_identificacion",
                        f"El número de identificación debe tener entre {minimo} y {maximo} caracteres "
                        f"para el tipo {paciente.tipo_identificacion.value}.",
                    ))
                elif not patron.match(numero):
                    errores.append(ErrorValidacion(
                        "numero_identificacion",
                        f"El número de identificación tiene un formato inválido para el tipo "
                        f"{paciente.tipo_identificacion.value}.",
                    ))

    # --- contacto ---
    if paciente.contacto:
        telefono = paciente.contacto.telefono
        if telefono and not REGEX_TELEFONO.match(telefono.strip()):
            errores.append(ErrorValidacion("telefono", "El teléfono tiene un formato inválido."))

        email = paciente.contacto.email
        if email and not REGEX_EMAIL.match(email.strip()):
            errores.append(ErrorValidacion("email", "El email tiene un formato inválido."))

        direccion = paciente.contacto.direccion
        if direccion and len(direccion) > LONGITUD_MAX_DIRECCION:
            errores.append(ErrorValidacion(
                "direccion", f"La dirección no puede superar {LONGITUD_MAX_DIRECCION} caracteres.",
            ))

    # --- antecedentes ---
    if paciente.antecedentes:
        if paciente.antecedentes.personales and len(paciente.antecedentes.personales) > LONGITUD_MAX_ANTECEDENTE:
            errores.append(ErrorValidacion(
                "antecedentes.personales",
                f"Los antecedentes personales no pueden superar {LONGITUD_MAX_ANTECEDENTE} caracteres.",
            ))
        if paciente.antecedentes.familiares and len(paciente.antecedentes.familiares) > LONGITUD_MAX_ANTECEDENTE:
            errores.append(ErrorValidacion(
                "antecedentes.familiares",
                f"Los antecedentes familiares no pueden superar {LONGITUD_MAX_ANTECEDENTE} caracteres.",
            ))

    # --- motivo_consulta_inicial ---
    if paciente.motivo_consulta_inicial and len(paciente.motivo_consulta_inicial) > LONGITUD_MAX_MOTIVO:
        errores.append(ErrorValidacion(
            "motivo_consulta_inicial", f"El motivo de consulta no puede superar {LONGITUD_MAX_MOTIVO} caracteres.",
        ))

    # --- oncologo_id ---
    if paciente.oncologo_id is not None and paciente.oncologo_id <= 0:
        errores.append(ErrorValidacion("oncologo_id", "El id del oncólogo debe ser un entero positivo."))

    return errores


def validar_paciente(paciente: Paciente) -> list:
    """Punto de entrada único: obligatoriedad + formato/longitud."""
    return validar_campos_obligatorios(paciente) + validar_formato_y_longitud(paciente)