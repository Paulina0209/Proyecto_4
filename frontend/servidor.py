"""Pasarela web del copiloto oncológico: páginas estáticas + sesión SEC-01 + APIs existentes detrás de permisos.

    python -m frontend.demo                                                   # demo con datos sintéticos
    python -m seguridad.servidor_tls --app frontend.servidor:app --cert cert.pem --key clave.pem

Qué hace y qué no:

    - Sirve la interfaz (``frontend/estatico``: HTML + CSS + JS sin compilar) bajo una política CSP
      estricta (solo recursos propios; sin ``unsafe-inline``).
    - Autentica con SEC-01 (``autenticar``: el bloqueo por intentos fallidos aplica igual) y abre una
      sesión con cookie ``__Host-`` HttpOnly, Secure y SameSite=Strict (``frontend.sesiones``).
    - Monta la API de pacientes SIN modificarla (``/api/pacientes/...``). Antes de cada petición:
      exige sesión, comprueba el permiso por rol (``verificar_permiso``, fail-closed), descarta
      cualquier ``oncologo_id``/``usuario_id`` que mande el navegador y pone los de la sesión
      (resuelve el ``TODO(SEC-01)`` de la API de pacientes para este camino de acceso), y solo deja
      pasar una lista cerrada de rutas (nada de ``/docs``, altas ni ediciones).
    - Muestra el tablero ADM-02 (``/panel/metricas``) con la sesión, para el rol director médico.
    - Exporta el expediente (DOC-02) a HTML accesible o PDF (``/api/pacientes/{id}/exportar``).

Limitación consciente: en esta versión solo el rol ``oncologo`` ve expedientes. Enfermería y auditoría
tienen permiso ``ver_expediente`` en SEC-01, pero el modelo de datos aún no dice a qué oncólogo asiste
cada una (no hay asignación de pacientes); mientras no exista, se les niega en vez de adivinar.
"""
from __future__ import annotations

import json
import re
import sqlite3
import tempfile
from contextlib import asynccontextmanager, contextmanager
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from administracion import metricas_uso as met
from administracion import usuarios as adm
from administracion.panel_metricas import renderizar_error, renderizar_panel
from auditoria.models import TipoAccion
from auditoria.registro_acceso import registrar_acceso
from frontend.sesiones import AlmacenSesiones, almacen_por_defecto
from operacion import salud
from operacion.latencia import MedicionLatenciaMiddleware
from seguridad.autenticacion import autenticar
from seguridad.autorizacion import Accion, permisos_del_rol, verificar_permiso
from seguridad.models import Rol, Usuario
from seguridad.tls import SoloHTTPSMiddleware

CARPETA_ESTATICA = Path(__file__).resolve().parent / "estatico"
NOMBRE_COOKIE = "__Host-copiloto_sesion"
#: Cabecera que el JavaScript propio pone en toda petición que cambia algo: una página de otro sitio no
#: puede mandarla sin permiso previo (CORS), así que sirve de defensa contra CSRF además de SameSite=Strict.
CABECERA_SOLICITUD = b"x-copiloto-solicitud"

CSP_APP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
    "frame-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
)
#: El tablero ADM-02 trae su script y estilos en línea; se mantiene su política y solo se permite que
#: lo incruste esta misma página (``frame-ancestors 'self'``).
CSP_TABLERO = (
    "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; "
    "form-action 'self'; frame-ancestors 'self'; base-uri 'none'"
)
CSP_DESCARGA = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'none'; base-uri 'none'"
CSP_POR_DEFECTO = "default-src 'none'; frame-ancestors 'none'"

ETIQUETAS_ROL = {
    Rol.ONCOLOGO: "Oncología",
    Rol.ENFERMERIA: "Enfermería",
    Rol.ADMINISTRATIVO: "Administrativo",
    Rol.AUDITOR: "Auditoría",
    Rol.ADMINISTRADOR_CLINICO: "Administración clínica",
    Rol.ADMINISTRADOR: "Administración del sistema",
    Rol.DIRECTOR_MEDICO: "Dirección médica",
}

MENSAJE_SIN_ASIGNACION = (
    "Tu rol no tiene pantallas de expediente en esta versión: el sistema todavía no registra a qué "
    "oncólogo asiste cada persona, y por seguridad no se muestran pacientes sin esa asignación."
)


