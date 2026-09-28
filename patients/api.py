"""API HTTP del módulo de pacientes: HC-01 (registro), PAC-02 (búsqueda y
datos clínicos) y PAC-03 (resumen 360).

    uvicorn patients.api:app

Al arrancar crea el esquema y, si no hay pacientes, carga los datos de
prueba (db/datos_prueba.sql).

TODO(SEC-01): el oncólogo llega como parámetro (`oncologo_id`), sin
autenticación. Cuando exista, debe salir de la identidad autenticada.
"""
from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from datetime import date
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import db
from .busqueda import (
    TAMANO_PAGINA_DEFECTO,
    TAMANO_PAGINA_MAXIMO,
    buscar_pacientes,
    listar_consultas,
    listar_diagnosticos,
    listar_tratamientos,
    registrar_consulta,
    registrar_diagnostico,
    registrar_tratamiento,
    validar_filtros,
)
from .models import (
    AntecedentesMedicos,
    DatosContacto,
    ErrorValidacion,
    EstadoTratamiento,
    FiltrosBusqueda,
    Paciente,
)
from .registro import buscar_por_id, completar_registro, listar_pacientes_de_oncologo, registrar_paciente
from .resumen_360 import PacienteNoEncontrado, obtener_resumen_360
from .schemas import (
    BusquedaPacientesResponse,
    CompletarRegistroSchema,
    ConsultaCreateSchema,
    ConsultaSchema,
    DiagnosticoCreateSchema,
    DiagnosticoSchema,
    DuplicadoResponse,
    ErroresValidacionResponse,
    PacienteCreateSchema,
    PacienteResponseSchema,
    PacienteResumenSchema,
    Resumen360Schema,
    TratamientoCreateSchema,
    TratamientoSchema,
)

DB_PATH = db.RUTA_DB
# Los tests que registran sus propios pacientes lo ponen en False.
SEMBRAR_DATOS_PRUEBA = True


def get_conn():
    """Una conexión por petición (se sobreescribe en tests con DB_PATH)."""
    conn = db.conectar(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    conn = db.conectar(DB_PATH)
    try:
        db.inicializar(conn)
        if SEMBRAR_DATOS_PRUEBA:
            db.sembrar_datos_prueba(conn)
    finally:
        conn.close()
    yield


app = FastAPI(
    title="Gestión de pacientes · HC-01 / PAC-02 / PAC-03",
    description=(
        "Registro de pacientes (HC-01), búsqueda y filtros por nombre, "
        "diagnóstico, estado de tratamiento y última consulta (PAC-02), y "
        "resumen 360 del paciente (PAC-03)."
    ),
    version="1.0.0",
    lifespan=_lifespan,
)


# ---------------------------------------------------------------------------
# Errores: un solo formato {"detail": {"errores": [{campo, mensaje}]}}
# ---------------------------------------------------------------------------

@app.exception_handler(RequestValidationError)
async def _manejar_error_validacion(request, exc: RequestValidationError):
    """Un campo mal tipado (fecha inválida, valor fuera del enum…) responde
    con el mismo formato que los errores de validación propios."""
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


def _error_400(errores: list[ErrorValidacion]) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"errores": [{"campo": e.campo, "mensaje": e.mensaje} for e in errores]},
    )


def _validar_no_futura(campo: str, fecha: Optional[date]) -> None:
    if fecha is not None and fecha > date.today():
        raise _error_400([ErrorValidacion(campo, "La fecha no puede ser futura.")])


def _paciente_del_oncologo_o_404(conn: sqlite3.Connection, paciente_id: int, oncologo_id: int) -> Paciente:
    """404 tanto si el id no existe como si es de otro oncólogo: no se
    confirma con un 403 que el registro existe."""
    paciente = buscar_por_id(conn, paciente_id)
    if paciente is None or paciente.oncologo_id != oncologo_id:
        raise HTTPException(status_code=404, detail=f"No existe un paciente con id {paciente_id}.")
    return paciente


def _a_schema(paciente: Paciente) -> PacienteResponseSchema:
    return PacienteResponseSchema.model_validate(paciente)


OncologoId = Query(..., description="ID del oncólogo autenticado (alcance de permisos)")
_RESPUESTA_404 = {404: {"description": "No existe un paciente con ese id, o no pertenece al oncólogo"}}
_RESPUESTAS_ESCRITURA = {
    400: {"model": ErroresValidacionResponse, "description": "Datos inválidos"},
    **_RESPUESTA_404,
}


# ---------------------------------------------------------------------------
# HC-01 · Registro de paciente
# ---------------------------------------------------------------------------

