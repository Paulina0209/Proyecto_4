"""API HTTP de ADM-01 (gestión de usuarios, roles y permisos).

    uvicorn administracion.api:app

Autenticación: HTTP Basic sobre el login de SEC-01 (``autenticar``), en cada
petición, así que el bloqueo temporal por intentos fallidos también aplica
aquí. Todavía no hay sesiones ni tokens (ver ``docs/seguridad.md``): sirve
solo detrás de TLS (SEC-02). Un usuario autenticado que no es
``administrador`` recibe 403, y el intento queda auditado.

La base es ``COPILOTO_USUARIOS_DB`` (por defecto ``data/usuarios.db``). El
primer administrador se crea con ``python -m administracion crear-admin``.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, ConfigDict

from administracion import usuarios as adm
from seguridad.autenticacion import autenticar
from seguridad.models import Rol, Usuario

RUTA_POR_DEFECTO = Path(__file__).resolve().parent.parent / "data" / "usuarios.db"
#: None = ``COPILOTO_USUARIOS_DB`` o ``data/usuarios.db``; los tests lo apuntan a una base temporal.
USUARIOS_DB_PATH: Optional[Path] = None

app = FastAPI(title="Copiloto oncológico — Administración (ADM-01)")
_basic = HTTPBasic(auto_error=False)


def _ruta() -> Path:
    return Path(USUARIOS_DB_PATH or os.environ.get("COPILOTO_USUARIOS_DB") or RUTA_POR_DEFECTO)


def get_conn():
    ruta = _ruta()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    conn = adm.crear_conexion(str(ruta), check_same_thread=False)
    try:
        yield conn
    finally:
        conn.close()


def actor(credenciales: Optional[HTTPBasicCredentials] = Depends(_basic), conn: sqlite3.Connection = Depends(get_conn)) -> Usuario:
    """Quien hace la petición, autenticado con SEC-01. 401 si no puede."""
    desafio = {"WWW-Authenticate": "Basic"}
    if credenciales is None:
        raise HTTPException(status_code=401, detail="Se requieren credenciales.", headers=desafio)
    resultado = autenticar(conn, credenciales.username, credenciales.password)
    if not resultado.exito:
        raise HTTPException(status_code=401, detail=resultado.motivo_rechazo, headers=desafio)
    return resultado.usuario


# --- Esquemas ----------------------------------------------------------------


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UsuarioCreateSchema(_Entrada):
    nombre_usuario: str
    contrasena: str
    rol: str
    nombre_completo: str
    correo: Optional[str] = None


class UsuarioUpdateSchema(_Entrada):
    nombre_completo: Optional[str] = None
    correo: Optional[str] = None


class CambiarRolSchema(_Entrada):
    rol: str
    motivo: str


class DesactivarSchema(_Entrada):
    motivo: str


class RestablecerContrasenaSchema(_Entrada):
    contrasena_nueva: str


class UsuarioSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nombre_usuario: str
    rol: Rol
    activo: bool
    nombre_completo: Optional[str]
    correo: Optional[str]
    bloqueado: bool
    bloqueado_hasta: Optional[str]
    creado_en: Optional[str]
    creado_por: Optional[int]
    desactivado_en: Optional[str]
    motivo_desactivacion: Optional[str]


class RolPermisosSchema(BaseModel):
    rol: Rol
    permisos: List[str]


class EventoSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    fecha: str
    actor_id: int
    operacion: str
    resultado: str
    objetivo_id: Optional[int]
    detalle: dict


# --- Errores -----------------------------------------------------------------


def _errores(status: int, errores) -> JSONResponse:
    return JSONResponse(status_code=status, content={"errores": [{"campo": c, "mensaje": m} for c, m in errores]})


@app.exception_handler(RequestValidationError)
async def _validacion_de_entrada(_request, exc: RequestValidationError):
    return _errores(400, [(".".join(str(p) for p in e["loc"][1:]) or "datos", e["msg"]) for e in exc.errors()])


@app.exception_handler(adm.UsuarioDuplicadoError)
async def _duplicado(_request, exc):
    return _errores(409, exc.errores)


@app.exception_handler(adm.ErrorValidacion)
async def _invalido(_request, exc):
    return _errores(400, exc.errores)


@app.exception_handler(adm.PermisoDenegadoError)
async def _denegado(_request, exc):
    return JSONResponse(status_code=403, content={"detail": str(exc)})


@app.exception_handler(adm.UsuarioNoEncontradoError)
async def _no_encontrado(_request, exc):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(adm.OperacionNoPermitidaError)
async def _no_permitida(_request, exc):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


# --- Endpoints ---------------------------------------------------------------

_R = {401: {"description": "Credenciales ausentes o incorrectas, o cuenta bloqueada"},
      403: {"description": "El usuario autenticado no es administrador (queda auditado)"}}


@app.post("/usuarios", response_model=UsuarioSchema, status_code=201, responses=_R, summary="ADM-01: crear un usuario")
def crear(payload: UsuarioCreateSchema, quien: Usuario = Depends(actor), conn: sqlite3.Connection = Depends(get_conn)):
    return adm.crear_usuario(conn, quien, payload.nombre_usuario, payload.contrasena, payload.rol,
                             payload.nombre_completo, payload.correo)


@app.get("/usuarios", response_model=List[UsuarioSchema], responses=_R, summary="ADM-01: listar usuarios (filtros opcionales)")
def listar(
    rol: Optional[str] = Query(None), activo: Optional[bool] = Query(None), texto: Optional[str] = Query(None),
    quien: Usuario = Depends(actor), conn: sqlite3.Connection = Depends(get_conn),
):
    return adm.listar_usuarios(conn, quien, rol=rol, activo=activo, texto=texto)


@app.get("/usuarios/{usuario_id}", response_model=UsuarioSchema, responses=_R, summary="ADM-01: ver un usuario")
def ver(usuario_id: int, quien: Usuario = Depends(actor), conn: sqlite3.Connection = Depends(get_conn)):
    return adm.obtener_usuario(conn, quien, usuario_id)


@app.patch("/usuarios/{usuario_id}", response_model=UsuarioSchema, responses=_R, summary="ADM-01: editar nombre completo y/o correo")
def editar(usuario_id: int, payload: UsuarioUpdateSchema, quien: Usuario = Depends(actor), conn: sqlite3.Connection = Depends(get_conn)):
    return adm.actualizar_usuario(conn, quien, usuario_id, **payload.model_dump(exclude_unset=True))


@app.put("/usuarios/{usuario_id}/rol", response_model=UsuarioSchema, responses=_R, summary="ADM-01: asignar un rol (y con él sus permisos)")
def cambiar_rol(usuario_id: int, payload: CambiarRolSchema, quien: Usuario = Depends(actor), conn: sqlite3.Connection = Depends(get_conn)):
    return adm.asignar_rol(conn, quien, usuario_id, payload.rol, payload.motivo)


@app.post("/usuarios/{usuario_id}/desactivar", response_model=UsuarioSchema, responses=_R, summary="ADM-01: baja lógica de un usuario")
def desactivar(usuario_id: int, payload: DesactivarSchema, quien: Usuario = Depends(actor), conn: sqlite3.Connection = Depends(get_conn)):
    return adm.desactivar_usuario(conn, quien, usuario_id, payload.motivo)


@app.post("/usuarios/{usuario_id}/reactivar", response_model=UsuarioSchema, responses=_R, summary="ADM-01: reactivar un usuario")
def reactivar(usuario_id: int, quien: Usuario = Depends(actor), conn: sqlite3.Connection = Depends(get_conn)):
    return adm.reactivar_usuario(conn, quien, usuario_id)


@app.post("/usuarios/{usuario_id}/contrasena", response_model=UsuarioSchema, responses=_R,
          summary="ADM-01: restablecer la contraseña (levanta el bloqueo)")
def restablecer(usuario_id: int, payload: RestablecerContrasenaSchema, quien: Usuario = Depends(actor), conn: sqlite3.Connection = Depends(get_conn)):
    return adm.restablecer_contrasena(conn, quien, usuario_id, payload.contrasena_nueva)


@app.get("/roles", response_model=List[RolPermisosSchema], responses=_R, summary="ADM-01: qué permisos da cada rol")
def roles(quien: Usuario = Depends(actor), conn: sqlite3.Connection = Depends(get_conn)):
    return [RolPermisosSchema(rol=rol, permisos=[a.value for a in acciones])
            for rol, acciones in adm.matriz_de_permisos(conn, quien).items()]


@app.get("/auditoria/usuarios", response_model=List[EventoSchema], responses=_R,
         summary="ADM-01: historial de gestión de usuarios (AUD-01), de todos o de uno")
def auditoria(usuario_id: Optional[int] = Query(None), quien: Usuario = Depends(actor), conn: sqlite3.Connection = Depends(get_conn)):
    return adm.eventos_de_administracion(conn, quien, usuario_id=usuario_id)
