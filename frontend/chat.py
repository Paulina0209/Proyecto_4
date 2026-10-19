"""El chat del copiloto en la pasarela: ``/api/chat/...`` (solo oncología, identidad de la sesión).

    POST /api/chat/mensajes                     pregunta al asistente; responde en NDJSON, un evento por línea:
                                                {"tipo": "conversacion"} · {"tipo": "paso"} (cada nodo del grafo, en vivo) · {"tipo": "final"}
    GET  /api/chat/conversaciones               historial del médico
    GET  /api/chat/conversaciones/{id}          mensajes de una conversación (con fuentes y pasos)
    GET  /api/chat/pacientes/{id}/hc            historia clínica para el panel, con los MISMOS ids que cita el asistente
    GET  /api/chat/pacientes/{id}/indice        cuántos fragmentos del paciente hay en la base vectorial
"""

from __future__ import annotations

import json
import queue
import threading
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from auditoria.models import TipoAccion
from auditoria.registro_acceso import registrar_acceso
from seguridad.autorizacion import Accion, verificar_permiso
from seguridad.models import Rol


def crear_router(pasarela) -> APIRouter:
    router = APIRouter(prefix="/api/chat")

    def oncologo(request: Request):
        from frontend.servidor import MENSAJE_SIN_ASIGNACION

        encontrado = pasarela.identidad_de(request.scope)
        if encontrado is None:
            raise HTTPException(status_code=401, detail="Inicia sesión para continuar.")
        usuario, nombre = encontrado
        permiso = verificar_permiso(usuario, Accion.VER_EXPEDIENTE)
        if not permiso.permitido:
            raise HTTPException(status_code=403, detail=permiso.motivo_rechazo)
        if usuario.rol != Rol.ONCOLOGO:
            raise HTTPException(status_code=403, detail=MENSAJE_SIN_ASIGNACION)
        return usuario, nombre

    def conexiones():
        from historia_clinica.db import conectar_expediente
        from patients import api as papi
        from tx_clinica.tools import _db

        ruta = papi._ruta_expediente()
        _db.usar_expediente(ruta)
        return papi.db.conectar(papi.DB_PATH, check_same_thread=False), conectar_expediente(ruta, check_same_thread=False)

    # --- Chat -------------------------------------------------------------------------------------

    @router.post("/mensajes")
    async def mensaje(request: Request):
        from asistente import historial, llm
        from asistente.grafo import Dependencias, ejecutar
        from asistente.indice import indice
        from frontend.servidor import _solicitud_legitima
        from patients.expediente import paciente_en_expediente

        usuario, _nombre = oncologo(request)
        if not _solicitud_legitima(request.scope):
            raise HTTPException(status_code=403, detail="Petición rechazada: no viene de esta aplicación.")
        try:
            datos = await request.json()
        except ValueError:
            datos = {}
        pregunta = str((datos or {}).get("mensaje") or "").strip()
        if not pregunta:
            raise HTTPException(status_code=400, detail={"errores": [{"campo": "mensaje", "mensaje": "Escribe tu pregunta."}]})
        if len(pregunta) > 2000:
            raise HTTPException(status_code=400, detail={"errores": [{"campo": "mensaje", "mensaje": "Máximo 2000 caracteres."}]})
        conversacion = datos.get("conversacion_id")
        if conversacion and not historial.es_de(conversacion, usuario.id):
            raise HTTPException(status_code=404, detail="Esa conversación no existe.")
        try:
            paciente_activo = int(datos["paciente_id"]) if datos.get("paciente_id") not in (None, "") else None
        except (TypeError, ValueError):
            paciente_activo = None

        conn, conn_exp = conexiones()
        if paciente_activo is not None:
            fila = conn.execute("SELECT oncologo_id FROM pacientes WHERE id = ?", (paciente_activo,)).fetchone()
            if fila is None or fila[0] != usuario.id:
                conn.close()
                conn_exp.close()
                raise HTTPException(status_code=404, detail=f"No existe un paciente con id {paciente_activo}.")
        if not conversacion:
            conversacion = historial.nueva_conversacion(usuario.id, pregunta[:80], paciente_activo)

        def buscar_pacientes(texto: str) -> List[Tuple[int, str, str]]:
            patron = f"%{texto.strip()}%"
            return [(f[0], f[1], f[2]) for f in conn.execute(
                "SELECT id, nombre_completo, numero_identificacion FROM pacientes WHERE oncologo_id = ? AND "
                "(nombre_completo LIKE ? OR numero_identificacion LIKE ?) ORDER BY id LIMIT 7", (usuario.id, patron, patron)).fetchall()]

        def expediente_de(paciente_id: int) -> Tuple[Optional[int], str]:
            fila = conn.execute("SELECT nombre_completo FROM pacientes WHERE id = ? AND oncologo_id = ?", (paciente_id, usuario.id)).fetchone()
            if fila is None:
                return None, f"paciente {paciente_id}"
            return paciente_en_expediente(conn, conn_exp, paciente_id), fila[0]

        def guardar(estado: Dict[str, Any]) -> None:
            paciente = estado.get("paciente") or {}
            historial.guardar_mensaje(conversacion, "medico", pregunta, paciente_id=paciente.get("id") or paciente_activo)
            historial.guardar_mensaje(conversacion, "asistente", estado.get("respuesta") or "", intencion=estado.get("intencion"),
                                      estado=estado.get("estado"), paciente_id=paciente.get("id"), fuentes=estado.get("fuentes"),
                                      pasos=estado.get("pasos"), modelo=estado.get("modelo"))
            if paciente.get("id"):
                registrar_acceso(conn, usuario.id, TipoAccion.VER, paciente_id=paciente["id"],
                                 detalle=f"Asistente: {estado.get('intencion')} ({estado.get('estado')})")

        eventos: "queue.Queue[Optional[dict]]" = queue.Queue()
        deps = Dependencias(usuario_id=usuario.id, conn_exp=conn_exp, indice=None, buscar_pacientes=buscar_pacientes,
                            expediente_de=expediente_de, guardar=guardar)

        def trabajar():
            try:
                deps.indice = indice()
                final = ejecutar(pregunta, deps, paciente_activo=paciente_activo, historia=historial.historia_reciente(conversacion),
                                 al_paso=lambda p: eventos.put({"tipo": "paso", **p}))
                eventos.put({"tipo": "final", "conversacion_id": conversacion, "respuesta": final.get("respuesta"), "estado": final.get("estado"),
                             "intencion": final.get("intencion"), "paciente": final.get("paciente"), "fuentes": final.get("fuentes") or [],
                             "opciones": final.get("opciones") or [], "modelo": final.get("modelo")})
            except Exception as exc:  # noqa: BLE001 - el chat explica el error en vez de quedarse colgado
                eventos.put({"tipo": "error", "mensaje": f"No pude responder: {type(exc).__name__}. Inténtalo de nuevo; si sigue, avisa a soporte."})
            finally:
                eventos.put(None)
                conn_exp.close()
                conn.close()

        threading.Thread(target=trabajar, daemon=True).start()

        def flujo():
            yield json.dumps({"tipo": "conversacion", "conversacion_id": conversacion, "modelo": llm.descripcion()}, ensure_ascii=False) + "\n"
            while True:
                evento = eventos.get()
                if evento is None:
                    return
                yield json.dumps(evento, ensure_ascii=False, default=str) + "\n"

        return StreamingResponse(flujo(), media_type="application/x-ndjson", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @router.get("/conversaciones")
    def conversaciones(request: Request):
        from asistente import historial

        usuario, _ = oncologo(request)
        return historial.conversaciones_de(usuario.id)

    @router.get("/conversaciones/{conversacion_id}")
    def conversacion(conversacion_id: str, request: Request):
        from asistente import historial

        usuario, _ = oncologo(request)
        if not historial.es_de(conversacion_id, usuario.id):
            raise HTTPException(status_code=404, detail="Esa conversación no existe.")
        return historial.mensajes_de(conversacion_id)

    # --- Historia clínica del panel ------------------------------------------------------------------

    @router.get("/pacientes/{paciente_id}/hc")
    def hc(paciente_id: int, request: Request):
        """Lo que el panel muestra, con los ids de fragmento del asistente (no exige consentimiento: es la HC, no la IA)."""
        from expediente.adapters import _texto_biomarcador, _texto_imagen, _texto_laboratorio
        from expediente.repository import biomarcadores_de_paciente, imagenologia_de_paciente, laboratorios_de_paciente, listar_consultas
        from ia_clinica.notes.models import split_sentences
        from patients import api as papi
        from patients.expediente import paciente_en_expediente
        from privacidad.consentimiento_ia import estado_consentimiento_ia

        usuario, _ = oncologo(request)
        conn, conn_exp = conexiones()
        try:
            paciente = papi._paciente_del_oncologo_o_404(conn, paciente_id, usuario.id)
            eid = paciente_en_expediente(conn, conn_exp, paciente_id)
            base = {"paciente": {"id": paciente.id, "nombre": paciente.nombre_completo, "identificacion": paciente.numero_identificacion,
                                 "fecha_nacimiento": paciente.fecha_nacimiento.isoformat() if paciente.fecha_nacimiento else None,
                                 "sexo": paciente.sexo.value if hasattr(paciente.sexo, "value") else paciente.sexo, "expediente_id": eid}}
            if eid is None:
                return {**base, "secciones": {}, "consentimiento": None}
            ficha = conn_exp.execute("SELECT diagnostico_principal, estadio FROM pacientes WHERE id = ?", (eid,)).fetchone()
            secciones: Dict[str, List[Dict[str, Any]]] = {
                "ficha": [{"id": f"paciente-{eid}", "texto": f"Diagnóstico principal: {ficha[0] or 'sin registrar'} · Estadio: {ficha[1] or 'sin registrar'}"}],
                "consultas": [{"id": f"consulta-{c.id}-nota-{i}", "texto": o, "fecha": c.fecha, "grupo": f"{c.fecha} · {c.motivo}"}
                              for c in listar_consultas(conn_exp, eid) for i, o in enumerate(split_sentences(c.notas_libres), 1)],
                "laboratorios": [{"id": f"lab-{l.id}", "texto": _texto_laboratorio(l), "fecha": l.fecha} for l in laboratorios_de_paciente(conn_exp, eid)],
                "imagenes": [{"id": f"imagen-{i.id}", "texto": _texto_imagen(i), "fecha": i.fecha} for i in imagenologia_de_paciente(conn_exp, eid)],
                "biomarcadores": [{"id": f"biomarcador-{b.id}", "texto": _texto_biomarcador(b), "fecha": b.fecha} for b in biomarcadores_de_paciente(conn_exp, eid)],
                "antecedentes": [{"id": f"antecedente-{f[0]}", "texto": f"{f[1]}: {f[2]}", "fecha": f[3]} for f in conn_exp.execute(
                    "SELECT id, tipo, descripcion, fecha FROM antecedentes_externos WHERE paciente_id = ? ORDER BY fecha, id", (eid,)).fetchall()]
                if conn_exp.execute("SELECT 1 FROM sqlite_master WHERE name = 'antecedentes_externos'").fetchone() else [],
                "datos": [{"id": f"dato-{f[0]}", "texto": f"{f[1]} = {f[2]}", "fecha": f[3]} for f in conn_exp.execute(
                    "SELECT id, variable, valor, fecha FROM datos_clinicos_estructurados WHERE paciente_id = ? ORDER BY id", (eid,)).fetchall()],
            }
            for clave in ("laboratorios", "imagenes", "biomarcadores", "antecedentes"):
                secciones[clave].sort(key=lambda x: str(x.get("fecha") or ""), reverse=True)
            c = estado_consentimiento_ia(conn_exp, eid)
            registrar_acceso(conn, usuario.id, TipoAccion.VER, paciente_id=paciente_id, detalle="Historia clínica en el panel del asistente")
            if c.ia_habilitada:
                threading.Thread(target=_indexar_en_segundo_plano, args=(eid,), daemon=True).start()
            return {**base, "secciones": secciones, "consentimiento": {"etiqueta": c.etiqueta, "ia_habilitada": c.ia_habilitada, "motivo": c.motivo}}
        finally:
            conn_exp.close()
            conn.close()

    def _indexar_en_segundo_plano(expediente_id: int) -> None:
        """Al abrir el paciente se deja listo su índice: la primera pregunta no espera a los embeddings (NFR-01)."""
        from asistente.__main__ import indexar_paciente
        from asistente.indice import indice
        from historia_clinica.db import conectar_expediente
        from patients import api as papi

        try:
            conn_exp = conectar_expediente(papi._ruta_expediente(), check_same_thread=False)
            try:
                indexar_paciente(conn_exp, expediente_id, indice())
            finally:
                conn_exp.close()
        except Exception:  # noqa: BLE001 - si falla, se indexa al preguntar
            pass

    @router.get("/pacientes/{paciente_id}/indice")
    def estado_indice(paciente_id: int, request: Request):
        from asistente.indice import indice
        from patients import api as papi
        from patients.expediente import paciente_en_expediente

        usuario, _ = oncologo(request)
        conn, conn_exp = conexiones()
        try:
            papi._paciente_del_oncologo_o_404(conn, paciente_id, usuario.id)
            eid = paciente_en_expediente(conn, conn_exp, paciente_id)
            return {"fragmentos": indice().cuantos(eid) if eid is not None else 0}
        finally:
            conn_exp.close()
            conn.close()

    return router
