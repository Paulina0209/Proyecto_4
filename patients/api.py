from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Optional

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from .models import (
    Paciente,
    Sexo,
    TipoIdentificacion,
    DatosContacto,
    AntecedentesMedicos,
)
from .registro import registrar_paciente, generar_identificador_temporal
from .repository import inicializar_schema, listar_pacientes_de_oncologo, buscar_por_id

DB_PATH = Path(__file__).parent.parent / "pacientes_api.db"


# ---------------------------------------------------------------------------
# Esquemas de entrada/salida (capa HTTP; el dominio en models.py no cambia)
# ---------------------------------------------------------------------------

class DatosContactoSchema(BaseModel):
    telefono: Optional[str] = None
    email: Optional[str] = None
    direccion: Optional[str] = None


class AntecedentesSchema(BaseModel):
    personales: Optional[str] = None
    familiares: Optional[str] = None


class PacienteCreateSchema(BaseModel):
    # Campos con default "vacío" a propósito: la validación de obligatoriedad
    # la sigue haciendo validacion.py (AC2), no el esquema de FastAPI, para
    # devolver el mismo mensaje "qué campo falta" que ya tienen los tests.
    nombre_completo: str = ""
    fecha_nacimiento: Optional[date] = None
    sexo: Optional[Sexo] = None
    tipo_identificacion: Optional[TipoIdentificacion] = None
    numero_identificacion: Optional[str] = None
    contacto: DatosContactoSchema = Field(default_factory=DatosContactoSchema)
    oncologo_id: int
    antecedentes: AntecedentesSchema = Field(default_factory=AntecedentesSchema)
    motivo_consulta_inicial: Optional[str] = None


class PacienteResponseSchema(BaseModel):
    id: int
    nombre_completo: str
    fecha_nacimiento: Optional[date]
    sexo: Sexo
    tipo_identificacion: TipoIdentificacion
    numero_identificacion: str
    contacto: DatosContactoSchema
    antecedentes: AntecedentesSchema
    motivo_consulta_inicial: Optional[str]
    oncologo_id: int
    registro_completo: bool


class ErrorValidacionSchema(BaseModel):
    campo: str
    mensaje: str


class ErroresValidacionResponse(BaseModel):
    errores: list[ErrorValidacionSchema]


class DuplicadoResponse(BaseModel):
    mensaje: str = "Ya existe un paciente registrado con esta identificación."
    posible_duplicado: PacienteResponseSchema


# ---------------------------------------------------------------------------
# Conexión a base de datos (una por request; se puede sobreescribir en tests
# con app.dependency_overrides[get_conn])
# ---------------------------------------------------------------------------

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _lifespan(app: FastAPI):
    conn = sqlite3.connect(DB_PATH)
    inicializar_schema(conn)
    conn.close()
    yield


app = FastAPI(
    title="HC-01 · Registro de pacientes",
    description=(
        "Registro de un paciente con datos demográficos, antecedentes "
        "básicos y motivo de consulta inicial."
    ),
    version="1.0.0",
    lifespan=_lifespan,
)


def _paciente_a_schema(paciente: Paciente) -> PacienteResponseSchema:
    return PacienteResponseSchema(
        id=paciente.id,
        nombre_completo=paciente.nombre_completo,
        fecha_nacimiento=paciente.fecha_nacimiento,
        sexo=paciente.sexo,
        tipo_identificacion=paciente.tipo_identificacion,
        numero_identificacion=paciente.numero_identificacion,
        contacto=DatosContactoSchema(
            telefono=paciente.contacto.telefono,
            email=paciente.contacto.email,
            direccion=paciente.contacto.direccion,
        ),
        antecedentes=AntecedentesSchema(
            personales=paciente.antecedentes.personales,
            familiares=paciente.antecedentes.familiares,
        ),
        motivo_consulta_inicial=paciente.motivo_consulta_inicial,
        oncologo_id=paciente.oncologo_id,
        registro_completo=paciente.registro_completo,
    )


@app.post(
    "/pacientes",
    response_model=PacienteResponseSchema,
    status_code=201,
    responses={
        400: {"model": ErroresValidacionResponse, "description": "Campos obligatorios faltantes (AC2)"},
        409: {"model": DuplicadoResponse, "description": "Posible paciente duplicado (AC3)"},
    },
    summary="Registrar un paciente nuevo (AC1/AC2/AC3 de HC-01)",
)
def crear_paciente(payload: PacienteCreateSchema, conn: sqlite3.Connection = Depends(get_conn)):
    numero_identificacion = payload.numero_identificacion
    if payload.tipo_identificacion == TipoIdentificacion.TEMPORAL and not numero_identificacion:
        numero_identificacion = generar_identificador_temporal()

    paciente = Paciente(
        nombre_completo=payload.nombre_completo,
        fecha_nacimiento=payload.fecha_nacimiento,
        sexo=payload.sexo,
        tipo_identificacion=payload.tipo_identificacion,
        numero_identificacion=numero_identificacion or "",
        contacto=DatosContacto(
            telefono=payload.contacto.telefono,
            email=payload.contacto.email,
            direccion=payload.contacto.direccion,
        ),
        oncologo_id=payload.oncologo_id,
        antecedentes=AntecedentesMedicos(
            personales=payload.antecedentes.personales,
            familiares=payload.antecedentes.familiares,
        ),
        motivo_consulta_inicial=payload.motivo_consulta_inicial,
    )

    resultado = registrar_paciente(conn, paciente)

    if resultado.exito:
        return _paciente_a_schema(resultado.paciente)

    if resultado.posible_duplicado:
        raise HTTPException(
            status_code=409,
            detail={
                "mensaje": "Ya existe un paciente registrado con esta identificación.",
                "posible_duplicado": _paciente_a_schema(resultado.posible_duplicado).model_dump(mode="json"),
            },
        )

    raise HTTPException(
        status_code=400,
        detail={"errores": [{"campo": e.campo, "mensaje": e.mensaje} for e in resultado.errores]},
    )


@app.get(
    "/pacientes",
    response_model=list[PacienteResponseSchema],
    summary="Listar los pacientes registrados por un oncólogo (parte de AC1)",
)
def listar_pacientes(
    oncologo_id: int = Query(..., description="ID del oncólogo autenticado"),
    conn: sqlite3.Connection = Depends(get_conn),
):
    pacientes = listar_pacientes_de_oncologo(conn, oncologo_id)
    return [_paciente_a_schema(p) for p in pacientes]


@app.get(
    "/pacientes/{paciente_id}",
    response_model=PacienteResponseSchema,
    responses={404: {"description": "No existe un paciente con ese id"}},
    summary="Leer un paciente por su id",
)
def leer_paciente(paciente_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    paciente = buscar_por_id(conn, paciente_id)
    if paciente is None:
        raise HTTPException(status_code=404, detail=f"No existe un paciente con id {paciente_id}.")
    return _paciente_a_schema(paciente)


@app.get(
    "/identificadores-temporales/nuevo",
    summary="Generar un identificador temporal (paciente sin documento)",
)
def nuevo_identificador_temporal():
    return {"identificador_temporal": generar_identificador_temporal()}
