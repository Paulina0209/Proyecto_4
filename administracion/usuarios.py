"""ADM-01 — Gestión de usuarios, roles y permisos.

Como administrador del sistema, quiero gestionar usuarios, roles y permisos,
para mantener el control de acceso institucional.

Qué hace: alta, consulta, listado, edición, cambio de rol, baja lógica
(desactivar/reactivar) y restablecimiento de contraseña de los usuarios
institucionales de SEC-01, y muestra qué puede hacer cada rol.

Decisiones de diseño:

    - Quién puede: solo el rol ``administrador`` (``Accion.GESTIONAR_USUARIOS``,
      fail-closed como el resto de SEC-01). Cada función recibe al ``actor``
      y lo vuelve a leer de la base: un administrador desactivado o con otro
      rol ya no puede operar aunque conserve el objeto ``Usuario``.
    - Los permisos son los del rol (``seguridad.autorizacion.PERMISOS_POR_ROL``),
      una sola tabla y una sola fuente de verdad. Asignar un rol es asignar
      sus permisos; no hay permisos sueltos por usuario (el menor privilegio
      se audita por rol, no persona por persona).
    - No se borra a nadie: "eliminar" es desactivar (baja lógica). Los
      eventos de auditoría (AUD-01) y las decisiones clínicas (TX-04, EST-02,
      DX-03) guardan el id del usuario y deben seguir resolviéndose.
    - Salvaguardas contra quedarse sin acceso: nadie cambia su propio rol ni
      se desactiva a sí mismo, y nunca se puede dejar al sistema sin al menos
      un administrador activo. El primero se crea con
      ``crear_primer_administrador`` (solo si aún no hay ninguno).
    - Cada operación (y cada intento denegado) queda en AUD-01 con quién, qué
      y sobre quién. Nunca se registra una contraseña ni su hash. El cambio y
      su evento de auditoría se confirman juntos o ninguno.
    - Cambiar el rol y desactivar exigen un motivo.
    - El nombre de usuario (el de inicio de sesión) no se edita: lo
      referencian los registros históricos.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from auditoria.models import TipoAccion
from auditoria.registro_acceso import inicializar_schema as inicializar_schema_auditoria
from auditoria.registro_acceso import registrar_acceso
from seguridad.autenticacion import establecer_contrasena
from seguridad.autenticacion import inicializar_esquema as inicializar_esquema_usuarios
from seguridad.autenticacion import insertar_usuario
from seguridad.autorizacion import Accion, permisos_del_rol, verificar_permiso
from seguridad.models import Rol, Usuario

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema_administracion.sql"

LARGO_MINIMO_CONTRASENA = 10
_USUARIO_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
_CORREO_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ErrorAdministracion(Exception):
    """Base de los errores de esta historia."""


class ErrorValidacion(ErrorAdministracion):
    """Datos inválidos: ``errores`` trae todos a la vez, ``(campo, mensaje)``."""

    def __init__(self, errores: List[Tuple[str, str]]):
        self.errores = errores
        super().__init__("; ".join(f"{campo}: {mensaje}" for campo, mensaje in errores))


class UsuarioDuplicadoError(ErrorValidacion):
    """El nombre de usuario o el correo ya los usa otra persona."""


class PermisoDenegadoError(ErrorAdministracion):
    """El actor no puede gestionar usuarios."""


class UsuarioNoEncontradoError(ErrorAdministracion):
    pass


class OperacionNoPermitidaError(ErrorAdministracion):
    """Válida en sí misma, pero dejaría al sistema sin acceso administrativo."""


@dataclass(frozen=True)
class UsuarioAdmin:
    """Un usuario tal como lo ve el administrador. Nunca trae hash ni sal."""

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


@dataclass(frozen=True)
class EventoAdministracion:
    id: int
    fecha: str
    actor_id: int
    operacion: str
    #: ``ok`` o ``denegado``.
    resultado: str
    objetivo_id: Optional[int]
    detalle: Dict[str, Any]


# --------------------------------------------------------------------------
# Conexión
# --------------------------------------------------------------------------


def inicializar_esquema(conn: sqlite3.Connection) -> None:
    """Usuarios (SEC-01), auditoría (AUD-01) y perfiles (ADM-01). Idempotente."""
    inicializar_esquema_usuarios(conn)
    inicializar_schema_auditoria(conn)
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def crear_conexion(ruta: str = ":memory:", *, check_same_thread: bool = True) -> sqlite3.Connection:
    conn = sqlite3.connect(ruta, check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    inicializar_esquema(conn)
    return conn


# --------------------------------------------------------------------------
# Validaciones
# --------------------------------------------------------------------------


def validar_contrasena(contrasena: str, nombre_usuario: str = "") -> List[str]:
    """Problemas de una contraseña (vacío = cumple la política)."""
    problemas = []
    contrasena = contrasena or ""
    if len(contrasena) < LARGO_MINIMO_CONTRASENA:
        problemas.append(f"Debe tener al menos {LARGO_MINIMO_CONTRASENA} caracteres.")
    if not any(c.isalpha() for c in contrasena) or not any(c.isdigit() for c in contrasena):
        problemas.append("Debe combinar letras y números.")
    if nombre_usuario and nombre_usuario.lower() in contrasena.lower():
        problemas.append("No puede contener el nombre de usuario.")
    return problemas


def _como_rol(valor: Union[Rol, str, None], errores: List[Tuple[str, str]]) -> Optional[Rol]:
    if isinstance(valor, Rol):
        return valor
    try:
        return Rol(valor)
    except ValueError:
        validos = ", ".join(r.value for r in Rol)
        errores.append(("rol", f"Rol desconocido '{valor}'. Los roles válidos son: {validos}."))
        return None


def _motivo(motivo: Optional[str], errores: List[Tuple[str, str]]) -> str:
    motivo = (motivo or "").strip()
    if not motivo:
        errores.append(("motivo", "El motivo es obligatorio."))
    return motivo


def _correo(correo: Optional[str], errores: List[Tuple[str, str]]) -> Optional[str]:
    correo = (correo or "").strip().lower()
    if not correo:
        return None
    if not _CORREO_RE.match(correo):
        errores.append(("correo", "El correo no tiene un formato válido."))
    return correo


def _nombre_completo(valor: Optional[str], errores: List[Tuple[str, str]]) -> str:
    valor = " ".join((valor or "").split())
    if not 3 <= len(valor) <= 120:
        errores.append(("nombre_completo", "El nombre completo debe tener entre 3 y 120 caracteres."))
    return valor


# --------------------------------------------------------------------------
# Acceso y auditoría
# --------------------------------------------------------------------------


def _json(datos: Dict[str, Any]) -> str:
    return json.dumps(datos, ensure_ascii=False, sort_keys=True)


def _auditar(
    conn: sqlite3.Connection, actor_id: int, operacion: str, resultado: str, ahora: Optional[datetime],
    objetivo_id: Optional[int] = None, **datos: Any,
) -> None:
    """Escribe el evento en AUD-01 (hace commit, junto con lo pendiente)."""
    detalle = {"operacion": operacion, "resultado": resultado, "objetivo_id": objetivo_id, **datos}
    registrar_acceso(conn, actor_id, TipoAccion.GESTIONAR_USUARIOS, detalle=_json(detalle), ahora=ahora)


def _verificar_actor(
    conn: sqlite3.Connection, actor: Usuario, operacion: str, ahora: Optional[datetime], objetivo_id: Optional[int] = None
) -> Usuario:
    """El actor vigente (releído de la base) o ``PermisoDenegadoError``. El
    intento denegado también queda auditado."""
    fila = conn.execute("SELECT id, nombre_usuario, rol, activo FROM usuarios WHERE id = ?", (actor.id,)).fetchone()
    vigente = None
    if fila is not None:
        try:
            vigente = Usuario(fila["id"], fila["nombre_usuario"], Rol(fila["rol"]), bool(fila["activo"]))
        except ValueError:
            vigente = None
    veredicto = verificar_permiso(vigente, Accion.GESTIONAR_USUARIOS) if vigente else None
    if veredicto is None or not veredicto.permitido:
        motivo = veredicto.motivo_rechazo if veredicto else "El usuario no existe."
        _auditar(conn, actor.id, operacion, "denegado", ahora, objetivo_id, motivo=motivo)
        raise PermisoDenegadoError(motivo)
    return vigente


def _fila_usuario(conn: sqlite3.Connection, usuario_id: int, ahora: Optional[datetime] = None) -> UsuarioAdmin:
    fila = conn.execute(_SELECT_USUARIO + " WHERE u.id = ?", (usuario_id,)).fetchone()
    if fila is None:
        raise UsuarioNoEncontradoError(f"No existe ningún usuario con id={usuario_id}.")
    return _a_usuario_admin(fila, ahora)


_SELECT_USUARIO = (
    "SELECT u.id, u.nombre_usuario, u.rol, u.activo, u.bloqueado_hasta, p.nombre_completo, p.correo, "
    "p.creado_en, p.creado_por, p.desactivado_en, p.motivo_desactivacion "
    "FROM usuarios u LEFT JOIN perfiles_usuario p ON p.usuario_id = u.id"
)


def _a_usuario_admin(fila: sqlite3.Row, ahora: Optional[datetime] = None) -> UsuarioAdmin:
    ahora = ahora or datetime.now(timezone.utc)
    hasta = fila["bloqueado_hasta"]
    return UsuarioAdmin(
        id=fila["id"], nombre_usuario=fila["nombre_usuario"], rol=Rol(fila["rol"]), activo=bool(fila["activo"]),
        nombre_completo=fila["nombre_completo"], correo=fila["correo"],
        bloqueado=bool(hasta and datetime.fromisoformat(hasta) > ahora), bloqueado_hasta=hasta,
        creado_en=fila["creado_en"], creado_por=fila["creado_por"],
        desactivado_en=fila["desactivado_en"], motivo_desactivacion=fila["motivo_desactivacion"],
    )


def _administradores_activos(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM usuarios WHERE rol = ? AND activo = 1", (Rol.ADMINISTRADOR.value,)
    ).fetchone()[0]


def _asegurar_perfil(conn: sqlite3.Connection, usuario_id: int, momento: str) -> None:
    """Los usuarios dados de alta solo con ``registrar_usuario`` no tienen perfil."""
    conn.execute(
        "INSERT OR IGNORE INTO perfiles_usuario (usuario_id, creado_en) VALUES (?, ?)", (usuario_id, momento)
    )


def _confirmar(conn: sqlite3.Connection, actor_id: int, operacion: str, ahora: Optional[datetime],
               objetivo_id: Optional[int], **datos: Any) -> None:
    """Audita y confirma lo pendiente en una sola transacción; si la auditoría
    falla, se deshace el cambio."""
    try:
        _auditar(conn, actor_id, operacion, "ok", ahora, objetivo_id, **datos)
    except Exception:
        conn.rollback()
        raise


# --------------------------------------------------------------------------
# Operaciones
# --------------------------------------------------------------------------


def _alta(
    conn: sqlite3.Connection, creador_id: Optional[int], nombre_usuario: str, contrasena: str,
    rol: Union[Rol, str], nombre_completo: str, correo: Optional[str], ahora: Optional[datetime],
) -> int:
    """Valida e inserta (sin confirmar). Devuelve el id nuevo."""
    errores: List[Tuple[str, str]] = []
    nombre_usuario = (nombre_usuario or "").strip()
    if not _USUARIO_RE.match(nombre_usuario):
        errores.append((
            "nombre_usuario",
            "Debe tener entre 3 y 32 caracteres: minúsculas, números, punto, guion o guion bajo, y empezar por letra o número.",
        ))
    rol_ = _como_rol(rol, errores)
    nombre_completo = _nombre_completo(nombre_completo, errores)
    correo = _correo(correo, errores)
    errores += [("contrasena", p) for p in validar_contrasena(contrasena, nombre_usuario)]
    if errores:
        raise ErrorValidacion(errores)

    if conn.execute("SELECT 1 FROM usuarios WHERE lower(nombre_usuario) = ?", (nombre_usuario,)).fetchone():
        raise UsuarioDuplicadoError([("nombre_usuario", f"Ya existe un usuario '{nombre_usuario}'.")])
    if correo and conn.execute("SELECT 1 FROM perfiles_usuario WHERE lower(correo) = ?", (correo,)).fetchone():
        raise UsuarioDuplicadoError([("correo", "Ya hay un usuario con ese correo.")])

    momento = (ahora or datetime.now(timezone.utc)).isoformat()
    creado = insertar_usuario(conn, nombre_usuario, contrasena, rol_)  # sin commit: se confirma con la auditoría
    conn.execute(
        "INSERT INTO perfiles_usuario (usuario_id, nombre_completo, correo, creado_en, creado_por) VALUES (?, ?, ?, ?, ?)",
        (creado.id, nombre_completo, correo, momento, creador_id if creador_id is not None else creado.id),
    )
    return creado.id


def crear_usuario(
    conn: sqlite3.Connection, actor: Usuario, nombre_usuario: str, contrasena: str, rol: Union[Rol, str],
    nombre_completo: str, correo: Optional[str] = None, *, ahora: Optional[datetime] = None,
) -> UsuarioAdmin:
    """Alta de un usuario institucional con su rol."""
    actor = _verificar_actor(conn, actor, "crear_usuario", ahora)
    try:
        nuevo_id = _alta(conn, actor.id, nombre_usuario, contrasena, rol, nombre_completo, correo, ahora)
    except sqlite3.IntegrityError as exc:  # carrera con otra alta del mismo usuario o correo
        conn.rollback()
        raise UsuarioDuplicadoError([("nombre_usuario", "El usuario o el correo ya existen.")]) from exc
    creado = _fila_usuario(conn, nuevo_id, ahora)
    _confirmar(conn, actor.id, "crear_usuario", ahora, nuevo_id,
               nombre_usuario=creado.nombre_usuario, rol=creado.rol.value, correo=creado.correo)
    return creado


def crear_primer_administrador(
    conn: sqlite3.Connection, nombre_usuario: str, contrasena: str, nombre_completo: str,
    correo: Optional[str] = None, *, ahora: Optional[datetime] = None,
) -> UsuarioAdmin:
    """Arranque: crea el primer administrador. Solo funciona si todavía no hay
    ninguno activo (después, los crea un administrador con ``crear_usuario``)."""
    if _administradores_activos(conn):
        raise OperacionNoPermitidaError(
            "Ya existe un administrador activo: los nuevos usuarios los crea un administrador."
        )
    try:
        nuevo_id = _alta(conn, None, nombre_usuario, contrasena, Rol.ADMINISTRADOR, nombre_completo, correo, ahora)
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise UsuarioDuplicadoError([("nombre_usuario", "El usuario o el correo ya existen.")]) from exc
    creado = _fila_usuario(conn, nuevo_id, ahora)
    _confirmar(conn, creado.id, "crear_primer_administrador", ahora, creado.id, nombre_usuario=creado.nombre_usuario)
    return creado


def obtener_usuario(conn: sqlite3.Connection, actor: Usuario, usuario_id: int, *, ahora: Optional[datetime] = None) -> UsuarioAdmin:
    _verificar_actor(conn, actor, "obtener_usuario", ahora, usuario_id)
    return _fila_usuario(conn, usuario_id, ahora)


def listar_usuarios(
    conn: sqlite3.Connection, actor: Usuario, *, rol: Union[Rol, str, None] = None,
    activo: Optional[bool] = None, texto: Optional[str] = None, ahora: Optional[datetime] = None,
) -> List[UsuarioAdmin]:
    """Usuarios por nombre de usuario, con filtros opcionales por rol, estado y texto
    (nombre de usuario, nombre completo o correo)."""
    _verificar_actor(conn, actor, "listar_usuarios", ahora)
    condiciones, params = [], []
    if rol is not None:
        errores: List[Tuple[str, str]] = []
        rol_ = _como_rol(rol, errores)
        if errores:
            raise ErrorValidacion(errores)
        condiciones.append("u.rol = ?")
        params.append(rol_.value)
    if activo is not None:
        condiciones.append("u.activo = ?")
        params.append(1 if activo else 0)
    if texto and texto.strip():
        patron = "%" + texto.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        condiciones.append(
            "(lower(u.nombre_usuario) LIKE ? ESCAPE '\\' OR lower(COALESCE(p.nombre_completo, '')) LIKE ? ESCAPE '\\' "
            "OR lower(COALESCE(p.correo, '')) LIKE ? ESCAPE '\\')"
        )
        params += [patron] * 3
    consulta = _SELECT_USUARIO + (" WHERE " + " AND ".join(condiciones) if condiciones else "") + " ORDER BY u.nombre_usuario"
    return [_a_usuario_admin(f, ahora) for f in conn.execute(consulta, params).fetchall()]


def actualizar_usuario(
    conn: sqlite3.Connection, actor: Usuario, usuario_id: int, *, nombre_completo: Optional[str] = None,
    correo: Optional[str] = None, ahora: Optional[datetime] = None,
) -> UsuarioAdmin:
    """Edita el nombre completo y/o el correo. Lo que no se envía no cambia;
    un correo vacío lo borra. El nombre de usuario y el rol no se cambian aquí."""
    actor = _verificar_actor(conn, actor, "actualizar_usuario", ahora, usuario_id)
    antes = _fila_usuario(conn, usuario_id, ahora)
    errores: List[Tuple[str, str]] = []
    nuevo_nombre = _nombre_completo(nombre_completo, errores) if nombre_completo is not None else antes.nombre_completo
    nuevo_correo = _correo(correo, errores) if correo is not None else antes.correo
    if nombre_completo is None and correo is None:
        errores.append(("datos", "No se indicó nada que cambiar."))
    if errores:
        raise ErrorValidacion(errores)
    if nuevo_correo and nuevo_correo != antes.correo and conn.execute(
        "SELECT 1 FROM perfiles_usuario WHERE lower(correo) = ? AND usuario_id <> ?", (nuevo_correo, usuario_id)
    ).fetchone():
        raise UsuarioDuplicadoError([("correo", "Ya hay un usuario con ese correo.")])

    momento = (ahora or datetime.now(timezone.utc)).isoformat()
    _asegurar_perfil(conn, usuario_id, momento)
    try:
        conn.execute(
            "UPDATE perfiles_usuario SET nombre_completo = ?, correo = ?, actualizado_en = ? WHERE usuario_id = ?",
            (nuevo_nombre, nuevo_correo, momento, usuario_id),
        )
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise UsuarioDuplicadoError([("correo", "Ya hay un usuario con ese correo.")]) from exc
    cambios = {}
    if nuevo_nombre != antes.nombre_completo:
        cambios["nombre_completo"] = [antes.nombre_completo, nuevo_nombre]
    if nuevo_correo != antes.correo:
        cambios["correo"] = [antes.correo, nuevo_correo]
    _confirmar(conn, actor.id, "actualizar_usuario", ahora, usuario_id, cambios=cambios)
    return _fila_usuario(conn, usuario_id, ahora)


def asignar_rol(
    conn: sqlite3.Connection, actor: Usuario, usuario_id: int, rol: Union[Rol, str], motivo: str,
    *, ahora: Optional[datetime] = None,
) -> UsuarioAdmin:
    """Cambia el rol de un usuario (y con él sus permisos). Exige motivo."""
    actor = _verificar_actor(conn, actor, "asignar_rol", ahora, usuario_id)
    antes = _fila_usuario(conn, usuario_id, ahora)
    errores: List[Tuple[str, str]] = []
    nuevo = _como_rol(rol, errores)
    motivo = _motivo(motivo, errores)
    if errores:
        raise ErrorValidacion(errores)
    if nuevo == antes.rol:
        raise ErrorValidacion([("rol", f"El usuario ya tiene el rol '{nuevo.value}'.")])
    if usuario_id == actor.id:
        raise OperacionNoPermitidaError("No puedes cambiar tu propio rol: pídelo a otro administrador.")
    if antes.rol == Rol.ADMINISTRADOR and antes.activo and nuevo != Rol.ADMINISTRADOR and _administradores_activos(conn) <= 1:
        raise OperacionNoPermitidaError("No se puede quitar el rol al último administrador activo.")

    conn.execute("UPDATE usuarios SET rol = ? WHERE id = ?", (nuevo.value, usuario_id))
    _asegurar_perfil(conn, usuario_id, (ahora or datetime.now(timezone.utc)).isoformat())
    _confirmar(conn, actor.id, "asignar_rol", ahora, usuario_id,
               rol_anterior=antes.rol.value, rol_nuevo=nuevo.value, motivo=motivo)
    return _fila_usuario(conn, usuario_id, ahora)


def desactivar_usuario(
    conn: sqlite3.Connection, actor: Usuario, usuario_id: int, motivo: str, *, ahora: Optional[datetime] = None,
) -> UsuarioAdmin:
    """Baja lógica: ya no puede iniciar sesión ni operar, pero su historial se conserva."""
    actor = _verificar_actor(conn, actor, "desactivar_usuario", ahora, usuario_id)
    antes = _fila_usuario(conn, usuario_id, ahora)
    errores: List[Tuple[str, str]] = []
    motivo = _motivo(motivo, errores)
    if errores:
        raise ErrorValidacion(errores)
    if not antes.activo:
        raise ErrorValidacion([("usuario", "El usuario ya está desactivado.")])
    if usuario_id == actor.id:
        raise OperacionNoPermitidaError("No puedes desactivar tu propia cuenta: pídelo a otro administrador.")
    if antes.rol == Rol.ADMINISTRADOR and _administradores_activos(conn) <= 1:
        raise OperacionNoPermitidaError("No se puede desactivar al último administrador activo.")

    momento = (ahora or datetime.now(timezone.utc)).isoformat()
    conn.execute("UPDATE usuarios SET activo = 0 WHERE id = ?", (usuario_id,))
    _asegurar_perfil(conn, usuario_id, momento)
    conn.execute(
        "UPDATE perfiles_usuario SET desactivado_en = ?, motivo_desactivacion = ? WHERE usuario_id = ?",
        (momento, motivo, usuario_id),
    )
    _confirmar(conn, actor.id, "desactivar_usuario", ahora, usuario_id, motivo=motivo)
    return _fila_usuario(conn, usuario_id, ahora)


def reactivar_usuario(
    conn: sqlite3.Connection, actor: Usuario, usuario_id: int, *, ahora: Optional[datetime] = None,
) -> UsuarioAdmin:
    actor = _verificar_actor(conn, actor, "reactivar_usuario", ahora, usuario_id)
    antes = _fila_usuario(conn, usuario_id, ahora)
    if antes.activo:
        raise ErrorValidacion([("usuario", "El usuario ya está activo.")])
    conn.execute(
        "UPDATE usuarios SET activo = 1, intentos_fallidos = 0, bloqueado_hasta = NULL WHERE id = ?", (usuario_id,)
    )
    conn.execute(
        "UPDATE perfiles_usuario SET desactivado_en = NULL, motivo_desactivacion = NULL WHERE usuario_id = ?",
        (usuario_id,),
    )
    _confirmar(conn, actor.id, "reactivar_usuario", ahora, usuario_id)
    return _fila_usuario(conn, usuario_id, ahora)


def restablecer_contrasena(
    conn: sqlite3.Connection, actor: Usuario, usuario_id: int, contrasena_nueva: str, *, ahora: Optional[datetime] = None,
) -> UsuarioAdmin:
    """Fija una contraseña nueva y levanta el bloqueo por intentos fallidos. La
    contraseña no se guarda ni se audita (solo que hubo un restablecimiento)."""
    actor = _verificar_actor(conn, actor, "restablecer_contrasena", ahora, usuario_id)
    objetivo = _fila_usuario(conn, usuario_id, ahora)
    problemas = validar_contrasena(contrasena_nueva, objetivo.nombre_usuario)
    if problemas:
        raise ErrorValidacion([("contrasena", p) for p in problemas])
    establecer_contrasena(conn, usuario_id, contrasena_nueva)
    _confirmar(conn, actor.id, "restablecer_contrasena", ahora, usuario_id)
    return _fila_usuario(conn, usuario_id, ahora)


def matriz_de_permisos(conn: sqlite3.Connection, actor: Usuario, *, ahora: Optional[datetime] = None) -> Dict[Rol, Tuple[Accion, ...]]:
    """Qué puede hacer cada rol (los permisos que recibe quien lo tenga asignado)."""
    _verificar_actor(conn, actor, "ver_permisos", ahora)
    return {rol: permisos_del_rol(rol) for rol in Rol}


def eventos_de_administracion(
    conn: sqlite3.Connection, actor: Usuario, *, usuario_id: Optional[int] = None, ahora: Optional[datetime] = None,
) -> List[EventoAdministracion]:
    """Historial de gestión de usuarios en AUD-01 (más reciente primero), de todos o de un usuario."""
    _verificar_actor(conn, actor, "ver_auditoria_usuarios", ahora, usuario_id)
    filas = conn.execute(
        "SELECT * FROM eventos_acceso WHERE accion = ? ORDER BY id DESC", (TipoAccion.GESTIONAR_USUARIOS.value,)
    ).fetchall()
    eventos = []
    for fila in filas:
        try:
            detalle = json.loads(fila["detalle"] or "{}")
        except ValueError:
            continue
        if usuario_id is not None and detalle.get("objetivo_id") != usuario_id:
            continue
        eventos.append(EventoAdministracion(
            id=fila["id"], fecha=fila["fecha"], actor_id=fila["usuario_id"],
            operacion=detalle.get("operacion", ""), resultado=detalle.get("resultado", ""),
            objetivo_id=detalle.get("objetivo_id"), detalle=detalle,
        ))
    return eventos
