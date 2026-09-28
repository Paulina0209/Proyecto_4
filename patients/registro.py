"""HC-01 · Registro de paciente.

- Validación: qué campo obligatorio falta (AC2) y formato/longitud.
- Registro: alerta de posible duplicado antes de crear (AC3) e
  identificador temporal para pacientes sin documento.
- Completar después: el formulario corto deja `registro_completo=False`
  hasta que se agreguen antecedentes y motivo de consulta.
- Persistencia de la tabla `pacientes` (ver db/schema.sql).
"""
from __future__ import annotations

import re
import sqlite3
import uuid
from dataclasses import replace
from datetime import date, datetime
from typing import Optional

from .models import (
    AntecedentesMedicos,
    DatosContacto,
    ErrorValidacion,
    Paciente,
    ResultadoRegistroPaciente,
    Sexo,
    TipoIdentificacion,
)

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


# ---------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------

def validar_campos_obligatorios(paciente: Paciente) -> list[ErrorValidacion]:
    errores: list[ErrorValidacion] = []

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


def validar_formato_y_longitud(paciente: Paciente) -> list[ErrorValidacion]:
    """Valida tipo/formato/longitud de los campos que sí vinieron con dato.
    No repite las validaciones de 'obligatorio' — esas las hace
    validar_campos_obligatorios."""
    errores: list[ErrorValidacion] = []

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


def validar_paciente(paciente: Paciente) -> list[ErrorValidacion]:
    """Punto de entrada único: obligatoriedad + formato/longitud."""
    return validar_campos_obligatorios(paciente) + validar_formato_y_longitud(paciente)


# ---------------------------------------------------------------------------
# Casos de uso
# ---------------------------------------------------------------------------

def generar_identificador_temporal() -> str:
    return f"TEMP-{uuid.uuid4().hex[:10].upper()}"


def _esta_completo(paciente: Paciente) -> bool:
    return bool(
        paciente.antecedentes
        and (paciente.antecedentes.personales or paciente.antecedentes.familiares)
        and paciente.motivo_consulta_inicial
    )


def registrar_paciente(conn: sqlite3.Connection, paciente: Paciente) -> ResultadoRegistroPaciente:
    # Sin documento: si no trae identificador, se genera uno temporal.
    if paciente.tipo_identificacion == TipoIdentificacion.TEMPORAL and not (
        paciente.numero_identificacion or ""
    ).strip():
        paciente.numero_identificacion = generar_identificador_temporal()

    errores = validar_paciente(paciente)
    if errores:
        return ResultadoRegistroPaciente(exito=False, errores=errores)

    # El identificador temporal se genera único, no tiene sentido buscarle duplicados.
    if paciente.tipo_identificacion != TipoIdentificacion.TEMPORAL:
        existente = buscar_por_identificacion(
            conn, paciente.tipo_identificacion, paciente.numero_identificacion
        )
        if existente:
            return ResultadoRegistroPaciente(exito=False, posible_duplicado=existente)

    paciente.registro_completo = _esta_completo(paciente)

    try:
        paciente_guardado = guardar_paciente(conn, paciente)
    except sqlite3.IntegrityError:
        # Condición de carrera: otra petición insertó la misma identificación
        # entre la verificación de arriba y este INSERT. Es un duplicado.
        conn.rollback()
        existente = buscar_por_identificacion(
            conn, paciente.tipo_identificacion, paciente.numero_identificacion
        )
        return ResultadoRegistroPaciente(exito=False, posible_duplicado=existente)

    return ResultadoRegistroPaciente(exito=True, paciente=paciente_guardado)