# ---------------------------------------------------------------------------
# Rutas de pacientes que la interfaz puede usar (lista cerrada)
# ---------------------------------------------------------------------------

class _Regla:
    def __init__(self, metodo: str, patron: str, accion: Accion, reescribe: Optional[str] = None, con: str = "nombre_usuario") -> None:
        self.metodo = metodo
        self.patron = re.compile(patron)
        self.accion = accion
        #: Campo del cuerpo JSON que la pasarela fija con la identidad de la sesión (no confía en el navegador).
        self.reescribe = reescribe
        #: Con qué se fija: "nombre_usuario" (quién revisó/confirmó) o "id" (oncólogo a cargo).
        self.con = con


_LECTURAS_DEL_PACIENTE = (
    "resumen-360|diagnosticos|tratamientos|consultas|alertas-laboratorio|conflictos-laboratorio|episodios|"
    "biopsias|biomarcadores|laboratorios/marcadores|laboratorios/tendencia|imagenes|imagenes/consultas|"
    "consentimiento-ia"
)
REGLAS_PACIENTES: Tuple[_Regla, ...] = (
    _Regla("GET", r"/pacientes", Accion.VER_EXPEDIENTE),
    _Regla("GET", r"/pacientes/buscar", Accion.VER_EXPEDIENTE),
    _Regla("GET", r"/pacientes/\d+", Accion.VER_EXPEDIENTE),
    _Regla("GET", r"/pacientes/\d+/(" + _LECTURAS_DEL_PACIENTE + ")", Accion.VER_EXPEDIENTE),
    _Regla("GET", r"/pacientes/\d+/imagenes/[^/]+/visor", Accion.VER_EXPEDIENTE),
    _Regla("POST", r"/pacientes/\d+/alertas-laboratorio/\d+/revisar", Accion.EDITAR_EXPEDIENTE, reescribe="revisada_por"),
    # Escrituras que la interfaz completa también usa (el autor siempre sale de la sesión).
    _Regla("POST", r"/pacientes", Accion.EDITAR_EXPEDIENTE, reescribe="oncologo_id", con="id"),                    # PAC-01
    _Regla("POST", r"/pacientes/\d+/(diagnosticos|tratamientos|consultas)", Accion.EDITAR_EXPEDIENTE),            # PAC-02
    _Regla("POST", r"/pacientes/\d+/laboratorios", Accion.EDITAR_EXPEDIENTE),                                    # HC-02
    _Regla("POST", r"/pacientes/\d+/conflictos-laboratorio/\d+/resolver", Accion.EDITAR_EXPEDIENTE, reescribe="resuelto_por"),
    _Regla("POST", r"/pacientes/\d+/(episodios|biopsias|biomarcadores)", Accion.EDITAR_EXPEDIENTE),               # HC-04
    _Regla("POST", r"/pacientes/\d+/biomarcadores/\d+/confirmar", Accion.EDITAR_EXPEDIENTE, reescribe="confirmado_por"),
    _Regla("POST", r"/pacientes/\d+/biomarcadores/\d+/descartar", Accion.EDITAR_EXPEDIENTE, reescribe="revisado_por"),
    _Regla("POST", r"/pacientes/\d+/consentimiento-ia(/retiro)?", Accion.REGISTRAR_CONSENTIMIENTO_IA),            # SEC-03
)
_METODOS_SEGUROS = frozenset({"GET", "HEAD", "OPTIONS"})


def _ruta_relativa(scope: Dict[str, Any]) -> str:
    """Ruta dentro del sub-app montado (con las dos convenciones de Starlette para ``root_path``)."""
    ruta = scope.get("path", "")
    raiz = scope.get("root_path", "")
    if raiz and ruta.startswith(raiz):
        ruta = ruta[len(raiz):]
    return ruta or "/"


def _cabecera(scope: Dict[str, Any], nombre: bytes) -> Optional[bytes]:
    valor = None
    for k, v in scope.get("headers", []):
        if k.lower() == nombre:
            valor = v
    return valor


def _cookie_de_sesion(scope: Dict[str, Any]) -> Optional[str]:
    crudo = _cabecera(scope, b"cookie")
    if not crudo:
        return None
    galleta: SimpleCookie = SimpleCookie()
    try:
        galleta.load(crudo.decode("latin-1"))
    except CookieError:
        return None
    morsa = galleta.get(NOMBRE_COOKIE)
    return morsa.value if morsa else None