@app.post(
    "/pacientes",
    response_model=PacienteResponseSchema,
    status_code=201,
    responses={
        400: {"model": ErroresValidacionResponse, "description": "Campos obligatorios faltantes (AC2)"},
        409: {"model": DuplicadoResponse, "description": "Posible paciente duplicado (AC3)"},
    },
    summary="Registrar un paciente nuevo",
)
def crear_paciente(payload: PacienteCreateSchema, conn: sqlite3.Connection = Depends(get_conn)):
    paciente = Paciente(
        nombre_completo=payload.nombre_completo,
        fecha_nacimiento=payload.fecha_nacimiento,
        sexo=payload.sexo,
        tipo_identificacion=payload.tipo_identificacion,
        numero_identificacion=payload.numero_identificacion or "",
        contacto=DatosContacto(**payload.contacto.model_dump()),
        oncologo_id=payload.oncologo_id,
        antecedentes=AntecedentesMedicos(**payload.antecedentes.model_dump()),
        motivo_consulta_inicial=payload.motivo_consulta_inicial,
    )

    resultado = registrar_paciente(conn, paciente)
    if resultado.exito:
        return _a_schema(resultado.paciente)

    if resultado.posible_duplicado:
        # El detalle del paciente existente solo se revela a su propio
        # oncólogo: si no, cualquiera podría sondear identificaciones.
        detalle = {"mensaje": DuplicadoResponse().mensaje}
        if resultado.posible_duplicado.oncologo_id == payload.oncologo_id:
            detalle["posible_duplicado"] = _a_schema(resultado.posible_duplicado).model_dump(mode="json")
        raise HTTPException(status_code=409, detail=detalle)

    raise _error_400(resultado.errores)


@app.get(
    "/pacientes",
    response_model=list[PacienteResponseSchema],
    summary="Lista de pacientes del oncólogo (AC1: el paciente registrado aparece aquí)",
)
def listar_pacientes(oncologo_id: int = OncologoId, conn: sqlite3.Connection = Depends(get_conn)):
    return [_a_schema(p) for p in listar_pacientes_de_oncologo(conn, oncologo_id)]