def completar_registro(
    conn: sqlite3.Connection,
    paciente: Paciente,
    antecedentes_personales: Optional[str] = None,
    antecedentes_familiares: Optional[str] = None,
    motivo_consulta_inicial: Optional[str] = None,
) -> ResultadoRegistroPaciente:
    """Agrega antecedentes y/o motivo a un registro corto. Solo cambia los
    campos que vienen con valor; los demás se conservan."""
    actualizado = replace(
        paciente,
        antecedentes=AntecedentesMedicos(
            personales=antecedentes_personales or paciente.antecedentes.personales,
            familiares=antecedentes_familiares or paciente.antecedentes.familiares,
        ),
        motivo_consulta_inicial=motivo_consulta_inicial or paciente.motivo_consulta_inicial,
    )

    errores = validar_formato_y_longitud(actualizado)
    if errores:
        return ResultadoRegistroPaciente(exito=False, errores=errores)

    actualizado.registro_completo = _esta_completo(actualizado)
    conn.execute(
        """
        UPDATE pacientes SET antecedentes_personales = ?, antecedentes_familiares = ?,
            motivo_consulta_inicial = ?, registro_completo = ?
        WHERE id = ?
        """,
        (
            actualizado.antecedentes.personales,
            actualizado.antecedentes.familiares,
            actualizado.motivo_consulta_inicial,
            int(actualizado.registro_completo),
            actualizado.id,
        ),
    )
    conn.commit()
    return ResultadoRegistroPaciente(exito=True, paciente=actualizado)


# ---------------------------------------------------------------------------
# Persistencia (tabla pacientes)
# ---------------------------------------------------------------------------

def buscar_por_id(conn: sqlite3.Connection, paciente_id: int) -> Optional[Paciente]:
    fila = conn.execute("SELECT * FROM pacientes WHERE id = ?", (paciente_id,)).fetchone()
    return _fila_a_paciente(fila) if fila else None


def buscar_por_identificacion(
    conn: sqlite3.Connection,
    tipo_identificacion: TipoIdentificacion,
    numero_identificacion: str,
) -> Optional[Paciente]:
    fila = conn.execute(
        "SELECT * FROM pacientes WHERE tipo_identificacion = ? AND numero_identificacion = ?",
        (tipo_identificacion.value, numero_identificacion),
    ).fetchone()
    return _fila_a_paciente(fila) if fila else None


def listar_pacientes_de_oncologo(conn: sqlite3.Connection, oncologo_id: int) -> list[Paciente]:
    filas = conn.execute(
        "SELECT * FROM pacientes WHERE oncologo_id = ? ORDER BY fecha_registro DESC, id DESC",
        (oncologo_id,),
    ).fetchall()
    return [_fila_a_paciente(fila) for fila in filas]


def guardar_paciente(conn: sqlite3.Connection, paciente: Paciente) -> Paciente:
    cur = conn.execute(
        """
        INSERT INTO pacientes (
            nombre_completo, fecha_nacimiento, sexo, tipo_identificacion,
            numero_identificacion, telefono, email, direccion,
            antecedentes_personales, antecedentes_familiares,
            motivo_consulta_inicial, oncologo_id, registro_completo, fecha_registro
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            paciente.nombre_completo,
            paciente.fecha_nacimiento.isoformat() if paciente.fecha_nacimiento else None,
            paciente.sexo.value,
            paciente.tipo_identificacion.value,
            paciente.numero_identificacion,
            paciente.contacto.telefono,
            paciente.contacto.email,
            paciente.contacto.direccion,
            paciente.antecedentes.personales,
            paciente.antecedentes.familiares,
            paciente.motivo_consulta_inicial,
            paciente.oncologo_id,
            int(paciente.registro_completo),
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    paciente.id = cur.lastrowid
    return paciente


def _fila_a_paciente(fila: sqlite3.Row) -> Paciente:
    return Paciente(
        id=fila["id"],
        nombre_completo=fila["nombre_completo"],
        fecha_nacimiento=date.fromisoformat(fila["fecha_nacimiento"]) if fila["fecha_nacimiento"] else None,
        sexo=Sexo(fila["sexo"]),
        tipo_identificacion=TipoIdentificacion(fila["tipo_identificacion"]),
        numero_identificacion=fila["numero_identificacion"],
        contacto=DatosContacto(telefono=fila["telefono"], email=fila["email"], direccion=fila["direccion"]),
        antecedentes=AntecedentesMedicos(
            personales=fila["antecedentes_personales"],
            familiares=fila["antecedentes_familiares"],
        ),
        motivo_consulta_inicial=fila["motivo_consulta_inicial"],
        oncologo_id=fila["oncologo_id"],
        registro_completo=bool(fila["registro_completo"]),
    )