def _solicitud_legitima(scope: Dict[str, Any]) -> bool:
    """Para peticiones que cambian algo: cabecera propia presente y, si hay ``Origin``, del mismo sitio."""
    if _cabecera(scope, CABECERA_SOLICITUD) != b"1":
        return False
    origen = _cabecera(scope, b"origin")
    if origen is not None:
        sitio = _cabecera(scope, b"host") or b""
        if urlparse(origen.decode("latin-1")).netloc.lower() != sitio.decode("latin-1").lower():
            return False
    return True


async def _responder_json(send, estado: int, cuerpo: Dict[str, Any]) -> None:
    datos = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
    await send({"type": "http.response.start", "status": estado, "headers": [
        (b"content-type", b"application/json; charset=utf-8"), (b"content-length", str(len(datos)).encode("ascii")),
        (b"cache-control", b"no-store")]})
    await send({"type": "http.response.body", "body": datos})


class _AppConIdentidad:
    """ASGI: pone la identidad autenticada delante de la API de pacientes (que se monta sin cambios)."""

    def __init__(self, destino, pasarela: "Pasarela") -> None:
        self.destino = destino
        self.pasarela = pasarela

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            return
        metodo = scope["method"].upper()
        ruta = _ruta_relativa(scope)
        regla = next((r for r in REGLAS_PACIENTES + self.pasarela.reglas_extra if r.metodo == metodo and r.patron.fullmatch(ruta)), None)
        if regla is None:
            await _responder_json(send, 404, {"detail": "No existe esa ruta."})
            return
        usuario = self.pasarela.usuario_de(scope)
        if usuario is None:
            await _responder_json(send, 401, {"detail": "Inicia sesión para continuar."})
            return
        if metodo not in _METODOS_SEGUROS and not _solicitud_legitima(scope):
            await _responder_json(send, 403, {"detail": "Petición rechazada: no viene de esta aplicación."})
            return
        permiso = verificar_permiso(usuario, regla.accion)
        if not permiso.permitido:
            await _responder_json(send, 403, {"detail": permiso.motivo_rechazo})
            return
        if usuario.rol != Rol.ONCOLOGO:
            await _responder_json(send, 403, {"detail": MENSAJE_SIN_ASIGNACION})
            return

        # La identidad sale de la sesión; lo que mande el navegador con esos nombres se descarta.
        consulta = [(k, v) for k, v in parse_qsl(scope.get("query_string", b"").decode("latin-1"), keep_blank_values=True)
                    if k not in ("oncologo_id", "usuario_id")]
        consulta += [("oncologo_id", str(usuario.id)), ("usuario_id", str(usuario.id))]
        nuevo = dict(scope)
        nuevo["query_string"] = urlencode(consulta).encode("latin-1")
        recibir = receive
        if regla.reescribe:
            valor = usuario.id if regla.con == "id" else usuario.nombre_usuario
            recibir, nuevo = await self._con_cuerpo_fijado(nuevo, receive, regla.reescribe, valor)
        await self.destino(nuevo, recibir, send)

    @staticmethod
    async def _con_cuerpo_fijado(scope, receive, campo: str, valor):
        """Lee el cuerpo JSON, fija ``campo`` con la identidad de la sesión y lo entrega al API."""
        trozos: List[bytes] = []
        while True:
            mensaje = await receive()
            if mensaje["type"] != "http.request":
                break
            trozos.append(mensaje.get("body", b""))
            if not mensaje.get("more_body"):
                break
        crudo = b"".join(trozos)
        try:
            datos = json.loads(crudo or b"{}")
        except ValueError:
            datos = None
        if isinstance(datos, dict):
            datos[campo] = valor
            crudo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        cabeceras = [(k, v) for k, v in scope["headers"] if k.lower() != b"content-length"]
        cabeceras.append((b"content-length", str(len(crudo)).encode("ascii")))
        scope = {**scope, "headers": cabeceras}
        entregado = False

        async def recibir():
            nonlocal entregado
            if entregado:
                return {"type": "http.disconnect"}
            entregado = True
            return {"type": "http.request", "body": crudo, "more_body": False}

        return recibir, scope


