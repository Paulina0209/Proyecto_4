"""API HTTP del módulo de pacientes: HC-01 (registro), PAC-02 (búsqueda y
datos clínicos), PAC-03 (resumen 360), HC-02 (laboratorios), HC-04
(biopsias y biomarcadores) y HC-03 (imágenes diagnósticas del PACS).

    uvicorn patients.api:app

Al arrancar crea el esquema si falta. No carga datos de ejemplo: los
pacientes son los registrados y los de cBioPortal.

Si existe el expediente real (``data/copiloto.db`` o la ruta de
``COPILOTO_EXPEDIENTE_DB``), los pacientes creados por el índice de
cBioPortal traen su detalle la primera vez que se abren (``leer_paciente``
y ``resumen_360``). Ver docs/cbioportal.md.

Los laboratorios, biopsias y biomarcadores se guardan en el expediente
clínico (``EXPEDIENTE_PATH``; por defecto el de ``COPILOTO_EXPEDIENTE_DB`` o
``data/copiloto.db``), que es lo que leen DX, EST, TX e IA. Un paciente de
esta base entra al expediente la primera vez que se le registra uno de esos
datos (``patients/expediente.py``).

TODO(SEC-01): el oncólogo llega como parámetro (`oncologo_id`), sin
autenticación. Cuando exista, debe salir de la identidad autenticada.
"""
from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from auditoria.models import TipoAccion
from auditoria.registro_acceso import inicializar_schema as inicializar_schema_auditoria
from auditoria.registro_acceso import registrar_acceso
from historia_clinica import biopsias_biomarcadores as hc04
from historia_clinica import imagenes_pacs as hc03
from historia_clinica import laboratorios as hc02
from historia_clinica.db import conectar_expediente, ruta_expediente
from historia_clinica.integracion_externa import importar_mensaje_hl7

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
from .expediente import identificacion_coincide, paciente_en_expediente
from .registro import buscar_por_id, completar_registro, listar_pacientes_de_oncologo, registrar_paciente
from .resumen_360 import PacienteNoEncontrado, obtener_resumen_360
from .schemas import (
    AlertaLaboratorioSchema,
    BiomarcadorCreateSchema,
    BiomarcadorSchema,
    BiopsiaCreateSchema,
    BiopsiaSchema,
    BusquedaPacientesResponse,
    ConfirmarBiomarcadorSchema,
    ConflictoLaboratorioSchema,
    DescartarBiomarcadorSchema,
    EpisodioCreateSchema,
    EpisodioSchema,
    VisorNoDisponibleSchema,
    VisorSchema,
    VistaImagenesSchema,
    LaboratorioCreateSchema,
    LaboratorioRegistradoSchema,
    MensajeHL7Schema,
    ResolverConflictoSchema,
    ResumenMarcadorSchema,
    RevisarAlertaSchema,
    SincronizacionSchema,
    TendenciaMarcadorSchema,
    CompletarRegistroSchema,
    ConsultaCreateSchema,
    ConsultaPACSSchema,
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
#: Expediente clínico (HC-02, HC-04). None = ``historia_clinica.db.ruta_expediente()``;
#: los tests lo apuntan a una base temporal.
EXPEDIENTE_PATH: Optional[Path] = None
#: Carga bajo demanda del detalle de pacientes externos (cbioportal.indice.
#: CargadorDetalle). None = desactivada; se crea al arrancar si existe el
#: expediente real, y los tests pueden asignarla directamente.
CARGADOR_DETALLE = None
#: PACS de la institución (HC-03): una ``historia_clinica.imagenes_pacs.FuentePACS``.
#: None = la que configuren ``COPILOTO_PACS_URL`` y compañía; sin ninguna, la
#: integración se informa como no disponible. Los tests asignan un doble.
PACS_FUENTE = None
#: Plantilla de URL del visor incrustable (``{study_uid}``). None = ``COPILOTO_VISOR_URL``.
VISOR_PLANTILLA: Optional[str] = None


def get_conn():
    """Una conexión por petición (se sobreescribe en tests con DB_PATH)."""
    conn = db.conectar(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


def _ruta_expediente() -> Path:
    return Path(EXPEDIENTE_PATH) if EXPEDIENTE_PATH else ruta_expediente()


def get_conn_expediente():
    """Conexión al expediente clínico (lo crea si no existe)."""
    conn = conectar_expediente(_ruta_expediente(), check_same_thread=False)
    try:
        yield conn
    finally:
        conn.close()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    global CARGADOR_DETALLE
    ruta = ruta_expediente()
    if CARGADOR_DETALLE is None and ruta.is_file():
        from cbioportal.indice import CargadorDetalle

        CARGADOR_DETALLE = CargadorDetalle.desde_ruta(str(ruta))
    conn = db.conectar(DB_PATH)
    try:
        db.inicializar(conn)
        inicializar_schema_auditoria(conn)
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


def _asegurar_detalle(conn: sqlite3.Connection, paciente_id: int) -> None:
    """Un paciente del índice de cBioPortal trae su detalle al abrirse por
    primera vez. Nunca falla: si la fuente no responde, se muestra lo que hay."""
    if CARGADOR_DETALLE is not None:
        CARGADOR_DETALLE.asegurar_detalle(conn, paciente_id)


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
def leer_paciente(
    paciente_id: int,
    oncologo_id: int = OncologoId,
    usuario_id: Optional[int] = Query(
        default=None,
        description=(
            "ID de quien consulta el expediente. Si se provee, el acceso "
            "queda registrado en el log de auditoría (AUD-01)."
        ),
    ),
    conn: sqlite3.Connection = Depends(get_conn),
):
    paciente = _paciente_del_oncologo_o_404(conn, paciente_id, oncologo_id)
    _asegurar_detalle(conn, paciente_id)
    if usuario_id is not None:
        registrar_acceso(conn, usuario_id, TipoAccion.VER, paciente_id=paciente_id)
    return _a_schema(buscar_por_id(conn, paciente_id))


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
    # Solo se carga el detalle de un paciente del propio oncólogo.
    _paciente_del_oncologo_o_404(conn, paciente_id, oncologo_id)
    _asegurar_detalle(conn, paciente_id)
    # Leer el 360 no crea el expediente: solo se consulta si ya existe.
    ruta = _ruta_expediente()
    conn_exp = conectar_expediente(ruta, check_same_thread=False) if ruta.is_file() else None
    try:
        return Resumen360Schema.model_validate(obtener_resumen_360(conn, paciente_id, oncologo_id, conn_exp))
    except PacienteNoEncontrado as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        if conn_exp is not None:
            conn_exp.close()


# ---------------------------------------------------------------------------
# HC-02 / HC-04: datos del expediente clínico
# ---------------------------------------------------------------------------

def _id_en_expediente(conn, conn_exp, paciente_id: int, oncologo_id: int, crear: bool) -> Optional[int]:
    _paciente_del_oncologo_o_404(conn, paciente_id, oncologo_id)
    return paciente_en_expediente(conn, conn_exp, paciente_id, crear=crear)


def _error_400_hc(exc: Exception) -> HTTPException:
    errores = getattr(exc, "errores", None) or [("datos", str(exc))]
    return HTTPException(status_code=400, detail={"errores": [{"campo": c, "mensaje": m} for c, m in errores]})


def _error_409_identidad(mensaje: str) -> HTTPException:
    return HTTPException(status_code=409, detail={"errores": [{"campo": "identificacion", "mensaje": mensaje}]})


def _no_encontrado(paciente_id: int, que: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"El paciente {paciente_id} no tiene {que}.")


_RESPUESTAS_LAB = {
    **_RESPUESTAS_ESCRITURA,
    409: {"model": ErroresValidacionResponse, "description": "La identificación o el nombre no corresponden al paciente"},
}


@app.post(
    "/pacientes/{paciente_id}/laboratorios",
    response_model=LaboratorioRegistradoSchema,
    status_code=201,
    responses=_RESPUESTAS_LAB,
    summary="HC-02: registrar un resultado de laboratorio (manual, con doble validación ID + nombre)",
)
def crear_laboratorio(
    paciente_id: int,
    payload: LaboratorioCreateSchema,
    oncologo_id: int = OncologoId,
    conn: sqlite3.Connection = Depends(get_conn),
    conn_exp: sqlite3.Connection = Depends(get_conn_expediente),
):
    paciente = _paciente_del_oncologo_o_404(conn, paciente_id, oncologo_id)
    if not identificacion_coincide(paciente.numero_identificacion, payload.identificacion):
        raise _error_409_identidad(
            f"La identificación '{payload.identificacion}' no corresponde al paciente {paciente_id}. "
            "No se guardó el resultado."
        )
    expediente_id = paciente_en_expediente(conn, conn_exp, paciente_id, crear=True)
    try:
        resultado = hc02.registrar_resultado_laboratorio(
            conn_exp, expediente_id,
            identificacion=paciente.numero_identificacion, nombre=payload.nombre,
            prueba=payload.prueba, valor=payload.valor, unidad=payload.unidad,
            fecha=payload.fecha, hora=payload.hora, rango_referencia=payload.rango_referencia,
        )
    except hc02.IdentidadNoCoincideError as exc:
        raise _error_409_identidad(str(exc))
    except hc02.ErrorLaboratorio as exc:
        raise _error_400_hc(exc)
    return LaboratorioRegistradoSchema(
        laboratorio_id=resultado.laboratorio_id,
        alerta=AlertaLaboratorioSchema.model_validate(resultado.alerta) if resultado.alerta else None,
        conflictos=[ConflictoLaboratorioSchema.model_validate(c) for c in resultado.conflictos],
    )


@app.post(
    "/pacientes/{paciente_id}/laboratorios/hl7",
    response_model=SincronizacionSchema,
    responses=_RESPUESTAS_ESCRITURA,
    summary="HC-02: recibir resultados de la interfaz de laboratorio (HL7 v2 ORU^R01)",
)
def recibir_hl7(
    paciente_id: int,
    payload: MensajeHL7Schema,
    oncologo_id: int = OncologoId,
    conn: sqlite3.Connection = Depends(get_conn),
    conn_exp: sqlite3.Connection = Depends(get_conn_expediente),
):
    expediente_id = _id_en_expediente(conn, conn_exp, paciente_id, oncologo_id, crear=True)
    resultado = importar_mensaje_hl7(conn_exp, expediente_id, payload.mensaje, payload.fuente)
    if not resultado.exito:
        raise HTTPException(status_code=400, detail={"errores": [{"campo": "mensaje", "mensaje": resultado.mensaje}]})
    return SincronizacionSchema(
        exito=True, registros_importados=resultado.registros_importados,
        registros_omitidos=resultado.registros_omitidos, mensaje=resultado.mensaje,
    )


@app.get(
    "/pacientes/{paciente_id}/laboratorios/marcadores",
    response_model=list[ResumenMarcadorSchema],
    responses=_RESPUESTA_404,
    summary="HC-02: marcadores con resultados, el medido más recientemente primero",
)
def listar_marcadores(
    paciente_id: int,
    oncologo_id: int = OncologoId,
    conn: sqlite3.Connection = Depends(get_conn),
    conn_exp: sqlite3.Connection = Depends(get_conn_expediente),
):
    expediente_id = _id_en_expediente(conn, conn_exp, paciente_id, oncologo_id, crear=False)
    if expediente_id is None:
        return []
    return [ResumenMarcadorSchema.model_validate(m) for m in hc02.marcadores_de_paciente(conn_exp, expediente_id)]


@app.get(
    "/pacientes/{paciente_id}/laboratorios/tendencia",
    response_model=TendenciaMarcadorSchema,
    responses=_RESPUESTA_404,
    summary="HC-02: tendencia histórica de un marcador",
)
def tendencia_de_marcador(
    paciente_id: int,
    prueba: str = Query(..., min_length=1, description="Nombre del marcador (acepta alias: Hb, K, CEA...)"),
    oncologo_id: int = OncologoId,
    conn: sqlite3.Connection = Depends(get_conn),
    conn_exp: sqlite3.Connection = Depends(get_conn_expediente),
):
    expediente_id = _id_en_expediente(conn, conn_exp, paciente_id, oncologo_id, crear=False)
    if expediente_id is None:
        return TendenciaMarcadorSchema(clave=prueba, prueba=prueba, series=[], advertencias=[])
    return TendenciaMarcadorSchema.model_validate(hc02.tendencia_marcador(conn_exp, expediente_id, prueba))


@app.get(
    "/pacientes/{paciente_id}/alertas-laboratorio",
    response_model=list[AlertaLaboratorioSchema],
    responses=_RESPUESTA_404,
    summary="HC-02: alertas por valor crítico",
)
def listar_alertas_laboratorio(
    paciente_id: int,
    solo_activas: bool = Query(True),
    oncologo_id: int = OncologoId,
    conn: sqlite3.Connection = Depends(get_conn),
    conn_exp: sqlite3.Connection = Depends(get_conn_expediente),
):
    expediente_id = _id_en_expediente(conn, conn_exp, paciente_id, oncologo_id, crear=False)
    if expediente_id is None:
        return []
    alertas = hc02.alertas_de_paciente(conn_exp, expediente_id, solo_activas=solo_activas)
    return [AlertaLaboratorioSchema.model_validate(a) for a in alertas]


@app.post(
    "/pacientes/{paciente_id}/alertas-laboratorio/{alerta_id}/revisar",
    response_model=AlertaLaboratorioSchema,
    responses=_RESPUESTAS_ESCRITURA,
    summary="HC-02: marcar una alerta crítica como revisada",
)
def revisar_alerta_laboratorio(
    paciente_id: int,
    alerta_id: int,
    payload: RevisarAlertaSchema,
    oncologo_id: int = OncologoId,
    conn: sqlite3.Connection = Depends(get_conn),
    conn_exp: sqlite3.Connection = Depends(get_conn_expediente),
):
    expediente_id = _id_en_expediente(conn, conn_exp, paciente_id, oncologo_id, crear=False)
    if expediente_id is None:
        raise _no_encontrado(paciente_id, f"la alerta {alerta_id}")
    try:
        alerta = hc02.marcar_alerta_revisada(conn_exp, expediente_id, alerta_id, payload.revisada_por)
    except hc02.ErrorLaboratorio as exc:
        raise _error_400_hc(exc)
    return AlertaLaboratorioSchema.model_validate(alerta)


@app.get(
    "/pacientes/{paciente_id}/conflictos-laboratorio",
    response_model=list[ConflictoLaboratorioSchema],
    responses=_RESPUESTA_404,
    summary="HC-02: resultados en conflicto (mismo marcador y momento, valores distintos)",
)
def listar_conflictos_laboratorio(
    paciente_id: int,
    solo_pendientes: bool = Query(True),
    oncologo_id: int = OncologoId,
    conn: sqlite3.Connection = Depends(get_conn),
    conn_exp: sqlite3.Connection = Depends(get_conn_expediente),
):
    expediente_id = _id_en_expediente(conn, conn_exp, paciente_id, oncologo_id, crear=False)
    if expediente_id is None:
        return []
    conflictos = hc02.conflictos_de_paciente(conn_exp, expediente_id, solo_pendientes=solo_pendientes)
    return [ConflictoLaboratorioSchema.model_validate(c) for c in conflictos]


@app.post(
    "/pacientes/{paciente_id}/conflictos-laboratorio/{conflicto_id}/resolver",
    response_model=ConflictoLaboratorioSchema,
    responses=_RESPUESTAS_ESCRITURA,
    summary="HC-02: resolver un conflicto (ningún resultado se borra)",
)
def resolver_conflicto_laboratorio(
    paciente_id: int,
    conflicto_id: int,
    payload: ResolverConflictoSchema,
    oncologo_id: int = OncologoId,
    conn: sqlite3.Connection = Depends(get_conn),
    conn_exp: sqlite3.Connection = Depends(get_conn_expediente),
):
    expediente_id = _id_en_expediente(conn, conn_exp, paciente_id, oncologo_id, crear=False)
    if expediente_id is None:
        raise _no_encontrado(paciente_id, f"el conflicto {conflicto_id}")
    try:
        conflicto = hc02.resolver_conflicto(
            conn_exp, expediente_id, conflicto_id, payload.resolucion.value, payload.resuelto_por, payload.nota
        )
    except hc02.ErrorLaboratorio as exc:
        raise _error_400_hc(exc)
    return ConflictoLaboratorioSchema.model_validate(conflicto)


@app.post(
    "/pacientes/{paciente_id}/episodios",
    response_model=EpisodioSchema,
    status_code=201,
    responses=_RESPUESTAS_ESCRITURA,
    summary="HC-04: registrar un episodio diagnóstico",
)
def crear_episodio(
    paciente_id: int,
    payload: EpisodioCreateSchema,
    oncologo_id: int = OncologoId,
    conn: sqlite3.Connection = Depends(get_conn),
    conn_exp: sqlite3.Connection = Depends(get_conn_expediente),
):
    expediente_id = _id_en_expediente(conn, conn_exp, paciente_id, oncologo_id, crear=True)
    try:
        episodio = hc04.registrar_episodio(
            conn_exp, expediente_id, payload.descripcion, payload.tipo_cancer, payload.fecha_diagnostico
        )
    except hc04.ErrorBiomarcador as exc:
        raise _error_400_hc(exc)
    return EpisodioSchema.model_validate(episodio)


@app.get(
    "/pacientes/{paciente_id}/episodios",
    response_model=list[EpisodioSchema],
    responses=_RESPUESTA_404,
    summary="HC-04: episodios diagnósticos del paciente",
)
def listar_episodios(
    paciente_id: int,
    oncologo_id: int = OncologoId,
    conn: sqlite3.Connection = Depends(get_conn),
    conn_exp: sqlite3.Connection = Depends(get_conn_expediente),
):
    expediente_id = _id_en_expediente(conn, conn_exp, paciente_id, oncologo_id, crear=False)
    if expediente_id is None:
        return []
    return [EpisodioSchema.model_validate(e) for e in hc04.episodios_de_paciente(conn_exp, expediente_id)]


@app.post(
    "/pacientes/{paciente_id}/biopsias",
    response_model=BiopsiaSchema,
    status_code=201,
    responses=_RESPUESTAS_ESCRITURA,
    summary="HC-04: registrar una biopsia (queda vinculada a su episodio diagnóstico)",
)
def crear_biopsia(
    paciente_id: int,
    payload: BiopsiaCreateSchema,
    oncologo_id: int = OncologoId,
    conn: sqlite3.Connection = Depends(get_conn),
    conn_exp: sqlite3.Connection = Depends(get_conn_expediente),
):
    expediente_id = _id_en_expediente(conn, conn_exp, paciente_id, oncologo_id, crear=True)
    try:
        biopsia = hc04.registrar_biopsia(
            conn_exp, expediente_id, fecha=payload.fecha, sitio=payload.sitio, procedimiento=payload.procedimiento,
            diagnostico_histologico=payload.diagnostico_histologico, episodio_id=payload.episodio_id,
            registrado_por=payload.registrado_por,
        )
    except hc04.ErrorBiomarcador as exc:
        raise _error_400_hc(exc)
    return BiopsiaSchema.model_validate(biopsia)


@app.get(
    "/pacientes/{paciente_id}/biopsias",
    response_model=list[BiopsiaSchema],
    responses=_RESPUESTA_404,
    summary="HC-04: biopsias del paciente, la más reciente primero",
)
def listar_biopsias(
    paciente_id: int,
    oncologo_id: int = OncologoId,
    conn: sqlite3.Connection = Depends(get_conn),
    conn_exp: sqlite3.Connection = Depends(get_conn_expediente),
):
    expediente_id = _id_en_expediente(conn, conn_exp, paciente_id, oncologo_id, crear=False)
    if expediente_id is None:
        return []
    return [BiopsiaSchema.model_validate(b) for b in hc04.biopsias_de_paciente(conn_exp, expediente_id)]


@app.post(
    "/pacientes/{paciente_id}/biomarcadores",
    response_model=BiomarcadorSchema,
    status_code=201,
    responses=_RESPUESTAS_ESCRITURA,
    summary="HC-04: registrar un biomarcador (validación estricta y doble ingreso)",
)
def crear_biomarcador(
    paciente_id: int,
    payload: BiomarcadorCreateSchema,
    oncologo_id: int = OncologoId,
    conn: sqlite3.Connection = Depends(get_conn),
    conn_exp: sqlite3.Connection = Depends(get_conn_expediente),
):
    expediente_id = _id_en_expediente(conn, conn_exp, paciente_id, oncologo_id, crear=True)
    try:
        registrado = hc04.registrar_biomarcador(
            conn_exp, expediente_id, biopsia_id=payload.biopsia_id, biomarcador=payload.biomarcador,
            estado=payload.estado, confirmacion=payload.confirmacion, metodo=payload.metodo,
            variante=payload.variante, valor=payload.valor, ihc_score=payload.ihc_score, ish=payload.ish,
            registrado_por=payload.registrado_por,
        )
    except hc04.ErrorBiomarcador as exc:
        raise _error_400_hc(exc)
    return BiomarcadorSchema.model_validate(registrado)


@app.get(
    "/pacientes/{paciente_id}/biomarcadores",
    response_model=list[BiomarcadorSchema],
    responses=_RESPUESTA_404,
    summary="HC-04: biomarcadores registrados con su dato estructurado",
)
def listar_biomarcadores(
    paciente_id: int,
    solo_clave: bool = Query(False, description="Solo los relevantes para el tratamiento (AC2)"),
    oncologo_id: int = OncologoId,
    conn: sqlite3.Connection = Depends(get_conn),
    conn_exp: sqlite3.Connection = Depends(get_conn_expediente),
):
    expediente_id = _id_en_expediente(conn, conn_exp, paciente_id, oncologo_id, crear=False)
    if expediente_id is None:
        return []
    lista = (hc04.biomarcadores_clave if solo_clave else hc04.biomarcadores_registrados)(conn_exp, expediente_id)
    return [BiomarcadorSchema.model_validate(b) for b in lista]


@app.post(
    "/pacientes/{paciente_id}/biomarcadores/{biomarcador_id}/confirmar",
    response_model=BiomarcadorSchema,
    responses=_RESPUESTAS_ESCRITURA,
    summary="HC-04: confirmar un biomarcador pendiente (pasa a ser insumo de TX-01)",
)
def confirmar_biomarcador(
    paciente_id: int,
    biomarcador_id: int,
    payload: ConfirmarBiomarcadorSchema,
    oncologo_id: int = OncologoId,
    conn: sqlite3.Connection = Depends(get_conn),
    conn_exp: sqlite3.Connection = Depends(get_conn_expediente),
):
    expediente_id = _id_en_expediente(conn, conn_exp, paciente_id, oncologo_id, crear=False)
    if expediente_id is None:
        raise _no_encontrado(paciente_id, f"el biomarcador {biomarcador_id}")
    try:
        registrado = hc04.confirmar_biomarcador(
            conn_exp, expediente_id, biomarcador_id, payload.confirmado_por, payload.confirmacion
        )
    except hc04.ErrorBiomarcador as exc:
        raise _error_400_hc(exc)
    return BiomarcadorSchema.model_validate(registrado)


@app.post(
    "/pacientes/{paciente_id}/biomarcadores/{biomarcador_id}/descartar",
    response_model=BiomarcadorSchema,
    responses=_RESPUESTAS_ESCRITURA,
    summary="HC-04: descartar un biomarcador pendiente (no es accionable para este paciente)",
)
def descartar_biomarcador(
    paciente_id: int,
    biomarcador_id: int,
    payload: DescartarBiomarcadorSchema,
    oncologo_id: int = OncologoId,
    conn: sqlite3.Connection = Depends(get_conn),
    conn_exp: sqlite3.Connection = Depends(get_conn_expediente),
):
    expediente_id = _id_en_expediente(conn, conn_exp, paciente_id, oncologo_id, crear=False)
    if expediente_id is None:
        raise _no_encontrado(paciente_id, f"el biomarcador {biomarcador_id}")
    try:
        registrado = hc04.descartar_biomarcador(conn_exp, expediente_id, biomarcador_id, payload.revisado_por)
    except hc04.ErrorBiomarcador as exc:
        raise _error_400_hc(exc)
    return BiomarcadorSchema.model_validate(registrado)


# ---------------------------------------------------------------------------
# HC-03: imágenes diagnósticas (DICOM/PACS)
# ---------------------------------------------------------------------------

def _fuente_pacs():
    return PACS_FUENTE if PACS_FUENTE is not None else hc03.fuente_desde_entorno()


def _plantilla_visor() -> Optional[str]:
    try:
        return VISOR_PLANTILLA if VISOR_PLANTILLA is not None else hc03.plantilla_visor_desde_entorno()
    except hc03.ErrorConfiguracionVisor:
        return None  # visor mal configurado: se informa como "sin visor", no se cae la API


_USUARIO_AUDITORIA = Query(
    default=None,
    description="ID de quien consulta. Si se provee, el acceso queda registrado en el log de auditoría (AUD-01).",
)


@app.get(
    "/pacientes/{paciente_id}/imagenes",
    response_model=VistaImagenesSchema,
    responses=_RESPUESTA_404,
    summary="HC-03: estudios de imagen del PACS y sus informes (aviso explícito si el PACS no responde)",
)
def ver_imagenes(
    paciente_id: int,
    oncologo_id: int = OncologoId,
    usuario_id: Optional[int] = _USUARIO_AUDITORIA,
    conn: sqlite3.Connection = Depends(get_conn),
    conn_exp: sqlite3.Connection = Depends(get_conn_expediente),
):
    # Se crea en el expediente (``crear=True``) porque el índice de estudios cuelga de él.
    expediente_id = _id_en_expediente(conn, conn_exp, paciente_id, oncologo_id, crear=True)
    if usuario_id is not None:
        registrar_acceso(conn, usuario_id, TipoAccion.VER, paciente_id=paciente_id, detalle="imagenes_pacs")
    vista = hc03.estudios_del_expediente(
        conn_exp, expediente_id, _fuente_pacs(), plantilla_visor=_plantilla_visor()
    )
    return VistaImagenesSchema.model_validate(vista)


@app.get(
    "/pacientes/{paciente_id}/imagenes/{study_uid}/visor",
    response_model=VisorSchema,
    responses={
        **_RESPUESTA_404,
        503: {"model": VisorNoDisponibleSchema, "description": "La integración con el PACS no está disponible (AC2)"},
    },
    summary="HC-03: abrir un estudio en el visor incrustado (503 explícito si el PACS no está disponible)",
)
def abrir_visor_imagen(
    paciente_id: int,
    study_uid: str,
    oncologo_id: int = OncologoId,
    usuario_id: Optional[int] = _USUARIO_AUDITORIA,
    conn: sqlite3.Connection = Depends(get_conn),
    conn_exp: sqlite3.Connection = Depends(get_conn_expediente),
):
    expediente_id = _id_en_expediente(conn, conn_exp, paciente_id, oncologo_id, crear=True)
    if usuario_id is not None:
        registrar_acceso(
            conn, usuario_id, TipoAccion.VER, paciente_id=paciente_id, detalle=f"visor_pacs:{study_uid}"
        )
    resultado = hc03.abrir_visor(
        conn_exp, expediente_id, study_uid, _fuente_pacs(), plantilla_visor=_plantilla_visor()
    )
    if not resultado.disponible:
        cuerpo = VisorNoDisponibleSchema.model_validate(resultado).model_dump(mode="json")
        return JSONResponse(status_code=503, content=cuerpo)
    return VisorSchema.model_validate(resultado)


@app.get(
    "/pacientes/{paciente_id}/imagenes/consultas",
    response_model=list[ConsultaPACSSchema],
    responses=_RESPUESTA_404,
    summary="HC-03: bitácora de intentos de consulta al PACS (incluye los fallidos)",
)
def consultas_pacs(
    paciente_id: int,
    oncologo_id: int = OncologoId,
    conn: sqlite3.Connection = Depends(get_conn),
    conn_exp: sqlite3.Connection = Depends(get_conn_expediente),
):
    expediente_id = _id_en_expediente(conn, conn_exp, paciente_id, oncologo_id, crear=False)
    if expediente_id is None:
        return []
    return [ConsultaPACSSchema.model_validate(c) for c in hc03.historial_consultas(conn_exp, expediente_id)]