# Va antes de /pacientes/{paciente_id} para que "buscar" no se tome como id.
@app.get(
    "/pacientes/buscar",
    response_model=BusquedaPacientesResponse,
    responses={400: {"model": ErroresValidacionResponse, "description": "Filtros inválidos"}},
    summary="Buscar y filtrar pacientes del oncólogo (PAC-02)",
)
def buscar(
    oncologo_id: int = OncologoId,
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
        raise _error_400(errores)

    resultado = buscar_pacientes(conn, filtros, pagina, tamano_pagina)
    return BusquedaPacientesResponse(
        items=[PacienteResumenSchema.model_validate(item) for item in resultado.items],
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
    responses=_RESPUESTA_404,
    summary="Leer un paciente",
)
def leer_paciente(paciente_id: int, oncologo_id: int = OncologoId, conn: sqlite3.Connection = Depends(get_conn)):
    return _a_schema(_paciente_del_oncologo_o_404(conn, paciente_id, oncologo_id))


@app.patch(
    "/pacientes/{paciente_id}",
    response_model=PacienteResponseSchema,
    responses=_RESPUESTAS_ESCRITURA,
    summary="Completar después un registro corto (antecedentes y motivo de consulta)",
)
def completar_paciente(
    paciente_id: int,
    payload: CompletarRegistroSchema,
    oncologo_id: int = OncologoId,
    conn: sqlite3.Connection = Depends(get_conn),
):
    paciente = _paciente_del_oncologo_o_404(conn, paciente_id, oncologo_id)
    resultado = completar_registro(
        conn,
        paciente,
        antecedentes_personales=payload.antecedentes.personales,
        antecedentes_familiares=payload.antecedentes.familiares,
        motivo_consulta_inicial=payload.motivo_consulta_inicial,
    )
    if not resultado.exito:
        raise _error_400(resultado.errores)
    return _a_schema(resultado.paciente)


# ---------------------------------------------------------------------------
# PAC-02 · Datos clínicos que alimentan los filtros (y el resumen 360)
# ---------------------------------------------------------------------------

@app.post(
    "/pacientes/{paciente_id}/diagnosticos",
    response_model=DiagnosticoSchema,
    status_code=201,
    responses=_RESPUESTAS_ESCRITURA,
    summary="Registrar un diagnóstico",
)
def crear_diagnostico(
    paciente_id: int,
    payload: DiagnosticoCreateSchema,
    oncologo_id: int = OncologoId,
    conn: sqlite3.Connection = Depends(get_conn),
):
    _paciente_del_oncologo_o_404(conn, paciente_id, oncologo_id)
    if not payload.descripcion.strip():
        raise _error_400([ErrorValidacion("descripcion", "La descripción del diagnóstico es obligatoria.")])
    _validar_no_futura("fecha", payload.fecha)

    nuevo_id = registrar_diagnostico(conn, paciente_id, payload.descripcion, payload.fecha, payload.estadio)
    return _leer_fila(conn, "diagnosticos", nuevo_id, DiagnosticoSchema)


@app.get(
    "/pacientes/{paciente_id}/diagnosticos",
    response_model=list[DiagnosticoSchema],
    responses=_RESPUESTA_404,
    summary="Diagnósticos del paciente, más reciente primero",
)
def obtener_diagnosticos(paciente_id: int, oncologo_id: int = OncologoId, conn: sqlite3.Connection = Depends(get_conn)):
    _paciente_del_oncologo_o_404(conn, paciente_id, oncologo_id)
    return [DiagnosticoSchema.model_validate(dict(f)) for f in listar_diagnosticos(conn, paciente_id)]


@app.post(
    "/pacientes/{paciente_id}/tratamientos",
    response_model=TratamientoSchema,
    status_code=201,
    responses=_RESPUESTAS_ESCRITURA,
    summary="Registrar un tratamiento",
)
def crear_tratamiento(
    paciente_id: int,
    payload: TratamientoCreateSchema,
    oncologo_id: int = OncologoId,
    conn: sqlite3.Connection = Depends(get_conn),
):
    _paciente_del_oncologo_o_404(conn, paciente_id, oncologo_id)
    _validar_no_futura("fecha_inicio", payload.fecha_inicio)

    nuevo_id = registrar_tratamiento(conn, paciente_id, payload.estado, payload.fecha_inicio, payload.regimen)
    return _leer_fila(conn, "tratamientos", nuevo_id, TratamientoSchema)


@app.get(
    "/pacientes/{paciente_id}/tratamientos",
    response_model=list[TratamientoSchema],
    responses=_RESPUESTA_404,
    summary="Tratamientos del paciente, más reciente primero",
)
def obtener_tratamientos(paciente_id: int, oncologo_id: int = OncologoId, conn: sqlite3.Connection = Depends(get_conn)):
    _paciente_del_oncologo_o_404(conn, paciente_id, oncologo_id)
    return [TratamientoSchema.model_validate(dict(f)) for f in listar_tratamientos(conn, paciente_id)]


@app.post(
    "/pacientes/{paciente_id}/consultas",
    response_model=ConsultaSchema,
    status_code=201,
    responses=_RESPUESTAS_ESCRITURA,
    summary="Registrar una consulta (y su nota, que aparece en el resumen 360)",
)
def crear_consulta(
    paciente_id: int,
    payload: ConsultaCreateSchema,
    oncologo_id: int = OncologoId,
    conn: sqlite3.Connection = Depends(get_conn),
):
    _paciente_del_oncologo_o_404(conn, paciente_id, oncologo_id)
    _validar_no_futura("fecha", payload.fecha)

    nuevo_id = registrar_consulta(conn, paciente_id, payload.fecha, payload.nota)
    return _leer_fila(conn, "consultas", nuevo_id, ConsultaSchema)


@app.get(
    "/pacientes/{paciente_id}/consultas",
    response_model=list[ConsultaSchema],
    responses=_RESPUESTA_404,
    summary="Consultas del paciente, más reciente primero",
)
def obtener_consultas(paciente_id: int, oncologo_id: int = OncologoId, conn: sqlite3.Connection = Depends(get_conn)):
    _paciente_del_oncologo_o_404(conn, paciente_id, oncologo_id)
    return [ConsultaSchema.model_validate(dict(f)) for f in listar_consultas(conn, paciente_id)]


def _leer_fila(conn: sqlite3.Connection, tabla: str, fila_id: int, esquema):
    """Devuelve la fila recién creada tal como quedó guardada."""
    fila = conn.execute(f"SELECT * FROM {tabla} WHERE id = ?", (fila_id,)).fetchone()
    return esquema.model_validate(dict(fila))


# ---------------------------------------------------------------------------
# PAC-03 · Resumen 360
# ---------------------------------------------------------------------------

@app.get(
    "/pacientes/{paciente_id}/resumen-360",
    response_model=Resumen360Schema,
    responses=_RESPUESTA_404,
    summary="Resumen 360 del paciente",
)
def resumen_360(paciente_id: int, oncologo_id: int = OncologoId, conn: sqlite3.Connection = Depends(get_conn)):
    try:
        return Resumen360Schema.model_validate(obtener_resumen_360(conn, paciente_id, oncologo_id))
    except PacienteNoEncontrado as e:
        raise HTTPException(status_code=404, detail=str(e))
