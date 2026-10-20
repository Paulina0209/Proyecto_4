"""Pantallas de gestión de la interfaz: ``/api/gestion/...``. Cada una para su rol (SEC-01).

    GET  /auditoria?paciente_id=&usuario_id=      AUD-01 / AUD-02         auditor
    GET  /usuarios                                ADM-01                  administrador
    POST /usuarios                                ADM-01: alta            administrador
    POST /usuarios/{id}/rol | /desactivar | /reactivar                   administrador
    GET  /equipos                                 equipo de atención: oncólogos y asignaciones   administrador
    POST /equipos/{id}                            asignar (o retirar) un oncólogo del equipo de la persona
    GET  /guias                                   CFG-01                  administrador clínico (y oncología, solo lectura)
    POST /guias                                   CFG-01                  administrador clínico
    GET  /salud                                   NFR-01 / NFR-02         administrador
    GET  /privacidad                              NFR-06: políticas vigentes y solicitudes de derechos   administrador clínico
    POST /privacidad/politicas                    NFR-06: publicar una política (o su nueva versión)
    POST /privacidad/solicitudes                  NFR-06: recibir una solicitud de derechos del titular
    POST /privacidad/solicitudes/{id}/estado      NFR-06: en trámite, atendida o rechazada
    GET  /privacidad/solicitudes/{id}/informacion NFR-06: la información del titular, para entregarla
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request

from frontend.clinica import a_json
from seguridad.autorizacion import Accion, verificar_permiso
from seguridad.models import Rol, Usuario

RAIZ = Path(__file__).resolve().parent.parent


def ruta_configuracion() -> Path:
    """Base de CFG-01 (``COPILOTO_CONFIGURACION_DB`` o ``data/configuracion.db``)."""
    ruta = Path(os.environ.get("COPILOTO_CONFIGURACION_DB") or RAIZ / "data" / "configuracion.db")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    return ruta


def crear_router(pasarela) -> APIRouter:
    router = APIRouter(prefix="/api/gestion")

    def usuario_con(request: Request, accion: Accion) -> Usuario:
        encontrado = pasarela.identidad_de(request.scope)
        if encontrado is None:
            raise HTTPException(status_code=401, detail="Inicia sesión para continuar.")
        usuario = encontrado[0]
        permiso = verificar_permiso(usuario, accion)
        if not permiso.permitido:
            raise HTTPException(status_code=403, detail=permiso.motivo_rechazo)
        return usuario

    async def cuerpo(request: Request) -> Dict[str, Any]:
        from frontend.servidor import _solicitud_legitima

        if not _solicitud_legitima(request.scope):
            raise HTTPException(status_code=403, detail="Petición rechazada: no viene de esta aplicación.")
        try:
            datos = await request.json()
        except ValueError:
            datos = None
        return datos if isinstance(datos, dict) else {}

    def error_400(exc) -> HTTPException:
        errores = getattr(exc, "errores", None) or [("datos", str(exc))]
        return HTTPException(status_code=400, detail={"errores": [{"campo": c, "mensaje": m} for c, m in errores]})

    # --- AUD-01 / AUD-02 -------------------------------------------------------------------------

    @router.get("/auditoria")
    def auditoria(request: Request, paciente_id: Optional[int] = None, usuario_id: Optional[int] = None, limite: int = 200):
        from auditoria.models import EventoAcceso
        from auditoria.registro_acceso import inicializar_schema
        from auditoria.trazabilidad_ia import obtener_trazabilidad_ia_paciente
        from historia_clinica.db import conectar_expediente
        from patients import api as papi
        from patients.expediente import paciente_en_expediente

        usuario_con(request, Accion.VER_AUDITORIA)
        limite = max(1, min(limite, 1000))
        conn = papi.db.conectar(papi.DB_PATH, check_same_thread=False)
        conn_exp = conectar_expediente(papi._ruta_expediente(), check_same_thread=False)
        try:
            eventos = []
            for origen, c in (("pacientes", conn), ("expediente", conn_exp)):
                inicializar_schema(c)
                sql, params = "SELECT * FROM eventos_acceso", []
                filtros = []
                if paciente_id is not None:
                    pid = paciente_id if origen == "pacientes" else paciente_en_expediente(conn, conn_exp, paciente_id)
                    filtros.append("paciente_id = ?")
                    params.append(pid if pid is not None else -1)
                if usuario_id is not None:
                    filtros.append("usuario_id = ?")
                    params.append(usuario_id)
                if filtros:
                    sql += " WHERE " + " AND ".join(filtros)
                sql += " ORDER BY fecha DESC LIMIT ?"
                params.append(limite)
                for fila in c.execute(sql, params).fetchall():
                    eventos.append({"origen": origen, "id": fila["id"], "usuario_id": fila["usuario_id"], "paciente_id": fila["paciente_id"],
                                    "accion": fila["accion"], "fecha": fila["fecha"], "detalle": fila["detalle"]})
            eventos.sort(key=lambda e: e["fecha"], reverse=True)
            trazabilidad = []
            if paciente_id is not None:
                eid = paciente_en_expediente(conn, conn_exp, paciente_id)
                if eid is not None:
                    from clinical_decision.registro import inicializar_schema as i_tx
                    from dx_clinica.juicio_clinico import inicializar_esquema as i_dx
                    from estadificacion.confirmacion import inicializar_esquema as i_est

                    for inicializar in (i_dx, i_est, i_tx):
                        inicializar(conn_exp)
                    trazabilidad = a_json(obtener_trazabilidad_ia_paciente(paciente_id=eid, conn_dx=conn_exp, conn_est=conn_exp, conn_tx=conn_exp))
            with pasarela.conexion_usuarios() as cu:
                nombres = {f["id"]: f["nombre_usuario"] for f in cu.execute("SELECT id, nombre_usuario FROM usuarios")}
            for e in eventos:
                e["usuario"] = nombres.get(e["usuario_id"], f"#{e['usuario_id']}")
            return {"eventos": eventos[:limite], "trazabilidad_ia": trazabilidad}
        finally:
            conn_exp.close()
            conn.close()

    # --- ADM-01 ------------------------------------------------------------------------------------

    def _usuario_json(u) -> dict:
        datos = a_json(u)
        datos["rol_etiqueta"] = __import__("frontend.servidor", fromlist=["ETIQUETAS_ROL"]).ETIQUETAS_ROL.get(u.rol, u.rol.value)
        return datos

    @router.get("/usuarios")
    def usuarios(request: Request):
        from administracion import usuarios as adm

        actor = usuario_con(request, Accion.GESTIONAR_USUARIOS)
        with pasarela.conexion_usuarios() as conn:
            return {"usuarios": [_usuario_json(u) for u in adm.listar_usuarios(conn, actor)],
                    "roles": [{"valor": r.value, "etiqueta": __import__("frontend.servidor", fromlist=["ETIQUETAS_ROL"]).ETIQUETAS_ROL[r]} for r in Rol]}

    @router.post("/usuarios")
    async def crear_usuario(request: Request):
        from administracion import usuarios as adm

        actor = usuario_con(request, Accion.GESTIONAR_USUARIOS)
        datos = await cuerpo(request)
        with pasarela.conexion_usuarios() as conn:
            try:
                creado = adm.crear_usuario(conn, actor, str(datos.get("nombre_usuario") or "").strip(), str(datos.get("contrasena") or ""),
                                           str(datos.get("rol") or ""), str(datos.get("nombre_completo") or "").strip(),
                                           (datos.get("correo") or None))
            except adm.ErrorValidacion as exc:
                raise error_400(exc) from exc
            return _usuario_json(creado)

    @router.post("/usuarios/{usuario_id}/{operacion}")
    async def operar_usuario(usuario_id: int, operacion: str, request: Request):
        from administracion import usuarios as adm

        actor = usuario_con(request, Accion.GESTIONAR_USUARIOS)
        datos = await cuerpo(request)
        motivo = str(datos.get("motivo") or "").strip()
        with pasarela.conexion_usuarios() as conn:
            try:
                if operacion == "rol":
                    hecho = adm.asignar_rol(conn, actor, usuario_id, str(datos.get("rol") or ""), motivo)
                elif operacion == "desactivar":
                    hecho = adm.desactivar_usuario(conn, actor, usuario_id, motivo)
                    pasarela.sesiones.cerrar_de_usuario(usuario_id)
                elif operacion == "reactivar":
                    hecho = adm.reactivar_usuario(conn, actor, usuario_id)
                else:
                    raise HTTPException(status_code=404, detail="Operación desconocida.")
            except adm.ErrorValidacion as exc:
                raise error_400(exc) from exc
            except adm.PermisoDenegadoError as exc:
                raise HTTPException(status_code=403, detail=str(exc)) from exc
            except (adm.OperacionNoPermitidaError, adm.UsuarioNoEncontradoError) as exc:
                raise HTTPException(status_code=409 if isinstance(exc, adm.OperacionNoPermitidaError) else 404, detail=str(exc)) from exc
            return _usuario_json(hecho)

    # --- Equipo de atención: a qué oncólogos asiste cada persona de enfermería o admisiones ----------

    @router.get("/equipos")
    def equipos(request: Request):
        from administracion import equipo

        usuario_con(request, Accion.GESTIONAR_USUARIOS)
        with pasarela.conexion_usuarios() as conn:
            oncologos = [{"id": f[0], "nombre": f[1] or f[2]} for f in conn.execute(
                "SELECT u.id, p.nombre_completo, u.nombre_usuario FROM usuarios u LEFT JOIN perfiles_usuario p ON p.usuario_id = u.id "
                "WHERE u.rol = ? AND u.activo = 1 ORDER BY u.id", (Rol.ONCOLOGO.value,))]
            miembros = [f[0] for f in conn.execute("SELECT id FROM usuarios WHERE rol IN (?, ?) AND activo = 1",
                                                   tuple(r.value for r in equipo.ROLES_DE_EQUIPO))]
            return {"oncologos": oncologos,
                    "asignaciones": {str(m): [a.oncologo_id for a in equipo.asignaciones_de(conn, m)] for m in miembros}}

    @router.post("/equipos/{usuario_id}")
    async def asignar_equipo(usuario_id: int, request: Request):
        from administracion import equipo
        from administracion import usuarios as adm

        actor = usuario_con(request, Accion.GESTIONAR_USUARIOS)
        datos = await cuerpo(request)
        with pasarela.conexion_usuarios() as conn:
            try:
                oncologo = int(datos.get("oncologo_id"))
                if datos.get("retirar"):
                    equipo.retirar(conn, actor, usuario_id, oncologo)
                else:
                    equipo.asignar(conn, actor, usuario_id, oncologo)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail={"errores": [{"campo": "oncologo_id", "mensaje": "Elige un oncólogo."}]})
            except adm.ErrorValidacion as exc:
                raise error_400(exc) from exc
            except adm.UsuarioNoEncontradoError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            return {"usuario_id": usuario_id, "oncologos": equipo.oncologos_de(conn, usuario_id)}

    # --- CFG-01 ------------------------------------------------------------------------------------

    @router.get("/guias")
    def guias(request: Request):
        from configuracion.guias_institucionales import crear_conexion, historial_configuracion, obtener_configuracion_vigente

        encontrado = pasarela.identidad_de(request.scope)
        if encontrado is None:
            raise HTTPException(status_code=401, detail="Inicia sesión para continuar.")
        usuario = encontrado[0]
        if usuario.rol not in (Rol.ADMINISTRADOR_CLINICO, Rol.ONCOLOGO):
            raise HTTPException(status_code=403, detail="Las guías institucionales las consulta oncología y las configura la administración clínica.")
        with closing(crear_conexion(str(ruta_configuracion()))) as conn:
            return {"vigente": a_json(obtener_configuracion_vigente(conn)), "historial": a_json(historial_configuracion(conn)[:10]),
                    "organizaciones_disponibles": ["NCCN", "ESMO"],
                    "puede_configurar": verificar_permiso(usuario, Accion.CONFIGURAR_GUIAS_INSTITUCIONALES).permitido}

    @router.post("/guias")
    async def configurar(request: Request):
        from configuracion.guias_institucionales import ProtocoloInterno, configurar_guias, crear_conexion

        usuario = usuario_con(request, Accion.CONFIGURAR_GUIAS_INSTITUCIONALES)
        datos = await cuerpo(request)
        organizaciones = [str(o) for o in (datos.get("organizaciones") or []) if str(o).strip()]
        protocolo = None
        if (datos.get("protocolo_nombre") or "").strip():
            protocolo = ProtocoloInterno(str(datos["protocolo_nombre"]).strip(), str(datos.get("protocolo_codigo") or "").strip() or "sin referencia")
        with closing(crear_conexion(str(ruta_configuracion()))) as conn:
            r = configurar_guias(conn, usuario, organizaciones, str(datos.get("motivo") or "").strip(), protocolo_interno=protocolo,
                                 confirmar_sin_modulos=bool(datos.get("confirmar_sin_modulos")))
        if not r.exito:
            raise HTTPException(status_code=400, detail={"errores": [{"campo": "organizaciones", "mensaje": r.motivo_rechazo}]})
        return a_json(r)

    # --- NFR-06: políticas de tratamiento de datos y derechos del titular ------------------------------

    def _privacidad():
        from historia_clinica.db import conectar_expediente
        from privacidad.tratamiento_datos import inicializar_esquema

        conn = conectar_expediente()
        inicializar_esquema(conn)
        return closing(conn)

    def _titular(conn, identificacion: str) -> int:
        """El paciente (id del expediente) por su identificación: documento, id de cBioPortal (P-…) o la clave completa."""
        texto = (identificacion or "").strip()
        if not texto:
            raise HTTPException(status_code=400, detail={"errores": [{"campo": "identificacion", "mensaje": "Indica la identificación del titular."}]})
        filas = conn.execute("SELECT id FROM pacientes WHERE identificacion = ? OR identificacion LIKE ?", (texto, f"%:{texto}")).fetchall()
        if len(filas) != 1:
            mensaje = "No hay ningún paciente con esa identificación." if not filas else "Esa identificación corresponde a más de un paciente: usa la completa."
            raise HTTPException(status_code=404 if not filas else 409, detail={"errores": [{"campo": "identificacion", "mensaje": mensaje}]})
        return filas[0][0]

    @router.get("/privacidad")
    def privacidad(request: Request):
        from privacidad.tratamiento_datos import politicas_vigentes, solicitudes_abiertas

        usuario_con(request, Accion.CONFIGURAR_POLITICA_DATOS)
        with _privacidad() as conn:
            cerradas = [dict(f) for f in conn.execute(
                "SELECT s.id, s.tipo_derecho, s.solicitante, s.fecha_recepcion, p.identificacion, "
                "(SELECT estado FROM eventos_solicitud_derechos e WHERE e.solicitud_id = s.id ORDER BY e.id DESC LIMIT 1) AS estado "
                "FROM solicitudes_derechos s LEFT JOIN pacientes p ON p.id = s.paciente_id ORDER BY s.id DESC LIMIT 20")]
            abiertas = solicitudes_abiertas(conn)
            identificaciones = {s.paciente_id: (conn.execute("SELECT identificacion FROM pacientes WHERE id = ?", (s.paciente_id,)).fetchone() or [None])[0]
                                for s in abiertas}
            return {"politicas": a_json(politicas_vigentes(conn)),
                    "abiertas": [{**a_json(s), "identificacion": identificaciones.get(s.paciente_id)} for s in abiertas],
                    "recientes": cerradas, "estados": ["en_tramite", "atendida", "rechazada"]}

    @router.post("/privacidad/politicas")
    async def configurar_politica(request: Request):
        from privacidad.models import Finalidad
        from privacidad.tratamiento_datos import configurar_politica as configurar

        usuario = usuario_con(request, Accion.CONFIGURAR_POLITICA_DATOS)
        datos = await cuerpo(request)
        lista = lambda clave: [str(x).strip() for x in (datos.get(clave) or []) if str(x).strip()]  # noqa: E731
        try:
            plazo = int(datos.get("plazo_respuesta_dias") or 0)
        except (TypeError, ValueError):
            plazo = 0
        with _privacidad() as conn:
            r = configurar(conn, usuario.id, codigo=str(datos.get("codigo") or "").strip(), jurisdiccion=str(datos.get("jurisdiccion") or "").strip(),
                           nombre=str(datos.get("nombre") or "").strip(), marco_normativo=(str(datos.get("marco_normativo") or "").strip() or None),
                           finalidades=[Finalidad(f, f.replace("_", " ")) for f in lista("finalidades")], bases_legales=lista("bases_legales"),
                           derechos=lista("derechos"), plazo_respuesta_dias=plazo)
        if not r.exito:
            raise HTTPException(status_code=400, detail={"errores": [{"campo": "politica", "mensaje": r.motivo_rechazo}]})
        return a_json(r.registro)

    @router.post("/privacidad/solicitudes")
    async def registrar_solicitud(request: Request):
        from privacidad.tratamiento_datos import registrar_solicitud_derechos

        usuario = usuario_con(request, Accion.CONFIGURAR_POLITICA_DATOS)
        datos = await cuerpo(request)
        with _privacidad() as conn:
            r = registrar_solicitud_derechos(conn, usuario.id, paciente_id=_titular(conn, str(datos.get("identificacion") or "")),
                                             codigo_politica=str(datos.get("codigo_politica") or "").strip(),
                                             tipo_derecho=str(datos.get("tipo_derecho") or "").strip(),
                                             descripcion=str(datos.get("descripcion") or "").strip(), solicitante=str(datos.get("solicitante") or "").strip())
        if not r.exito:
            raise HTTPException(status_code=400, detail={"errores": [{"campo": "solicitud", "mensaje": r.motivo_rechazo}]})
        return a_json(r.registro)

    @router.post("/privacidad/solicitudes/{solicitud_id}/estado")
    async def avanzar_solicitud(solicitud_id: int, request: Request):
        from privacidad.models import EstadoSolicitud
        from privacidad.tratamiento_datos import actualizar_solicitud

        usuario = usuario_con(request, Accion.CONFIGURAR_POLITICA_DATOS)
        datos = await cuerpo(request)
        try:
            estado = EstadoSolicitud(str(datos.get("estado") or ""))
        except ValueError:
            raise HTTPException(status_code=400, detail={"errores": [{"campo": "estado", "mensaje": "Estado desconocido."}]})
        with _privacidad() as conn:
            r = actualizar_solicitud(conn, usuario.id, solicitud_id, estado, (str(datos.get("detalle") or "").strip() or None))
        if not r.exito:
            raise HTTPException(status_code=400, detail={"errores": [{"campo": "estado", "mensaje": r.motivo_rechazo}]})
        return a_json(r.registro)

    @router.get("/privacidad/solicitudes/{solicitud_id}/informacion")
    def informacion_titular(solicitud_id: int, request: Request):
        """AC4: todo lo que el sistema tiene del titular, en un archivo portable (queda en la auditoría)."""
        from fastapi.responses import Response

        from privacidad.tratamiento_datos import obtener_solicitud, recopilar_informacion_titular

        usuario = usuario_con(request, Accion.CONFIGURAR_POLITICA_DATOS)
        with _privacidad() as conn:
            try:
                solicitud = obtener_solicitud(conn, solicitud_id)
            except KeyError:
                raise HTTPException(status_code=404, detail="No existe esa solicitud.")
            info = recopilar_informacion_titular(conn, usuario.id, solicitud.paciente_id, conn_expediente=conn, solicitud_id=solicitud_id)
        return Response(info.a_json(), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="titular-solicitud-{solicitud_id}.json"', "Cache-Control": "no-store"})

    # --- NFR-01 / NFR-02 ---------------------------------------------------------------------------

    @router.get("/salud")
    def estado_sistema(request: Request):
        from operacion.latencia import REGISTRO
        from operacion.salud import estado_general

        usuario_con(request, Accion.VER_ESTADO_SISTEMA)
        verificaciones = pasarela.verificaciones_salud()
        return {"estado": estado_general(verificaciones).value, "verificaciones": [v.a_dict() for v in verificaciones],
                "rutas": [r.a_dict() for r in REGISTRO.resumen()]}

    return router