class _CabecerasDeSeguridad:
    """ASGI: cabeceras que toda respuesta debe llevar si la ruta no puso las suyas."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def enviar(mensaje):
            if mensaje["type"] == "http.response.start":
                cabeceras = list(mensaje.get("headers") or [])
                presentes = {k.lower() for k, _v in cabeceras}
                for nombre, valor in (
                    (b"content-security-policy", CSP_POR_DEFECTO),
                    (b"x-content-type-options", "nosniff"),
                    (b"referrer-policy", "no-referrer"),
                    (b"cache-control", "no-store"),
                    (b"permissions-policy", "camera=(), microphone=(), geolocation=()"),
                ):
                    if nombre not in presentes:
                        cabeceras.append((nombre, valor.encode("ascii")))
                mensaje = {**mensaje, "headers": cabeceras}
            await send(mensaje)

        await self.app(scope, receive, enviar)


def _pagina_mensaje(titulo: str, mensaje: str, enlace: Optional[Tuple[str, str]] = None) -> str:
    """Página mínima y accesible para el marco del tablero (sesión caducada, sin permiso, error)."""
    import html

    boton = ""
    if enlace:
        boton = f'<p><a href="{html.escape(enlace[0], quote=True)}" target="_top">{html.escape(enlace[1])}</a></p>'
    return (
        '<!doctype html><html lang="es-MX"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(titulo)}</title><style>"
        "body{margin:0;font:1.0625rem/1.6 system-ui,-apple-system,'Segoe UI',sans-serif;background:#fff;color:#14233a}"
        "main{max-width:40rem;margin:0 auto;padding:2rem 1rem}h1{font-size:1.5rem;line-height:1.3}"
        "a{color:#0b4f9c;font-weight:600}a:focus-visible{outline:3px solid #0b57d0;outline-offset:2px}"
        "@media (prefers-color-scheme:dark){body{background:#0e1726;color:#e6edf7}a{color:#8ab4f8}}"
        f"</style></head><body><main id=\"contenido\"><h1>{html.escape(titulo)}</h1><p>{html.escape(mensaje)}</p>{boton}</main></body></html>"
    )


# ---------------------------------------------------------------------------
# La pasarela
# ---------------------------------------------------------------------------

class Pasarela:
    """Configuración y estado de una instancia de la interfaz (sesiones, bases, API de pacientes)."""

    def __init__(
        self,
        usuarios_db: Optional[Path] = None,
        patients_app=None,
        sesiones: Optional[AlmacenSesiones] = None,
        carpeta_estatica: Path = CARPETA_ESTATICA,
        metricas_db_paths: Optional[List[Path]] = None,
        fuentes_metricas: Optional[Callable[[], Any]] = None,  # fábrica de un context manager con ``FuentesMetricas``
        modo_demo: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._usuarios_db = usuarios_db
        self._patients_app = patients_app
        # NFR-05: con COPILOTO_SESIONES_DB, sesiones compartidas entre réplicas.
        self.sesiones = sesiones if sesiones is not None else almacen_por_defecto()
        #: Reglas de las rutas de HC-06 / CFG-02 que publique patients.api (frontend.extensiones).
        self.reglas_extra: Tuple[_Regla, ...] = ()
        self.carpeta_estatica = Path(carpeta_estatica)
        self._metricas_db_paths = metricas_db_paths
        self._fuentes_metricas = fuentes_metricas
        #: ``None`` en producción. En la demo: {"clave": ..., "usuarios": [{"usuario", "descripcion"}]}; la interfaz
        #: muestra el aviso de «datos inventados» y la lista de usuarios de prueba.
        self.modo_demo = modo_demo

    @property
    def patients_app(self):
        if self._patients_app is None:
            from patients.api import app as patients_app

            self._patients_app = patients_app
        return self._patients_app

    # --- Usuarios -----------------------------------------------------------------------------
    def _ruta_usuarios(self) -> Path:
        from administracion import api as adm_api
        import os

        return Path(self._usuarios_db or adm_api.USUARIOS_DB_PATH or os.environ.get("COPILOTO_USUARIOS_DB") or adm_api.RUTA_POR_DEFECTO)

    @contextmanager
    def conexion_usuarios(self) -> Iterator[sqlite3.Connection]:
        ruta = self._ruta_usuarios()
        ruta.parent.mkdir(parents=True, exist_ok=True)
        conn = adm.crear_conexion(str(ruta), check_same_thread=False)
        try:
            yield conn
        finally:
            conn.close()

    def _leer_usuario(self, usuario_id: int) -> Optional[Tuple[Usuario, Optional[str]]]:
        """El usuario tal como está AHORA en la base: una cuenta desactivada o con otro rol se nota en la siguiente petición."""
        with self.conexion_usuarios() as conn:
            fila = conn.execute(
                "SELECT u.id, u.nombre_usuario, u.rol, u.activo, p.nombre_completo FROM usuarios u "
                "LEFT JOIN perfiles_usuario p ON p.usuario_id = u.id WHERE u.id = ?", (usuario_id,)).fetchone()
        if fila is None or not fila["activo"]:
            return None
        try:
            rol = Rol(fila["rol"])
        except ValueError:
            return None
        return Usuario(fila["id"], fila["nombre_usuario"], rol, True), fila["nombre_completo"]

    def usuario_de(self, scope: Dict[str, Any]) -> Optional[Usuario]:
        resuelto = self.identidad_de(scope)
        return resuelto[0] if resuelto else None

    def identidad_de(self, scope: Dict[str, Any]) -> Optional[Tuple[Usuario, Optional[str]]]:
        token = _cookie_de_sesion(scope)
        usuario_id = self.sesiones.resolver(token)
        if usuario_id is None:
            return None
        encontrado = self._leer_usuario(usuario_id)
        if encontrado is None:
            self.sesiones.cerrar(token)
        return encontrado

    @staticmethod
    def cuerpo_de_sesion(usuario: Usuario, nombre_completo: Optional[str]) -> Dict[str, Any]:
        clinico = usuario.rol == Rol.ONCOLOGO
        return {
            "autenticado": True,
            "usuario": {"id": usuario.id, "nombre_usuario": usuario.nombre_usuario,
                        "nombre_completo": nombre_completo or usuario.nombre_usuario, "rol": usuario.rol.value,
                        "rol_etiqueta": ETIQUETAS_ROL.get(usuario.rol, usuario.rol.value)},
            "permisos": [a.value for a in permisos_del_rol(usuario.rol)],
            "acceso_clinico": clinico and verificar_permiso(usuario, Accion.VER_EXPEDIENTE).permitido,
            "puede_revisar_alertas": clinico and verificar_permiso(usuario, Accion.EDITAR_EXPEDIENTE).permitido,
            "puede_exportar": clinico and verificar_permiso(usuario, Accion.EXPORTAR_EXPEDIENTE).permitido,
            "ver_metricas": verificar_permiso(usuario, Accion.VER_METRICAS_USO).permitido,
            "puede_registrar": clinico and verificar_permiso(usuario, Accion.EDITAR_EXPEDIENTE).permitido,
            "puede_juicio_dx": clinico and verificar_permiso(usuario, Accion.REGISTRAR_JUICIO_DIAGNOSTICO).permitido,
            "puede_confirmar_estadio": clinico and verificar_permiso(usuario, Accion.CONFIRMAR_ESTADIFICACION).permitido,
            "puede_decidir_tratamiento": clinico and verificar_permiso(usuario, Accion.CONFIRMAR_TRATAMIENTO).permitido,
            "puede_consentimiento": clinico and verificar_permiso(usuario, Accion.REGISTRAR_CONSENTIMIENTO_IA).permitido,
            "ver_auditoria": verificar_permiso(usuario, Accion.VER_AUDITORIA).permitido,
            "gestionar_usuarios": verificar_permiso(usuario, Accion.GESTIONAR_USUARIOS).permitido,
            "configurar_guias": verificar_permiso(usuario, Accion.CONFIGURAR_GUIAS_INSTITUCIONALES).permitido,
            "ver_estado_sistema": verificar_permiso(usuario, Accion.VER_ESTADO_SISTEMA).permitido,
            "configurar_privacidad": verificar_permiso(usuario, Accion.CONFIGURAR_POLITICA_DATOS).permitido,
            "mensaje_sin_acceso_clinico": None if clinico else MENSAJE_SIN_ASIGNACION,
        }

    # --- Salud (NFR-02) -----------------------------------------------------------------------
    def verificaciones_salud(self) -> List[Any]:
        from frontend.sesiones import AlmacenSesionesSQLite
        from historia_clinica.db import ruta_expediente
        from patients import api as papi

        expediente = Path(papi.EXPEDIENTE_PATH or ruta_expediente())
        resultado = [
            salud.verificar_base("usuarios", self._ruta_usuarios()),
            salud.verificar_base("base de pacientes", Path(papi.DB_PATH)),
            salud.verificar_base("expediente clínico", expediente, critica=expediente.is_file()),
        ]
        if isinstance(self.sesiones, AlmacenSesionesSQLite):
            resultado.append(salud.verificar_base("sesiones compartidas", self.sesiones.ruta))
        return resultado + [salud.verificar_espacio(self._ruta_usuarios()), salud.verificar_modelo_ia(), salud.verificar_pacs()]

    # --- Métricas -----------------------------------------------------------------------------
    @contextmanager
    def fuentes_de_metricas(self, conn_usuarios: sqlite3.Connection) -> Iterator[Any]:
        if self._fuentes_metricas is not None:
            with self._fuentes_metricas() as fuentes:
                yield fuentes
            return
        from administracion import api as adm_api

        rutas = self._metricas_db_paths
        if rutas is None:
            rutas = adm_api.METRICAS_DB_PATHS if adm_api.METRICAS_DB_PATHS is not None else met.rutas_por_defecto()
        abiertas: List[sqlite3.Connection] = []
        try:
            for ruta in rutas:
                try:
                    abiertas.append(met.abrir_solo_lectura(Path(ruta)))
                except sqlite3.Error:
                    continue
            yield met.FuentesMetricas(conn_usuarios, abiertas)
        finally:
            for c in abiertas:
                c.close()

    # --- Aplicación ---------------------------------------------------------------------------
    def crear_app(self) -> FastAPI:
        if self._patients_app is None:
            from patients.api import app as patients_app

            self._patients_app = patients_app
        patients_app = self._patients_app
        from frontend import chat, clinica, extensiones, gestion

        self.reglas_extra = extensiones.reglas_extra(patients_app)

        @asynccontextmanager
        async def vida(_app: FastAPI):
            # Starlette no ejecuta el arranque de las apps montadas: aquí se hace el de pacientes
            # (esquemas de la base de pacientes y de auditoría). Las peticiones simultáneas ya no
            # necesitan ajuste aquí: patients.api abre su conexión apta para varios hilos (NFR-02).
            async with patients_app.router.lifespan_context(patients_app):
                yield

        app = FastAPI(title="Copiloto oncológico — interfaz web", docs_url=None, redoc_url=None, openapi_url=None, lifespan=vida)
        app.add_middleware(MedicionLatenciaMiddleware)  # NFR-01
        app.add_middleware(_CabecerasDeSeguridad)
        # NFR-02: la sonda de vida (sin datos) también responde por HTTP, para el balanceador.
        app.add_middleware(SoloHTTPSMiddleware, rutas_exentas=(salud.RUTA_VIVO,))
        pasarela = self
        app.include_router(salud.crear_router(pasarela.verificaciones_salud))

        # --- Páginas ---
        @app.get("/", include_in_schema=False)
        def inicio():
            return FileResponse(pasarela.carpeta_estatica / "index.html", media_type="text/html; charset=utf-8",
                                headers={"Content-Security-Policy": CSP_APP, "Cache-Control": "no-store"})

        @app.get("/favicon.ico", include_in_schema=False)
        def icono():
            return FileResponse(pasarela.carpeta_estatica / "icono.svg", media_type="image/svg+xml",
                                headers={"Cache-Control": "max-age=86400"})

        @app.get("/api/info", include_in_schema=False)
        def info():
            return {"modo_demo": pasarela.modo_demo is not None, "demo": pasarela.modo_demo}

        # --- Sesión ---
        @app.post("/api/sesion", include_in_schema=False)
        async def iniciar_sesion(request: Request):
            if not _solicitud_legitima(request.scope):
                return JSONResponse(status_code=403, content={"detail": "Petición rechazada: no viene de esta aplicación."})
            try:
                datos = await request.json()
            except ValueError:
                datos = None
            if not isinstance(datos, dict):
                datos = {}
            nombre = str(datos.get("usuario") or "").strip()
            contrasena = datos.get("contrasena")
            contrasena = contrasena if isinstance(contrasena, str) else ""
            errores = []
            if not nombre:
                errores.append({"campo": "usuario", "mensaje": "Escribe tu nombre de usuario."})
            if not contrasena:
                errores.append({"campo": "contrasena", "mensaje": "Escribe tu contraseña."})
            if errores:
                return JSONResponse(status_code=400, content={"detail": {"errores": errores}})
            with pasarela.conexion_usuarios() as conn:
                resultado = autenticar(conn, nombre, contrasena)
            if not resultado.exito:
                estado = 423 if resultado.cuenta_bloqueada else 401
                return JSONResponse(status_code=estado, content={"detail": resultado.motivo_rechazo})
            encontrado = pasarela._leer_usuario(resultado.usuario.id)
            if encontrado is None:
                return JSONResponse(status_code=401, content={"detail": "Usuario o contraseña incorrectos."})
            usuario, nombre_completo = encontrado
            token = pasarela.sesiones.abrir(usuario.id)
            respuesta = JSONResponse(pasarela.cuerpo_de_sesion(usuario, nombre_completo))
            respuesta.set_cookie(NOMBRE_COOKIE, token, httponly=True, secure=True, samesite="strict", path="/")
            return respuesta

        @app.get("/api/sesion", include_in_schema=False)
        def ver_sesion(request: Request):
            encontrado = pasarela.identidad_de(request.scope)
            if encontrado is None:
                # 200 y no 401: «no hay sesión» es el estado normal al abrir la página, no un error.
                return JSONResponse({"autenticado": False})
            return JSONResponse(pasarela.cuerpo_de_sesion(*encontrado))

        @app.delete("/api/sesion", include_in_schema=False)
        def cerrar_sesion(request: Request):
            if not _solicitud_legitima(request.scope):
                return JSONResponse(status_code=403, content={"detail": "Petición rechazada: no viene de esta aplicación."})
            pasarela.sesiones.cerrar(_cookie_de_sesion(request.scope))
            respuesta = Response(status_code=204)
            respuesta.delete_cookie(NOMBRE_COOKIE, path="/", secure=True, httponly=True, samesite="strict")
            return respuesta

        # --- Exportación del expediente (DOC-02) ---
        @app.get("/api/pacientes/{paciente_id}/exportar", include_in_schema=False)
        def exportar(paciente_id: int, request: Request, formato: str = "html"):
            return pasarela._exportar(request, paciente_id, formato)

        # --- Tablero de métricas (ADM-02) ---
        @app.get("/panel/metricas", include_in_schema=False)
        def panel_metricas(request: Request, desde: Optional[str] = None, hasta: Optional[str] = None):
            return pasarela._panel(request, desde, hasta)

        # --- Apoyo a la decisión, IA y gestión (antes del montaje de /api, que atrapa el resto) ---
        app.include_router(chat.crear_router(self))
        app.include_router(clinica.crear_router(self))
        app.include_router(gestion.crear_router(self))

        # --- API de pacientes, con identidad y permisos por delante ---
        app.mount("/api", _AppConIdentidad(patients_app, self))
        app.mount("/ui", StaticFiles(directory=str(self.carpeta_estatica)), name="ui")
        return app

    # --- Manejadores con lógica propia --------------------------------------------------------
    def _panel(self, request: Request, desde: Optional[str], hasta: Optional[str]) -> Response:
        from datetime import date

        cabeceras = {"Content-Security-Policy": CSP_TABLERO, "Cache-Control": "no-store"}
        encontrado = self.identidad_de(request.scope)
        if encontrado is None:
            return HTMLResponse(_pagina_mensaje("Tu sesión terminó", "Vuelve a iniciar sesión para ver el tablero.",
                                                ("/", "Ir a iniciar sesión")), status_code=401, headers=cabeceras)
        usuario, _nombre = encontrado
        try:
            d = date.fromisoformat(desde) if desde else None
            h = date.fromisoformat(hasta) if hasta else None
        except ValueError:
            return HTMLResponse(renderizar_error(["Una de las fechas no es válida: usa el formato AAAA-MM-DD (por ejemplo 2026-10-17)."],
                                                 desde=desde or "", hasta=hasta or ""), status_code=400, headers=cabeceras)
        with self.conexion_usuarios() as conn, self.fuentes_de_metricas(conn) as fuentes:
            try:
                # consultar_metricas decide el permiso y deja auditado el intento denegado (ADM-02).
                resultado = met.consultar_metricas(fuentes, usuario, desde=d, hasta=h, via="panel")
            except adm.PermisoDenegadoError:
                return HTMLResponse(_pagina_mensaje("Sin permiso", "Tu rol no puede ver las métricas de uso. Solo la dirección médica las consulta."),
                                    status_code=403, headers=cabeceras)
            except adm.ErrorValidacion as exc:
                return HTMLResponse(renderizar_error([m for _c, m in exc.errores], desde=desde or "", hasta=hasta or ""),
                                    status_code=400, headers=cabeceras)
            except met.ErrorMetricas as exc:
                return HTMLResponse(_pagina_mensaje("No se pudieron calcular las métricas", str(exc)), status_code=500, headers=cabeceras)
            return HTMLResponse(renderizar_panel(resultado), headers=cabeceras)

    def _exportar(self, request: Request, paciente_id: int, formato: str) -> Response:
        from historia_clinica.db import conectar_expediente
        from patients import api as papi
        from patients.expediente import paciente_en_expediente

        encontrado = self.identidad_de(request.scope)
        if encontrado is None:
            raise HTTPException(status_code=401, detail="Inicia sesión para continuar.")
        usuario, _nombre = encontrado
        permiso = verificar_permiso(usuario, Accion.EXPORTAR_EXPEDIENTE)
        if not permiso.permitido:
            raise HTTPException(status_code=403, detail=permiso.motivo_rechazo)
        if usuario.rol != Rol.ONCOLOGO:
            raise HTTPException(status_code=403, detail=MENSAJE_SIN_ASIGNACION)
        if formato not in ("html", "pdf"):
            raise HTTPException(status_code=400, detail={"errores": [{"campo": "formato", "mensaje": "Elige html o pdf."}]})

        sin_expediente = HTTPException(status_code=404, detail="Este paciente todavía no tiene expediente clínico que exportar.")
        ruta = papi._ruta_expediente()
        if not Path(ruta).is_file():
            raise sin_expediente
        conn = papi.db.conectar(papi.DB_PATH)
        conn_exp = conectar_expediente(ruta, check_same_thread=False)
        try:
            papi._paciente_del_oncologo_o_404(conn, paciente_id, usuario.id)
            expediente_id = paciente_en_expediente(conn, conn_exp, paciente_id, crear=False)
            if expediente_id is None:
                raise sin_expediente
            from documentos_clinicos.adaptadores import expediente_completo_a_documento_exportable

            documento = expediente_completo_a_documento_exportable(conn_exp, expediente_id)
            registrar_acceso(conn, usuario.id, TipoAccion.EXPORTAR, paciente_id=paciente_id, detalle="exportar_expediente_" + formato)
            nombre = f"expediente-paciente-{paciente_id}"
            if formato == "html":
                from documentos_clinicos.html_export import renderizar_html

                return HTMLResponse(renderizar_html(documento), headers={
                    "Content-Security-Policy": CSP_DESCARGA, "Cache-Control": "no-store",
                    "Content-Disposition": f'attachment; filename="{nombre}.html"'})
            from documentos_clinicos.pdf_export import exportar_a_pdf

            with tempfile.TemporaryDirectory() as tmp:
                destino = Path(tmp) / (nombre + ".pdf")
                exportar_a_pdf(documento, str(destino))
                contenido = destino.read_bytes()
            return Response(contenido, media_type="application/pdf", headers={
                "Cache-Control": "no-store", "Content-Disposition": f'attachment; filename="{nombre}.pdf"'})
        finally:
            conn_exp.close()
            conn.close()


def crear_app(**opciones: Any) -> FastAPI:
    """Una instancia de la interfaz. Sin opciones usa las bases por defecto (variables ``COPILOTO_*``)."""
    return Pasarela(**opciones).crear_app()


class _AppPerezosa:
    """``app`` a nivel de módulo sin importar la API de pacientes hasta la primera petición (importar este
    módulo no abre bases ni lee variables de entorno)."""

    def __init__(self) -> None:
        self._real: Optional[FastAPI] = None

    async def __call__(self, scope, receive, send) -> None:
        if self._real is None:
            self._real = crear_app()
        await self._real(scope, receive, send)


app = _AppPerezosa()
