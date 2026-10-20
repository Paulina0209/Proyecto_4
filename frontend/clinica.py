"""Funciones clínicas del copiloto para la interfaz web: ``/api/clinica/...``.

La API de pacientes (``patients.api``) cubre el expediente (registro, búsqueda,
360, laboratorios, imágenes, biopsias, consentimiento). Las funciones de apoyo a
la decisión y de IA son módulos de Python sin HTTP propio; este router las
expone a la interfaz con las mismas garantías que la pasarela:

    - la identidad sale de la sesión, nunca del navegador;
    - solo oncología ve expedientes, y solo los de SUS pacientes (404 si no);
    - cada acción sensible exige su permiso de SEC-01 (fail-closed);
    - las funciones de IA respetan el consentimiento de SEC-03: sin él
      responden 409 con ``consentimiento_requerido`` y la interfaz lo explica;
    - notas y resúmenes usan GPT con el presupuesto de NFR-01 (< 10 s) y dicen
      quién los redactó (el modelo o el respaldo por reglas).

Rutas (todas bajo ``/api/clinica``):

    GET  /capacidades                                   modelo de IA y extensiones (HC-06, CFG-02)
    GET  /pacientes/{id}/faltantes                      HC-05
    GET  /pacientes/{id}/historia-externa               HC-01
    POST /pacientes/{id}/preguntar                      IA-01 / IA-06
    GET  /pacientes/{id}/diagnostico?sospecha=          DX-01, DX-02, DX-03, IA-05
    POST /pacientes/{id}/diagnostico/juicio             DX-03
    GET  /pacientes/{id}/estadificacion                 EST-01, EST-03
    POST /pacientes/{id}/estadificacion/datos           T/N/M que registra el oncólogo
    POST /pacientes/{id}/estadificacion/confirmar       EST-02
    GET  /pacientes/{id}/tratamiento                    TX-01, TX-02 (+ medicación actual)
    POST /pacientes/{id}/tratamiento/datos              variables de la guía
    POST /pacientes/{id}/tratamiento/conciliacion       medicación concomitante
    GET  /pacientes/{id}/tratamiento/interacciones      TX-03
    POST /pacientes/{id}/tratamiento/decision           TX-04
    GET  /pacientes/{id}/consultas-expediente           consultas del expediente (insumo de IA-02)
    POST /pacientes/{id}/consultas-expediente           registrar la consulta de hoy
    GET  /pacientes/{id}/notas                          IA-03: notas en revisión
    POST /pacientes/{id}/notas                          IA-02: borrador con GPT
    PUT  /pacientes/{id}/notas/{nota}/secciones/{clave} IA-03: editar una sección
    POST /pacientes/{id}/notas/{nota}/aprobar           IA-03: aprobar
    POST /pacientes/{id}/resumen-junta                  IA-04
    GET  /pacientes/{id}/evidencia?q=                   EV-01 (filtrada por CFG-01)
    GET  /pacientes/{id}/privacidad                     SEC-03 / NFR-06: historial de autorizaciones
    GET  /pacientes/{id}/documentos                     DOC-01
    POST /pacientes/{id}/documentos                     DOC-01 (contenido en base64)
    GET  /pacientes/{id}/documentos/{doc}/contenido     DOC-01: descarga (descifrado, SEC-02)
"""

from __future__ import annotations

import base64
import binascii
import dataclasses
import enum
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from auditoria.models import TipoAccion
from auditoria.registro_acceso import registrar_acceso
from privacidad.consentimiento_ia import ConsentimientoIARequerido
from seguridad.autorizacion import Accion, verificar_permiso
from seguridad.models import Rol, Usuario

RAIZ = Path(__file__).resolve().parent.parent
#: Límite de un documento cargado desde la interfaz (DOC-01).
TAMANO_MAXIMO_DOCUMENTO = 15 * 1024 * 1024

#: Variables de estadificación que el oncólogo puede registrar desde la pantalla de EST.
VARIABLES_ESTADIO = {
    "clinical_t_category": "Categoría T",
    "clinical_n_status": "Categoría N",
    "clinical_m_status": "Categoría M",
}


def a_json(objeto: Any) -> Any:
    """Dataclasses, enums y fechas a JSON (recursivo)."""
    if dataclasses.is_dataclass(objeto) and not isinstance(objeto, type):
        return {f.name: a_json(getattr(objeto, f.name)) for f in dataclasses.fields(objeto)}
    if isinstance(objeto, enum.Enum):
        return objeto.value
    if isinstance(objeto, (list, tuple, set, frozenset)):
        return [a_json(x) for x in objeto]
    if isinstance(objeto, dict):
        return {str(k): a_json(v) for k, v in objeto.items()}
    if isinstance(objeto, (date, datetime)):
        return objeto.isoformat()
    if isinstance(objeto, Path):
        return objeto.as_posix()
    if isinstance(objeto, (str, int, float, bool)) or objeto is None:
        return objeto
    return str(objeto)


def _consentimiento_requerido(exc: ConsentimientoIARequerido) -> HTTPException:
    return HTTPException(status_code=409, detail={
        "consentimiento_requerido": True, "mensaje": str(exc),
        "errores": [{"campo": "consentimiento", "mensaje": str(exc)}]})


@dataclasses.dataclass
class Contexto:
    usuario: Usuario
    nombre_completo: str
    conn: sqlite3.Connection          # base de pacientes
    conn_exp: sqlite3.Connection      # expediente clínico
    paciente: Any                     # patients.models.Paciente
    expediente_id: Optional[int]

    @property
    def autor(self) -> str:
        return f"{self.nombre_completo} ({self.usuario.nombre_usuario})"

    def exigir_expediente(self) -> int:
        if self.expediente_id is None:
            raise HTTPException(status_code=404, detail=(
                "Este paciente todavía no tiene expediente clínico: registra un laboratorio, una biopsia o una "
                "consulta para crearlo."))
        return self.expediente_id

    def auditar(self, accion: TipoAccion, detalle: str) -> None:
        registrar_acceso(self.conn, self.usuario.id, accion, paciente_id=self.paciente.id, detalle=detalle)


