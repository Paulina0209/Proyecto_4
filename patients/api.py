from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Optional

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
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
from .busqueda import (
    EstadoTratamiento,
    FiltrosBusqueda,
    TAMANO_PAGINA_DEFECTO,
    TAMANO_PAGINA_MAXIMO,
    buscar_pacientes,
    inicializar_schema_busqueda,
    validar_filtros,
)
from .resumen_360 import db as db_360
from .resumen_360 import seed as seed_360
from .resumen_360 import service as service_360

DB_PATH = Path(__file__).parent.parent / "pacientes_api.db"

# PAC-03: base MOCK separada a propósito -- ver el docstring de
# resumen_360/schema.sql y R11 del plan (la unificación real de
# identidad de paciente se hace con la migración a una base unificada,
# no antes). Se sigue el mismo patrón que ya usa DB_PATH arriba (un
# archivo propio, conexión nueva por request).
DB_PATH_360 = Path(__file__).parent / "resumen_360_mock.db"


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


class PacienteResumenSchema(BaseModel):
    id: int
    nombre_completo: str
    fecha_nacimiento: Optional[date]
    tipo_identificacion: TipoIdentificacion
    numero_identificacion: str
    diagnosticos: list[str]
    estado_tratamiento: Optional[str]
    fecha_ultima_consulta: Optional[date]


class BusquedaPacientesResponse(BaseModel):
    items: list[PacienteResumenSchema]
    total: int
    pagina: int
    tamano_pagina: int
    total_paginas: int
    filtros_aplicados: dict[str, str]
    # Solo viene lleno cuando total == 0: el frontend lo muestra en lugar
    # de una lista vacía sin explicación.
    mensaje: Optional[str] = None


class DuplicadoResponse(BaseModel):
    mensaje: str = "Ya existe un paciente registrado con esta identificación."
    # D4: Optional a propósito -- solo se incluye cuando el duplicado
    # pertenece al MISMO oncologo_id que intenta el registro (ver
    # crear_paciente). Si es de otro oncólogo, no se revela su detalle.
    posible_duplicado: Optional[PacienteResponseSchema] = None


# --------------------------------------------------------------------- PAC-03

class TratamientoRecienteSchema(BaseModel):
    regimen: str
    estado: str
    fecha_inicio: date


class AlertaActivaSchema(BaseModel):
    tipo: str
    severidad: str
    descripcion: str
    fecha: date


class AccesoRapidoSchema(BaseModel):
    fecha: date
    resumen: str


class Resumen360Schema(BaseModel):
    paciente_id: int
    nombre: str
    diagnostico_principal: Optional[str]
    estadio: Optional[str]
    tratamiento_mas_reciente: Optional[TratamientoRecienteSchema]
    alertas_activas: list[AlertaActivaSchema]
    labs_recientes: list[AccesoRapidoSchema]
    imagenes_recientes: list[AccesoRapidoSchema]
    notas_recientes: list[AccesoRapidoSchema]
    # AC2 de PAC-03 (ligado a HC-05): el front debe mostrar un indicador
    # explícito de "información faltante" cuando esto no está vacío --
    # nunca ocultar el hueco ni rellenarlo con un valor que aparente
    # estar completo.
    campos_faltantes: list[str]
    informacion_incompleta: bool


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


def get_conn_360():
    """PAC-03: conexión a la base MOCK de resumen 360 -- separada de
    get_conn() (la de HC-01) a propósito, ver DB_PATH_360 arriba."""
    conn = sqlite3.connect(DB_PATH_360)
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
    inicializar_schema_busqueda(conn)
    conn.close()

    # PAC-03: inicializa y siembra la base MOCK de resumen 360 -- solo
    # si está vacía (db_360.esta_vacia), para no reventar con
    # IntegrityError si el servidor se reinicia sobre un archivo que ya
    # tenía datos (el mismo problema que seed.py de historia_clinica_mock
    # tiene hoy sin resolver, ver Apéndice C del plan -- aquí sí se evita
    # desde el diseño).
    conn_360 = sqlite3.connect(DB_PATH_360)
    conn_360.row_factory = sqlite3.Row
    db_360.inicializar_esquema(conn_360)
    if db_360.esta_vacia(conn_360):
        seed_360.sembrar_datos_ficticios(conn_360)
    conn_360.close()

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


@app.exception_handler(RequestValidationError)
async def _manejar_error_validacion(request, exc: RequestValidationError):
    # D8: antes, un campo mal tipado ante FastAPI/Pydantic (fecha con
    # formato inválido, un valor de sexo fuera del enum...) devolvía el
    # 422 nativo de FastAPI, con una forma distinta a los 400 que arma
    # validacion.py para los campos obligatorios -- el front tenía que
    # manejar DOS contratos de error distintos según qué campo fallara.
    # Se anida bajo "detail" (igual que hace FastAPI con HTTPException,
    # que es como ya responden los 400 propios de esta API) para que
    # AMBOS caminos den exactamente la misma forma:
    # {"detail": {"errores": [{"campo": ..., "mensaje": ...}]}}.
    errores = [
        {
            "campo": ".".join(
                str(parte) for parte in error["loc"] if parte not in ("body", "query", "path")
            ) or "desconocido",
            "mensaje": error["msg"],
        }
        for error in exc.errors()
    ]
    return JSONResponse(status_code=400, content={"detail": {"errores": errores}})


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
    # TODO(SEC-01): oncologo_id viene del cuerpo de la petición, sin
    # autenticación -- cualquiera puede registrar un paciente "a nombre
    # de" cualquier oncólogo. Mismo problema ya documentado abajo en
    # /pacientes/buscar; depende de que exista autenticación real (P7)
    # para resolverse de raíz -- esto no lo es, solo lo deja documentado.
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
        # D4: antes se devolvía el detalle completo del paciente ya
        # registrado (nombre, contacto, antecedentes) sin verificar que
        # perteneciera al mismo oncólogo que intenta el registro --
        # cualquiera podía "sondear" números de identificación reales y
        # aprender quién ya está registrado. Solo se revela el detalle
        # si el duplicado es del MISMO oncologo_id; si es de otro,
        # mensaje genérico sin datos del paciente.
        if resultado.posible_duplicado.oncologo_id == payload.oncologo_id:
            detalle = {
                "mensaje": "Ya existe un paciente registrado con esta identificación.",
                "posible_duplicado": _paciente_a_schema(resultado.posible_duplicado).model_dump(mode="json"),
            }
        else:
            detalle = {"mensaje": "Ya existe un paciente registrado con esta identificación."}
        raise HTTPException(status_code=409, detail=detalle)

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
    "/pacientes/buscar",
    response_model=BusquedaPacientesResponse,
    responses={400: {"model": ErroresValidacionResponse, "description": "Filtros inválidos"}},
    summary="Buscar y filtrar pacientes de un oncólogo",
)
def buscar(
    # TODO(SEC-01): tomar el oncólogo de la identidad autenticada, no de un query param.
    oncologo_id: int = Query(..., description="ID del oncólogo autenticado (alcance de permisos)"),
    nombre: Optional[str] = Query(None, description="Nombre parcial; ignora mayúsculas y tildes"),
    diagnostico: Optional[str] = Query(None, description="Texto parcial del diagnóstico"),
    estado_tratamiento: Optional[EstadoTratamiento] = Query(None),
    ultima_consulta_desde: Optional[date] = Query(None, description="Inclusive"),
    ultima_consulta_hasta: Optional[date] = Query(None, description="Inclusive"),
    pagina: int = Query(1, ge=1),
    tamano_pagina: int = Query(TAMANO_PAGINA_DEFECTO, ge=1, le=TAMANO_PAGINA_MAXIMO),
    conn: sqlite3.Connection = Depends(get_conn),
):
    filtros = FiltrosBusqueda(
        oncologo_id=oncologo_id,
        nombre=nombre,
        diagnostico=diagnostico,
        estado_tratamiento=estado_tratamiento,
        ultima_consulta_desde=ultima_consulta_desde,
        ultima_consulta_hasta=ultima_consulta_hasta,
    )
    errores = validar_filtros(filtros)
    if errores:
        raise HTTPException(
            status_code=400,
            detail={"errores": [{"campo": e.campo, "mensaje": e.mensaje} for e in errores]},
        )

    resultado = buscar_pacientes(conn, filtros, pagina, tamano_pagina)
    return BusquedaPacientesResponse(
        items=[PacienteResumenSchema(**vars(item)) for item in resultado.items],
        total=resultado.total,
        pagina=resultado.pagina,
        tamano_pagina=resultado.tamano_pagina,
        total_paginas=resultado.total_paginas,
        filtros_aplicados=filtros.aplicados(),
        mensaje=resultado.mensaje,
    )