def crear_router(pasarela) -> APIRouter:  # noqa: C901 - un router por historia sería más difícil de seguir
    from frontend import extensiones
    from frontend.agente import ConversacionesAgente

    router = APIRouter(prefix="/api/clinica")
    agentes = ConversacionesAgente()

    # --- Contexto común ---------------------------------------------------------------------

    def _identidad(request: Request):
        encontrado = pasarela.identidad_de(request.scope)
        if encontrado is None:
            raise HTTPException(status_code=401, detail="Inicia sesión para continuar.")
        return encontrado

    def _permiso(usuario: Usuario, accion: Accion) -> None:
        resultado = verificar_permiso(usuario, accion)
        if not resultado.permitido:
            raise HTTPException(status_code=403, detail=resultado.motivo_rechazo)

    @contextmanager
    def contexto(request: Request, paciente_id: int, accion: Accion = Accion.VER_EXPEDIENTE,
                 crear_expediente: bool = False, solo_oncologia: bool = False) -> Iterator[Contexto]:
        """El paciente, si quien pide puede verlo: oncología (los suyos) o su equipo de atención.
        ``solo_oncologia``: apoyo a la decisión (DX, EST, TX, evidencia, agentes): es del oncólogo tratante."""
        from frontend.servidor import MENSAJE_SIN_ASIGNACION
        from historia_clinica.db import conectar_expediente
        from patients import api as papi
        from patients.expediente import paciente_en_expediente
        from tx_clinica.tools import _db

        usuario, nombre = _identidad(request)
        _permiso(usuario, accion)
        if not pasarela.oncologos_visibles(usuario):
            raise HTTPException(status_code=403, detail=MENSAJE_SIN_ASIGNACION)
        if solo_oncologia and usuario.rol != Rol.ONCOLOGO:
            raise HTTPException(status_code=403, detail="El apoyo a la decisión (diagnóstico, estadificación, tratamiento y evidencia) es del oncólogo tratante.")
        conn = papi.db.conectar(papi.DB_PATH, check_same_thread=False)
        ruta = papi._ruta_expediente()
        conn_exp = conectar_expediente(ruta, check_same_thread=False)
        _db.usar_expediente(ruta)  # las tools de TX trabajan sobre el mismo expediente
        try:
            paciente = papi._paciente_del_oncologo_o_404(conn, paciente_id, pasarela.oncologo_responsable(usuario, paciente_id))
            expediente_id = paciente_en_expediente(conn, conn_exp, paciente_id, crear=crear_expediente)
            yield Contexto(usuario, nombre or usuario.nombre_usuario, conn, conn_exp, paciente, expediente_id)
        except ConsentimientoIARequerido as exc:
            raise _consentimiento_requerido(exc) from exc
        finally:
            conn_exp.close()
            conn.close()

    def _tool(tool, argumentos: Dict[str, Any], oncologo_id: int) -> dict:
        """Invoca una tool de TX (las mismas que usa el agente) y devuelve su JSON."""
        crudo = tool.invoke(argumentos, config={"configurable": {"oncologo_id": oncologo_id}})
        datos = json.loads(crudo)
        if isinstance(datos, dict) and datos.get("error") == "consentimiento_ia_requerido":
            raise HTTPException(status_code=409, detail={"consentimiento_requerido": True, "mensaje": datos["mensaje"],
                                                         "errores": [{"campo": "consentimiento", "mensaje": datos["mensaje"]}]})
        return datos

    async def _cuerpo(request: Request) -> Dict[str, Any]:
        from frontend.servidor import _solicitud_legitima

        if not _solicitud_legitima(request.scope):
            raise HTTPException(status_code=403, detail="Petición rechazada: no viene de esta aplicación.")
        try:
            datos = await request.json()
        except ValueError:
            datos = None
        return datos if isinstance(datos, dict) else {}

    def _texto(datos: Dict[str, Any], campo: str, etiqueta: str, maximo: int = 4000) -> str:
        valor = datos.get(campo)
        valor = valor.strip() if isinstance(valor, str) else ""
        if not valor:
            raise HTTPException(status_code=400, detail={"errores": [{"campo": campo, "mensaje": f"Escribe {etiqueta}."}]})
        if len(valor) > maximo:
            raise HTTPException(status_code=400, detail={"errores": [{"campo": campo, "mensaje": f"Máximo {maximo} caracteres."}]})
        return valor

    # --- Capacidades ------------------------------------------------------------------------

    @router.get("/capacidades")
    def capacidades(request: Request):
        from core import llm_config

        _identidad(request)
        llave = bool(llm_config.obtener_api_key())
        return {
            "modelo_ia": {"configurado": llave, "modelo": llm_config.obtener_modelo() if llave else None,
                          "descripcion": f"GPT ({llm_config.obtener_modelo()})" if llave else "Sin llave de OpenAI: notas y resúmenes por reglas"},
            "agente": {"disponible": llave},
            "extensiones": extensiones.estado(pasarela.patients_app),
        }

    # --- HC-05 / HC-01 ------------------------------------------------------------------------

    @router.get("/pacientes/{paciente_id}/faltantes")
    def faltantes(paciente_id: int, request: Request):
        from historia_clinica.informacion_faltante import evaluar_informacion_faltante

        with contexto(request, paciente_id) as ctx:
            return a_json(evaluar_informacion_faltante(ctx.conn_exp, ctx.exigir_expediente()))

    @router.get("/pacientes/{paciente_id}/historia-externa")
    def historia_externa(paciente_id: int, request: Request):
        from historia_clinica.integracion_externa import antecedentes_externos_de_paciente, listar_sincronizaciones

        with contexto(request, paciente_id) as ctx:
            if ctx.expediente_id is None:
                return {"sincronizaciones": [], "antecedentes": []}
            return {"sincronizaciones": a_json(listar_sincronizaciones(ctx.conn_exp, ctx.expediente_id)),
                    "antecedentes": a_json(antecedentes_externos_de_paciente(ctx.conn_exp, ctx.expediente_id))}

    # --- IA-01 / IA-06 ------------------------------------------------------------------------

    @router.post("/pacientes/{paciente_id}/preguntar")
    async def preguntar(paciente_id: int, request: Request):
        from clinical_query import NaturalLanguageClinicalQueryService, SQLiteClinicalRepository
        from clinical_query.service import Clarification

        datos = await _cuerpo(request)
        pregunta = _texto(datos, "pregunta", "tu pregunta", 500)
        aclaracion = Clarification(concept=datos.get("concepto") or None, episode_id=datos.get("episodio") or None,
                                   confirm_active_patient=bool(datos.get("confirmar_paciente")))
        with contexto(request, paciente_id, solo_oncologia=True) as ctx:
            servicio = NaturalLanguageClinicalQueryService(SQLiteClinicalRepository(ctx.conn_exp))
            respuesta = servicio.ask(str(ctx.exigir_expediente()), pregunta, clarification=aclaracion)
            ctx.auditar(TipoAccion.VER, "Consulta en lenguaje natural")
            return a_json(respuesta)

    # --- DX -------------------------------------------------------------------------------------

    def _diferencial(ctx: Contexto):
        from dx_clinica.builder import construir_diagnosticos_diferenciales
        from expediente.adapters import obtener_hallazgos_de_paciente
        from expediente.repository import obtener_paciente

        eid = ctx.exigir_expediente()
        paciente = obtener_paciente(ctx.conn_exp, eid)
        hallazgos = obtener_hallazgos_de_paciente(ctx.conn_exp, eid)
        return paciente, hallazgos, construir_diagnosticos_diferenciales(paciente, hallazgos)

    @router.get("/pacientes/{paciente_id}/diagnostico")
    def diagnostico(paciente_id: int, request: Request, sospecha: Optional[str] = None):
        from dx_clinica.incertidumbre import analizar_incertidumbre
        from dx_clinica.juicio_clinico import inicializar_esquema, obtener_decision_diagnostica_vigente
        from dx_clinica.recomendacion_estudios import recomendar_estudios
        from ia_clinica.explainability import PatientRecommendationService

        with contexto(request, paciente_id, solo_oncologia=True) as ctx:
            paciente, hallazgos, resultado = _diferencial(ctx)
            inicializar_esquema(ctx.conn_exp)
            explicaciones = PatientRecommendationService().for_patient(paciente, hallazgos)
            cuerpo = {
                "hallazgos": len(hallazgos),
                "textos_hallazgos": {h.id: h.texto for h in hallazgos},
                "diferencial": a_json(resultado),
                "incertidumbre": a_json(analizar_incertidumbre(resultado)),
                "explicaciones": a_json(explicaciones),
                "decision_vigente": a_json(obtener_decision_diagnostica_vigente(ctx.conn_exp, paciente.id, resultado)),
                "estudios": None,
            }
            if sospecha and sospecha.strip():
                cuerpo["estudios"] = a_json(recomendar_estudios(paciente_id=paciente.id, sospecha_diagnostica=sospecha.strip()[:300],
                                                                hallazgos=hallazgos))
            ctx.auditar(TipoAccion.VER, "DX: apoyo al diagnóstico")
            return cuerpo

    @router.post("/pacientes/{paciente_id}/diagnostico/juicio")
    async def juicio(paciente_id: int, request: Request):
        from dx_clinica.juicio_clinico import inicializar_esquema, registrar_juicio_clinico

        datos = await _cuerpo(request)
        texto = _texto(datos, "diagnostico", "el diagnóstico o juicio clínico", 2000)
        with contexto(request, paciente_id, Accion.REGISTRAR_JUICIO_DIAGNOSTICO) as ctx:
            _p, _h, resultado = _diferencial(ctx)
            inicializar_esquema(ctx.conn_exp)
            registrado = registrar_juicio_clinico(ctx.conn_exp, paciente_id=ctx.exigir_expediente(), diagnostico_registrado=texto,
                                                  autor=ctx.autor, resultado_sistema=resultado)
            ctx.auditar(TipoAccion.EDITAR, "Juicio clínico registrado")
            return a_json(registrado)

    # --- EST --------------------------------------------------------------------------------------

    def _propuesta(ctx: Contexto):
        from estadificacion.builder import proponer_estadificacion

        return proponer_estadificacion(ctx.conn_exp, ctx.exigir_expediente())

    @router.get("/pacientes/{paciente_id}/estadificacion")
    def estadificacion(paciente_id: int, request: Request):
        from estadificacion.confirmacion import inicializar_esquema, obtener_estadificacion_vigente
        from estadificacion.incompleta import analizar_estadificacion_incompleta

        with contexto(request, paciente_id, solo_oncologia=True) as ctx:
            propuesta = _propuesta(ctx)
            inicializar_esquema(ctx.conn_exp)
            return {"propuesta": a_json(propuesta), "incompleta": a_json(analizar_estadificacion_incompleta(propuesta)),
                    "vigente": a_json(obtener_estadificacion_vigente(ctx.conn_exp, ctx.expediente_id, propuesta)),
                    "variables": VARIABLES_ESTADIO}

    @router.post("/pacientes/{paciente_id}/estadificacion/datos")
    async def estadificacion_datos(paciente_id: int, request: Request):
        from expediente.registro import registrar_datos_clinicos

        datos = await _cuerpo(request)
        valores = {k: str(v).strip() for k, v in (datos.get("valores") or {}).items()
                   if k in VARIABLES_ESTADIO and isinstance(v, (str, int)) and str(v).strip()}
        if not valores:
            raise HTTPException(status_code=400, detail={"errores": [{"campo": "valores", "mensaje": "Indica al menos un componente (T, N o M)."}]})
        with contexto(request, paciente_id, Accion.EDITAR_EXPEDIENTE) as ctx:
            registrar_datos_clinicos(ctx.conn_exp, ctx.exigir_expediente(), valores)
            ctx.auditar(TipoAccion.EDITAR, f"EST: componentes registrados ({', '.join(valores)})")
            return {"registrados": valores}

    @router.post("/pacientes/{paciente_id}/estadificacion/confirmar")
    async def estadificacion_confirmar(paciente_id: int, request: Request):
        from estadificacion.confirmacion import confirmar_estadificacion, inicializar_esquema

        datos = await _cuerpo(request)
        estadio = _texto(datos, "estadio", "el estadio confirmado", 20)
        justificacion = (datos.get("justificacion") or "").strip() or None
        with contexto(request, paciente_id, Accion.CONFIRMAR_ESTADIFICACION) as ctx:
            propuesta = _propuesta(ctx)
            inicializar_esquema(ctx.conn_exp)
            try:
                confirmado = confirmar_estadificacion(ctx.conn_exp, ctx.expediente_id, estadio_confirmado=estadio, autor=ctx.autor,
                                                      propuesta_sistema=propuesta, justificacion=justificacion)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail={"errores": [{"campo": "estadio", "mensaje": str(exc)}]}) from exc
            ctx.auditar(TipoAccion.EDITAR, f"Estadio confirmado {estadio}")
            return a_json(confirmado)

    # --- TX ------------------------------------------------------------------------------------------

    @router.get("/pacientes/{paciente_id}/tratamiento")
    def tratamiento(paciente_id: int, request: Request):
        from tx_clinica.tools.interaction_tools import consultar_medicacion_actual
        from tx_clinica.tools.recommendation_tools import obtener_recomendaciones_tratamiento_por_id
        from tx_clinica.tools.registro_tools import definiciones_variables, variables_de_biomarcadores

        with contexto(request, paciente_id, solo_oncologia=True) as ctx:
            eid = ctx.exigir_expediente()
            recomendacion = _tool(obtener_recomendaciones_tratamiento_por_id, {"patient_id": eid}, ctx.usuario.id)
            medicacion = _tool(consultar_medicacion_actual, {"patient_id": eid}, ctx.usuario.id)
            ctx.auditar(TipoAccion.VER, "Recomendaciones de tratamiento")
            # Los biomarcadores no se escriben como dato suelto: la interfaz los manda a HC-04.
            return {"recomendacion": recomendacion, "medicacion": medicacion, "definiciones": a_json(definiciones_variables()),
                    "biomarcadores": sorted(variables_de_biomarcadores())}

    @router.post("/pacientes/{paciente_id}/tratamiento/datos")
    async def tratamiento_datos(paciente_id: int, request: Request):
        from tx_clinica.tools.registro_tools import registrar_datos_clinicos_paciente

        datos = await _cuerpo(request)
        valores = datos.get("valores")
        if not isinstance(valores, dict) or not valores:
            raise HTTPException(status_code=400, detail={"errores": [{"campo": "valores", "mensaje": "Indica al menos un dato clínico."}]})
        with contexto(request, paciente_id, Accion.EDITAR_EXPEDIENTE) as ctx:
            r = _tool(registrar_datos_clinicos_paciente, {"patient_id": ctx.exigir_expediente(), "datos": valores}, ctx.usuario.id)
            if r.get("error"):
                errores = [{"campo": str(e).split("'")[1] if str(e).startswith("'") else "valores", "mensaje": str(e)}
                           for e in (r.get("errores") or [])]
                raise HTTPException(status_code=400, detail={"errores": errores or [{"campo": "valores", "mensaje": r.get("mensaje") or r["error"]}]})
            return r

    @router.post("/pacientes/{paciente_id}/tratamiento/conciliacion")
    async def tratamiento_conciliacion(paciente_id: int, request: Request):
        from tx_clinica.tools.registro_tools import registrar_conciliacion_medicamentos

        datos = await _cuerpo(request)
        medicamentos = [m.strip() for m in (datos.get("medicamentos") or []) if isinstance(m, str) and m.strip()]
        # "Sin medicación" tiene que ser explícito: una lista vacía no significa que no tome nada.
        argumentos = {"sin_medicacion_concomitante": True} if datos.get("sin_medicacion") and not medicamentos else {"medicamentos": medicamentos}
        with contexto(request, paciente_id, Accion.EDITAR_EXPEDIENTE) as ctx:
            r = _tool(registrar_conciliacion_medicamentos, {"patient_id": ctx.exigir_expediente(), **argumentos}, ctx.usuario.id)
            if r.get("error"):
                raise HTTPException(status_code=400, detail={"errores": [{"campo": "medicamentos", "mensaje": r.get("mensaje") or r["error"]}]})
            return r

    @router.get("/pacientes/{paciente_id}/tratamiento/interacciones")
    def tratamiento_interacciones(paciente_id: int, request: Request, regimen: str):
        from tx_clinica.tools.interaction_tools import chequear_interacciones_tratamiento

        with contexto(request, paciente_id, solo_oncologia=True) as ctx:
            return _tool(chequear_interacciones_tratamiento, {"patient_id": ctx.exigir_expediente(), "regimen_id": regimen},
                         ctx.usuario.id)

    @router.post("/pacientes/{paciente_id}/tratamiento/decision")
    async def tratamiento_decision(paciente_id: int, request: Request):
        from tx_clinica.tools.decision_tools import registrar_decision_tratamiento

        datos = await _cuerpo(request)
        tipo = datos.get("tipo")
        if tipo not in ("accept", "modify", "reject"):
            raise HTTPException(status_code=400, detail={"errores": [{"campo": "tipo", "mensaje": "Elige aceptar, modificar o rechazar."}]})
        argumentos = {"tipo_decision": tipo}
        if datos.get("regimen_final"):
            argumentos["regimen_final_id"] = str(datos["regimen_final"])
        if datos.get("motivo"):
            argumentos["motivo_rechazo"] = str(datos["motivo"]).strip()[:2000]
        if isinstance(datos.get("justificaciones"), dict):
            argumentos["textos_justificacion"] = {str(k): str(v) for k, v in datos["justificaciones"].items() if str(v).strip()}
        with contexto(request, paciente_id, Accion.CONFIRMAR_TRATAMIENTO) as ctx:
            argumentos["patient_id"] = ctx.exigir_expediente()
            return _tool(registrar_decision_tratamiento, argumentos, ctx.usuario.id)

    # --- Consultas e IA-02 / IA-03 / IA-04 ------------------------------------------------------------

    @router.get("/pacientes/{paciente_id}/consultas-expediente")
    def consultas_expediente(paciente_id: int, request: Request):
        from expediente.repository import listar_consultas

        with contexto(request, paciente_id) as ctx:
            if ctx.expediente_id is None:
                return []
            return a_json(listar_consultas(ctx.conn_exp, ctx.expediente_id))

    @router.post("/pacientes/{paciente_id}/consultas-expediente")
    async def registrar_consulta(paciente_id: int, request: Request):
        from expediente.registro import registrar_consulta as registrar

        datos = await _cuerpo(request)
        motivo = _texto(datos, "motivo", "el motivo de la consulta", 200)
        notas = _texto(datos, "notas", "lo que pasó en la consulta", 8000)
        with contexto(request, paciente_id, Accion.EDITAR_EXPEDIENTE, crear_expediente=True) as ctx:
            consulta_id = registrar(ctx.conn_exp, ctx.exigir_expediente(), motivo, notas)
            ctx.auditar(TipoAccion.EDITAR, f"Consulta #{consulta_id} registrada en el expediente")
            return {"consulta_id": consulta_id}

    def _cliente_llm(respaldo):
        from core import llm_config
        from operacion.presupuesto import LLMConPresupuesto, cliente_openai_para_presupuesto

        principal = cliente_openai_para_presupuesto() if llm_config.obtener_api_key() else respaldo
        return LLMConPresupuesto(principal, respaldo)

    def _uso(cliente) -> dict:
        uso = cliente.ultimo_uso
        modelo = getattr(cliente.principal, "model", None)
        if uso is None:
            return {}
        if uso.proveedor == "modelo" and modelo:
            return {"proveedor": "modelo", "modelo": modelo, "segundos": round(uso.segundos, 1),
                    "descripcion": f"Redactado por {modelo} en {uso.segundos:.1f} s"}
        return {"proveedor": "respaldo", "segundos": round(uso.segundos, 1), "motivo": uso.motivo,
                "descripcion": "Redactado por el asistente de reglas" + (f" ({uso.motivo})" if uso.motivo else " (sin llave de OpenAI)")}

    def _revisiones(conn_exp: sqlite3.Connection):
        from ia_clinica.review import store

        store.inicializar_esquema(conn_exp)
        return store

    def _nota_json(nota) -> dict:
        datos = a_json(nota)
        datos["oficial"] = nota.es_nota_oficial()
        return datos

    @router.get("/pacientes/{paciente_id}/notas")
    def notas(paciente_id: int, request: Request):
        with contexto(request, paciente_id) as ctx:
            if ctx.expediente_id is None:
                return []
            store = _revisiones(ctx.conn_exp)
            ids = [f[0] for f in ctx.conn_exp.execute(
                "SELECT nota_id FROM revision_notas WHERE paciente_ref = ? ORDER BY creado_en DESC", (f"paciente-{ctx.expediente_id}",))]
            return [_nota_json(store.obtener_revision(ctx.conn_exp, i)) for i in ids]

    @router.post("/pacientes/{paciente_id}/notas")
    async def generar_nota(paciente_id: int, request: Request):
        from expediente.adapters import construir_contexto_clinico
        from ia_clinica.notes.generator import ClinicalNoteGenerator, GenerationError
        from ia_clinica.notes.llm_client import RuleBasedLLMClient
        from ia_clinica.review.service import iniciar_revision

        datos = await _cuerpo(request)
        try:
            consulta_id = int(datos.get("consulta_id"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail={"errores": [{"campo": "consulta_id", "mensaje": "Elige la consulta."}]})
        formato = datos.get("formato") or "SOAP"
        with contexto(request, paciente_id, Accion.EDITAR_EXPEDIENTE) as ctx:
            eid = ctx.exigir_expediente()
            fila = ctx.conn_exp.execute("SELECT paciente_id FROM consultas WHERE id = ?", (consulta_id,)).fetchone()
            if fila is None or fila[0] != eid:
                raise HTTPException(status_code=404, detail="Esa consulta no es de este paciente.")
            _revisiones(ctx.conn_exp)
            previa = ctx.conn_exp.execute("SELECT estado FROM revision_notas WHERE nota_id = ?", (f"consulta-{consulta_id}",)).fetchone()
            if previa is not None:
                # Una consulta tiene una sola nota: se edita (o ya se aprobó), no se vuelve a generar encima.
                aprobada = str(previa[0]).upper() == "APPROVED"
                raise HTTPException(status_code=409, detail={"errores": [{"campo": "consulta_id", "mensaje":
                    "Esa consulta ya tiene una nota aprobada como oficial." if aprobada else
                    "Esa consulta ya tiene un borrador: edítalo o apruébalo en la lista de notas."}]})
            cliente = _cliente_llm(RuleBasedLLMClient())
            try:
                borrador = ClinicalNoteGenerator(llm_client=cliente).generate_draft(
                    construir_contexto_clinico(ctx.conn_exp, consulta_id), format_name=formato)
            except (GenerationError, ValueError) as exc:
                raise HTTPException(status_code=400, detail={"errores": [{"campo": "consulta_id", "mensaje": str(exc)}]}) from exc
            _revisiones(ctx.conn_exp)
            revision = iniciar_revision(ctx.conn_exp, borrador)
            ctx.auditar(TipoAccion.EDITAR, f"Borrador de nota generado ({_uso(cliente).get('proveedor')})")
            return {"nota": _nota_json(revision), "borrador": a_json(borrador), "uso_modelo": _uso(cliente)}

    @router.put("/pacientes/{paciente_id}/notas/{nota_id}/secciones/{clave}")
    async def editar_nota(paciente_id: int, nota_id: str, clave: str, request: Request):
        from ia_clinica.review.models import NotaYaAprobadaError
        from ia_clinica.review.service import editar_seccion

        datos = await _cuerpo(request)
        contenido = _texto(datos, "contenido", "el contenido de la sección", 8000)
        with contexto(request, paciente_id, Accion.EDITAR_EXPEDIENTE) as ctx:
            _revisiones(ctx.conn_exp)
            _nota_del_paciente(ctx, nota_id)
            try:
                return _nota_json(editar_seccion(ctx.conn_exp, nota_id=nota_id, seccion_key=clave, nuevo_contenido=contenido, autor=ctx.autor))
            except NotaYaAprobadaError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except (KeyError, ValueError) as exc:
                raise HTTPException(status_code=400, detail={"errores": [{"campo": "contenido", "mensaje": str(exc)}]}) from exc

    @router.post("/pacientes/{paciente_id}/notas/{nota_id}/aprobar")
    async def aprobar(paciente_id: int, nota_id: str, request: Request):
        from ia_clinica.review.models import NotaYaAprobadaError
        from ia_clinica.review.service import aprobar_nota

        await _cuerpo(request)
        with contexto(request, paciente_id, Accion.EDITAR_EXPEDIENTE) as ctx:
            _revisiones(ctx.conn_exp)
            _nota_del_paciente(ctx, nota_id)
            try:
                nota = aprobar_nota(ctx.conn_exp, nota_id, aprobado_por=ctx.autor)
            except NotaYaAprobadaError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            ctx.auditar(TipoAccion.EDITAR, "Nota aprobada como oficial")
            return _nota_json(nota)

    def _nota_del_paciente(ctx: Contexto, nota_id: str) -> None:
        fila = ctx.conn_exp.execute("SELECT paciente_ref FROM revision_notas WHERE nota_id = ?", (nota_id,)).fetchone()
        if fila is None or fila[0] != f"paciente-{ctx.expediente_id}":
            raise HTTPException(status_code=404, detail="No existe esa nota para este paciente.")

    @router.post("/pacientes/{paciente_id}/resumen-junta")
    async def resumen_junta(paciente_id: int, request: Request):
        from expediente.adapters import construir_contexto_resumen_caso
        from ia_clinica.summary.generator import CaseSummaryGenerator
        from ia_clinica.summary.llm_client import RuleBasedSummaryLLMClient

        await _cuerpo(request)
        with contexto(request, paciente_id, solo_oncologia=True) as ctx:
            cliente = _cliente_llm(RuleBasedSummaryLLMClient())
            resumen = CaseSummaryGenerator(llm_client=cliente).generate_summary(
                construir_contexto_resumen_caso(ctx.conn_exp, ctx.exigir_expediente()))
            ctx.auditar(TipoAccion.VER, "Resumen para junta médica")
            return {"resumen": a_json(resumen), "texto": resumen.to_text(), "uso_modelo": _uso(cliente)}

    # --- EV-01 ------------------------------------------------------------------------------------------

    @router.get("/pacientes/{paciente_id}/evidencia")
    def evidencia(paciente_id: int, request: Request, q: Optional[str] = None):
        from evidencia_clinica import EvidenceSearchService
        from expediente.repository import obtener_paciente

        with contexto(request, paciente_id, solo_oncologia=True) as ctx:
            eid = ctx.exigir_expediente()
            servicio = EvidenceSearchService()
            if q and q.strip():
                resultados = servicio.search(q.strip()[:200])
            else:
                import demo_ia01

                resultados = servicio.search_for_patient(obtener_paciente(ctx.conn_exp, eid),
                                                         demo_ia01._terminos_clinicos_paciente(ctx.conn_exp, eid))
            from frontend.gestion import ruta_configuracion
            from configuracion.guias_institucionales import crear_conexion as conectar_cfg, obtener_configuracion_vigente

            cfg = conectar_cfg(str(ruta_configuracion()))
            try:
                vigente = obtener_configuracion_vigente(cfg)
            finally:
                cfg.close()
            preferidas = [o.upper() for o in vigente.organizaciones]
            resultados = sorted((r for r in resultados if r.document.organization.upper() in preferidas),
                                key=lambda r: preferidas.index(r.document.organization.upper()))
            return {"consulta": q or None, "organizaciones": preferidas, "resultados": a_json(resultados[:12])}

    # --- SEC-03 / NFR-06 -------------------------------------------------------------------------------

    @router.get("/pacientes/{paciente_id}/privacidad")
    def privacidad(paciente_id: int, request: Request):
        from privacidad.tratamiento_datos import historial_autorizaciones, inicializar_esquema

        with contexto(request, paciente_id) as ctx:
            if ctx.expediente_id is None:
                return {"autorizaciones": []}
            inicializar_esquema(ctx.conn_exp)
            return {"autorizaciones": a_json(historial_autorizaciones(ctx.conn_exp, ctx.expediente_id))}

    # --- Órdenes médicas: el oncólogo prescribe, enfermería suministra ---------------------------------

    def _decision_vigente(ctx: Contexto) -> Optional[dict]:
        """La decisión de tratamiento del oncólogo (TX-04), como punto de partida de las órdenes."""
        try:
            from clinical_decision.registro import obtener_decision_vigente

            d = obtener_decision_vigente(ctx.conn_exp, ctx.expediente_id) if ctx.expediente_id else None
        except sqlite3.Error:
            return None
        if d is None or getattr(d, "tipo_decision", None) == "reject":
            return None
        regimen = getattr(d, "regimen_final_id", None) or getattr(d, "regimen_sugerido_id", None)
        farmacos: List[str] = []
        try:
            snapshot = getattr(d, "recomendacion_ia_snapshot", None) or {}
            snapshot = json.loads(snapshot) if isinstance(snapshot, str) else snapshot
            for c in snapshot.get("candidatos") or []:
                if c.get("regimen_id") == regimen:
                    farmacos = list(c.get("farmacos") or [])
        except (TypeError, ValueError):
            pass
        return {"id": d.id, "fecha": d.fecha, "tipo": d.tipo_decision, "regimen": regimen, "farmacos": farmacos}

    @router.get("/pacientes/{paciente_id}/ordenes")
    def ordenes(paciente_id: int, request: Request):
        from historia_clinica import ordenes_medicas as om

        with contexto(request, paciente_id, Accion.VER_ORDENES_MEDICAS) as ctx:
            if ctx.expediente_id is None:
                lista, horario, decision = [], [], None
            else:
                lista = om.ordenes_de(ctx.conn_exp, ctx.expediente_id)
                horario = om.horario(ctx.conn_exp, [ctx.expediente_id], horas=48)
                decision = _decision_vigente(ctx)
            ctx.auditar(TipoAccion.VER, "Órdenes médicas y horario de administración")
            return {"ordenes": [o.a_dict() for o in lista], "horario": [d.a_dict() for d in horario], "decision": decision,
                    "vias": om.VIAS, "frecuencias": {str(k): v for k, v in om.FRECUENCIAS.items()},
                    "puede_prescribir": verificar_permiso(ctx.usuario, Accion.PRESCRIBIR_MEDICAMENTO).permitido}

    @router.post("/pacientes/{paciente_id}/ordenes")
    async def prescribir(paciente_id: int, request: Request):
        from historia_clinica import ordenes_medicas as om

        datos = await _cuerpo(request)
        with contexto(request, paciente_id, Accion.PRESCRIBIR_MEDICAMENTO, crear_expediente=True) as ctx:
            decision = _decision_vigente(ctx)
            try:
                orden = om.prescribir(ctx.conn_exp, ctx.exigir_expediente(), medicamento=str(datos.get("medicamento") or ""),
                                      dosis=str(datos.get("dosis") or ""), via=str(datos.get("via") or ""),
                                      intervalo_horas=datos.get("intervalo_horas"), fecha_inicio=str(datos.get("fecha_inicio") or ""),
                                      hora_inicio=str(datos.get("hora_inicio") or ""), fecha_fin=datos.get("fecha_fin") or None,
                                      indicaciones=datos.get("indicaciones"), ordenado_por=ctx.autor,
                                      decision_id=decision["id"] if decision and datos.get("desde_decision") else None)
            except om.ErrorOrden as exc:
                raise HTTPException(status_code=400, detail={"errores": [{"campo": c, "mensaje": m} for c, m in exc.errores]}) from exc
            ctx.auditar(TipoAccion.EDITAR, f"Orden médica #{orden.id}: {orden.medicamento} {orden.dosis}")
            return orden.a_dict()

    @router.post("/pacientes/{paciente_id}/ordenes/{orden_id}/suspender")
    async def suspender_orden(paciente_id: int, orden_id: int, request: Request):
        from historia_clinica import ordenes_medicas as om

        datos = await _cuerpo(request)
        with contexto(request, paciente_id, Accion.PRESCRIBIR_MEDICAMENTO) as ctx:
            try:
                orden = om.suspender(ctx.conn_exp, ctx.exigir_expediente(), orden_id, suspendida_por=ctx.autor, motivo=str(datos.get("motivo") or ""))
            except om.ErrorOrden as exc:
                raise HTTPException(status_code=400, detail={"errores": [{"campo": c, "mensaje": m} for c, m in exc.errores]}) from exc
            ctx.auditar(TipoAccion.EDITAR, f"Orden médica #{orden.id} suspendida")
            return orden.a_dict()

    def _pacientes_del_alcance(request: Request, accion: Accion):
        """(usuario, conexiones, {id_expediente: paciente}) de los pacientes que la persona puede ver."""
        from frontend.servidor import MENSAJE_SIN_ASIGNACION
        from historia_clinica.db import conectar_expediente
        from patients import api as papi

        usuario, _nombre = _identidad(request)
        _permiso(usuario, accion)
        oncologos = pasarela.oncologos_visibles(usuario)
        if not oncologos:
            raise HTTPException(status_code=403, detail=MENSAJE_SIN_ASIGNACION)
        pedido = request.query_params.get("equipo")
        if pedido and pedido.isdigit() and int(pedido) in oncologos:
            oncologos = [int(pedido)]
        return usuario, oncologos, papi.db.conectar(papi.DB_PATH, check_same_thread=False), conectar_expediente(papi._ruta_expediente(), check_same_thread=False)

    @router.get("/enfermeria/horario")
    def horario_enfermeria(request: Request, horas: int = 24):
        """Lo que toca administrar en las próximas horas a los pacientes del equipo, en orden de hora."""
        from historia_clinica import ordenes_medicas as om

        usuario, oncologos, conn, conn_exp = _pacientes_del_alcance(request, Accion.VER_ORDENES_MEDICAS)
        try:
            om.inicializar_esquema(conn_exp)
            con_ordenes = [f[0] for f in conn_exp.execute("SELECT DISTINCT paciente_id FROM ordenes_medicamento WHERE suspendida_en IS NULL")]
            marcas = ",".join("?" * len(oncologos))
            pacientes = {}
            for eid in con_ordenes:
                ficha = conn_exp.execute("SELECT identificacion FROM pacientes WHERE id = ?", (eid,)).fetchone()
                if ficha is None:
                    continue
                fila = conn.execute(f"SELECT id, nombre_completo, numero_identificacion FROM pacientes WHERE numero_identificacion = ? "
                                    f"AND oncologo_id IN ({marcas})", (ficha[0], *oncologos)).fetchone()
                if fila is not None:
                    pacientes[eid] = {"id": fila[0], "nombre": fila[1], "identificacion": fila[2]}
            dosis = om.horario(conn_exp, list(pacientes), horas=max(1, min(int(horas), 72)))
            for p in pacientes.values():
                registrar_acceso(conn, usuario.id, TipoAccion.VER, paciente_id=p["id"], detalle="Horario de administración de medicamentos")
            return {"dosis": [{**d.a_dict(), "paciente": pacientes[d.paciente_id]} for d in dosis],
                    "pacientes": list(pacientes.values()), "horas": horas}
        finally:
            conn_exp.close()
            conn.close()

    @router.get("/admision/pacientes")
    def admision(request: Request, q: str = ""):
        """Admisiones: los pacientes del equipo con sus datos de admisión (sin datos clínicos) y su consentimiento."""
        from privacidad.consentimiento_ia import estado_consentimiento_ia

        usuario, oncologos, conn, conn_exp = _pacientes_del_alcance(request, Accion.VER_DATOS_ADMISION)
        try:
            marcas = ",".join("?" * len(oncologos))
            texto = f"%{q.strip()}%"
            filas = conn.execute(
                f"SELECT id, nombre_completo, fecha_nacimiento, sexo, tipo_identificacion, numero_identificacion, oncologo_id "
                f"FROM pacientes WHERE oncologo_id IN ({marcas}) AND (nombre_completo LIKE ? OR numero_identificacion LIKE ?) "
                f"ORDER BY id DESC LIMIT 30", (*oncologos, texto, texto)).fetchall()
            resultado = []
            for f in filas:
                exp = conn_exp.execute("SELECT id FROM pacientes WHERE identificacion = ?", (f[5],)).fetchone()
                consentimiento = estado_consentimiento_ia(conn_exp, exp[0]).etiqueta if exp else "pendiente"
                resultado.append({"id": f[0], "nombre_completo": f[1], "fecha_nacimiento": f[2], "sexo": f[3], "tipo_identificacion": f[4],
                                  "numero_identificacion": f[5], "oncologo_id": f[6], "consentimiento_ia": consentimiento})
            return {"pacientes": resultado}
        finally:
            conn_exp.close()
            conn.close()

    # --- DOC-01 ----------------------------------------------------------------------------------------

    def _documentos():
        from documentos_clinicos.carga_documentos import crear_conexion as conectar_docs

        ruta = Path(os.environ.get("COPILOTO_DOCUMENTOS_DB") or RAIZ / "data" / "documentos.db")
        ruta.parent.mkdir(parents=True, exist_ok=True)
        carpeta = Path(os.environ.get("COPILOTO_DOCUMENTOS_DIR") or ruta.parent / "documentos")
        return conectar_docs(str(ruta)), carpeta

    @router.get("/pacientes/{paciente_id}/documentos")
    def documentos(paciente_id: int, request: Request):
        from documentos_clinicos.carga_documentos import listar_documentos_de_paciente

        with contexto(request, paciente_id) as ctx:
            if ctx.expediente_id is None:
                return []
            conn_docs, _carpeta = _documentos()
            try:
                return [{k: v for k, v in a_json(d).items() if k != "ruta_almacenamiento"}
                        for d in listar_documentos_de_paciente(conn_docs, ctx.expediente_id)]
            finally:
                conn_docs.close()

    @router.post("/pacientes/{paciente_id}/documentos")
    async def cargar_documento(paciente_id: int, request: Request):
        from documentos_clinicos.carga_documentos import DocumentoInvalidoError, cargar_documento_clinico

        datos = await _cuerpo(request)
        nombre = _texto(datos, "nombre", "el nombre del archivo", 200)
        try:
            contenido = base64.b64decode(str(datos.get("contenido_base64") or ""), validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=400, detail={"errores": [{"campo": "archivo", "mensaje": "No se pudo leer el archivo."}]})
        if len(contenido) > TAMANO_MAXIMO_DOCUMENTO:
            raise HTTPException(status_code=400, detail={"errores": [{"campo": "archivo", "mensaje": "El archivo supera los 15 MB."}]})
        with contexto(request, paciente_id, Accion.EDITAR_EXPEDIENTE, crear_expediente=True) as ctx:
            conn_docs, carpeta = _documentos()
            try:
                doc = cargar_documento_clinico(conn_docs, ctx.conn_exp, ctx.exigir_expediente(), Path(nombre).name, contenido,
                                               ctx.usuario.nombre_usuario, carpeta)
            except DocumentoInvalidoError as exc:
                raise HTTPException(status_code=400, detail={"errores": [{"campo": "archivo", "mensaje": str(exc)}]}) from exc
            finally:
                conn_docs.close()
            ctx.auditar(TipoAccion.EDITAR, f"Documento cargado ({doc.tipo_documento})")
            respuesta = {k: v for k, v in a_json(doc).items() if k != "ruta_almacenamiento"}
            respuesta["procesamiento"] = _indexar_documento(ctx, doc, contenido)
            return respuesta

    def _indexar_documento(ctx: Contexto, doc, contenido: bytes) -> dict:
        """Base de conocimiento del asistente: extraer el texto, trocearlo, calcular embeddings y guardarlos.
        Solo con consentimiento de IA (el texto va a OpenAI para los embeddings) y seudonimizado (NFR-04)."""
        from asistente.fragmentos import Fragmento, fragmentos_de_documento
        from asistente.indice import indice
        from privacidad.consentimiento_ia import estado_consentimiento_ia
        from privacidad.minimizacion import seudonimizar_texto

        if not estado_consentimiento_ia(ctx.conn_exp, ctx.expediente_id).ia_habilitada:
            return {"indexado": False, "fragmentos": 0, "mensaje": "Guardado en el expediente. Sin consentimiento de IA no se agrega a la base del asistente."}
        trozos = fragmentos_de_documento(doc.id, ctx.expediente_id, doc.nombre_archivo_original, contenido, doc.extension)
        if not trozos:
            return {"indexado": False, "fragmentos": 0, "mensaje": "Guardado en el expediente. No tiene texto que el asistente pueda leer (imagen o DICOM)."}
        ficha = ctx.conn_exp.execute("SELECT nombre, identificacion FROM pacientes WHERE id = ?", (ctx.expediente_id,)).fetchone()
        trozos = [Fragmento(t.id, seudonimizar_texto(t.texto, nombre=ficha[0], identificaciones=[ficha[1]] if ficha[1] else []), t.tipo, t.origen,
                            t.paciente_id, (doc.cargado_en or "")[:10], t.titulo, t.metadatos) for t in trozos]
        try:
            agregados = indice().agregar_documento(trozos)
        except Exception as exc:  # noqa: BLE001 - el documento ya quedó guardado; el índice se puede rehacer
            return {"indexado": False, "fragmentos": 0, "mensaje": f"Guardado en el expediente, pero no se pudo procesar para el asistente ({type(exc).__name__})."}
        return {"indexado": True, "fragmentos": agregados, "mensaje": f"Procesado: {agregados} fragmentos agregados a la base de conocimiento del asistente."}

    @router.get("/pacientes/{paciente_id}/documentos/{documento_id}/contenido")
    def contenido_documento(paciente_id: int, documento_id: int, request: Request):
        from documentos_clinicos.carga_documentos import leer_contenido_documento, obtener_documento_por_id

        tipos = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".dcm": "application/dicom"}
        with contexto(request, paciente_id) as ctx:
            conn_docs, _carpeta = _documentos()
            try:
                try:
                    doc = obtener_documento_por_id(conn_docs, documento_id)
                except KeyError:
                    doc = None
                if doc is None or doc.paciente_id != ctx.expediente_id:
                    raise HTTPException(status_code=404, detail="No existe ese documento para este paciente.")
                contenido = leer_contenido_documento(doc)
            finally:
                conn_docs.close()
            ctx.auditar(TipoAccion.VER, f"Documento #{documento_id} descargado")
            nombre = Path(doc.nombre_archivo_original).name.replace('"', "")
            return Response(contenido, media_type=tipos.get(doc.extension, "application/octet-stream"), headers={
                "Content-Disposition": f'attachment; filename="{nombre}"', "Cache-Control": "no-store"})

    # --- Agente de tratamiento (GPT) ------------------------------------------------------------------

    @router.post("/pacientes/{paciente_id}/agente")
    async def agente_mensaje(paciente_id: int, request: Request):
        datos = await _cuerpo(request)
        mensaje = _texto(datos, "mensaje", "tu mensaje", 2000)
        with contexto(request, paciente_id, solo_oncologia=True) as ctx:
            eid = ctx.exigir_expediente()
            return agentes.enviar(ctx.usuario, ctx.paciente.id, eid, mensaje, datos.get("hilo"))

    @router.post("/pacientes/{paciente_id}/agente/{hilo}/decision")
    async def agente_decision(paciente_id: int, hilo: str, request: Request):
        datos = await _cuerpo(request)
        with contexto(request, paciente_id, solo_oncologia=True) as ctx:
            eid = ctx.exigir_expediente()
            if datos.get("aprobar") and not verificar_permiso(ctx.usuario, Accion.CONFIRMAR_TRATAMIENTO).permitido:
                raise HTTPException(status_code=403, detail="Tu rol no puede aprobar acciones del asistente.")
            return agentes.decidir(ctx.usuario, ctx.paciente.id, eid, hilo, bool(datos.get("aprobar")),
                                   (datos.get("motivo") or "").strip() or None)

    return router