@app.get(
    "/pacientes/{paciente_id}",
    response_model=PacienteResponseSchema,
    responses={404: {"description": "No existe un paciente con ese id, o no pertenece al oncólogo autenticado"}},
    summary="Leer un paciente por su id",
)
def leer_paciente(
    paciente_id: int,
    # D2/TODO(SEC-01): mitigación mínima mientras no hay autenticación
    # real (P7) -- antes este endpoint no filtraba por propiedad en
    # absoluto: cualquiera que conociera o adivinara un id podía leer
    # nombre, contacto y antecedentes de cualquier paciente, sin ni
    # siquiera un parámetro que lo intentara acotar. Se devuelve 404
    # tanto si el id no existe como si pertenece a otro oncólogo, para
    # no confirmar con un 403 que el registro sí existe.
    oncologo_id: int = Query(..., description="ID del oncólogo autenticado"),
    conn: sqlite3.Connection = Depends(get_conn),
):
    paciente = buscar_por_id(conn, paciente_id)
    if paciente is None or paciente.oncologo_id != oncologo_id:
        raise HTTPException(status_code=404, detail=f"No existe un paciente con id {paciente_id}.")
    return _paciente_a_schema(paciente)


@app.get(
    "/pacientes/{paciente_id}/resumen-360",
    response_model=Resumen360Schema,
    responses={404: {"description": "No existe un paciente con ese id, o no pertenece al oncólogo autenticado"}},
    summary="Dashboard 360 del paciente (PAC-03)",
)
def resumen_360(
    paciente_id: int,
    # NOTA (R11 del plan): paciente_id aquí es el id dentro de la base
    # MOCK de resumen_360 (PAC-03), todavía INDEPENDIENTE de
    # pacientes_identidad (ver D1) -- se integran cuando se resuelva la
    # unificación de base de datos, no antes.
    oncologo_id: int = Query(..., description="ID del oncólogo autenticado"),
    conn: sqlite3.Connection = Depends(get_conn_360),
):
    try:
        resumen = service_360.obtener_resumen_360(conn, paciente_id, oncologo_id)
    except service_360.PacienteNoEncontrado360:
        raise HTTPException(status_code=404, detail=f"No existe un paciente con id {paciente_id}.")

    return Resumen360Schema(
        paciente_id=resumen.paciente_id,
        nombre=resumen.nombre,
        diagnostico_principal=resumen.diagnostico_principal,
        estadio=resumen.estadio,
        tratamiento_mas_reciente=(
            TratamientoRecienteSchema(
                regimen=resumen.tratamiento_mas_reciente.regimen,
                estado=resumen.tratamiento_mas_reciente.estado,
                fecha_inicio=resumen.tratamiento_mas_reciente.fecha_inicio,
            )
            if resumen.tratamiento_mas_reciente is not None
            else None
        ),
        alertas_activas=[
            AlertaActivaSchema(tipo=a.tipo, severidad=a.severidad, descripcion=a.descripcion, fecha=a.fecha)
            for a in resumen.alertas_activas
        ],
        labs_recientes=[AccesoRapidoSchema(fecha=a.fecha, resumen=a.resumen) for a in resumen.labs_recientes],
        imagenes_recientes=[
            AccesoRapidoSchema(fecha=a.fecha, resumen=a.resumen) for a in resumen.imagenes_recientes
        ],
        notas_recientes=[AccesoRapidoSchema(fecha=a.fecha, resumen=a.resumen) for a in resumen.notas_recientes],
        campos_faltantes=list(resumen.campos_faltantes),
        informacion_incompleta=resumen.informacion_incompleta,
    )
