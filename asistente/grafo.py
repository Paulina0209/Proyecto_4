"""El agente conversacional: un grafo de LangGraph (``StateGraph``), nodo por nodo.

    validar_intencion ─► resolver_paciente ─┬─► recuperar ─► evaluar_contexto ─┬─► responder ─► guardar_historial
                                            │                                   └─► rechazar  ─► guardar_historial
                                            ├─► aclarar ──────────────────────────────────────► guardar_historial
                                            └─► (saludo) responder_saludo ────────────────────► guardar_historial

Control de alucinaciones (cinco estrategias a la vez):

    1. Umbral mínimo de similitud (``COPILOTO_UMBRAL_SIMILITUD``) para aceptar un fragmento.
    2. Nodo dedicado (``evaluar_contexto``) que decide si el contexto alcanza ANTES de redactar.
    3. Prompt que obliga a responder solo con el contexto y a citar cada afirmación con su id.
    4. Verificación posterior: las citas que no están en el contexto se descartan; una
       respuesta sin ninguna cita válida se reemplaza por la respuesta extractiva.
    5. Rechazo explícito: "No tengo suficiente información en mi base de conocimiento…".

Además, las funciones de apoyo a la decisión (DX-02, EST-01, TX-01, HC-05, IA-01) se
consultan como datos estructurados y sus fuentes son ids reales del expediente, que la
interfaz resalta en la historia clínica.
"""

from __future__ import annotations

import json
import operator
import re
import time
from dataclasses import dataclass, field
from typing import Annotated, Any, Callable, Dict, List, Optional, Sequence, Tuple, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from asistente import MENSAJE_SIN_INFORMACION, llm
from asistente import config as ajustes
from asistente.intencion import ETIQUETAS, detectar_intencion, mencion_de_paciente, necesita_paciente

SUGERENCIA_DOCUMENTOS = ("Si la información existe en otro documento, cárgalo en la sección Documentos del paciente "
                         "(o registra la consulta) y vuelve a preguntar.")
_CITA = re.compile(r"\[([a-z]+(?:-[\w.]+)+)\]", re.IGNORECASE)

SECCION_HC = {"consulta": "consultas", "laboratorio": "laboratorios", "imagenologia": "imagenes", "biomarcador": "biomarcadores",
              "antecedente": "antecedentes", "dato": "datos", "ficha": "ficha", "documento": "documentos", "guia": "guias",
              "orden": "ordenes"}


@dataclass
class Dependencias:
    """Lo que el grafo necesita de afuera (lo arma la pasarela con la identidad de la sesión)."""

    usuario_id: int
    conn_exp: Any
    indice: Any
    #: texto -> [(paciente_id, nombre, identificacion)] entre los pacientes DEL MÉDICO
    buscar_pacientes: Callable[[str], List[Tuple[int, str, str]]]
    #: paciente_id (base de pacientes) -> (expediente_id o None, nombre)
    expediente_de: Callable[[int], Tuple[Optional[int], str]]
    guardar: Optional[Callable[[Dict[str, Any]], None]] = None
    #: "oncologia" o "enfermeria": enfermería conversa sobre las órdenes médicas (lo que suministra) y los datos.
    perfil: str = "oncologia"


#: Lo que enfermería puede pedirle al asistente; el apoyo a la decisión es del oncólogo tratante.
INTENCIONES_ENFERMERIA = ("medicacion", "dato", "saludo")
MENSAJE_FUERA_DE_ROL = ("Como enfermería, te ayudo con las órdenes médicas de tus pacientes (medicamentos, dosis, vías y horarios) y con los "
                        "datos de su expediente. El diagnóstico, la estadificación y las decisiones de tratamiento son del oncólogo tratante.")


class Estado(TypedDict, total=False):
    pregunta: str
    paciente_activo: Optional[int]
    historia: List[Dict[str, Any]]
    intencion: str
    paciente: Optional[Dict[str, Any]]
    contexto: List[Dict[str, Any]]
    estructurado: Dict[str, Any]
    suficiente: bool
    motivo: str
    respuesta: str
    estado: str
    opciones: List[Dict[str, Any]]
    fuentes: List[Dict[str, Any]]
    modelo: Optional[str]
    pasos: Annotated[List[Dict[str, Any]], operator.add]


def _paso(nodo: str, titulo: str, detalle: str = "", **extra) -> Dict[str, Any]:
    return {"nodo": nodo, "titulo": titulo, "detalle": detalle, "t": round(time.time(), 3), **extra}


def _deps(config_: RunnableConfig) -> Dependencias:
    return config_["configurable"]["deps"]


# ---------------------------------------------------------------------------
# Nodos
# ---------------------------------------------------------------------------


def validar_intencion(estado: Estado, config: RunnableConfig) -> Estado:
    intencion = detectar_intencion(estado["pregunta"])
    pasos = [_paso("validar_intencion", "Entendí la pregunta", ETIQUETAS[intencion], intencion=intencion)]
    if _deps(config).perfil == "enfermeria" and intencion not in INTENCIONES_ENFERMERIA:
        return {"intencion": intencion, "estado": "fuera_de_rol", "respuesta": MENSAJE_FUERA_DE_ROL,
                "pasos": pasos + [_paso("validar_intencion", "Fuera del alcance de enfermería", "Es del oncólogo tratante")]}
    return {"intencion": intencion, "pasos": pasos}


def resolver_paciente(estado: Estado, config: RunnableConfig) -> Estado:
    from privacidad.consentimiento_ia import estado_consentimiento_ia

    deps = _deps(config)
    if estado.get("estado") == "fuera_de_rol":
        return {}
    if not necesita_paciente(estado["intencion"]):
        return {"paciente": None, "pasos": [_paso("resolver_paciente", "No necesita un paciente", "Se busca en las guías clínicas")]}
    mencion = mencion_de_paciente(estado["pregunta"]).texto
    elegido: Optional[int] = None
    if mencion:
        candidatos = deps.buscar_pacientes(mencion)
        if len(candidatos) == 1:
            elegido = candidatos[0][0]
        elif len(candidatos) > 1:
            opciones = [{"paciente_id": c[0], "nombre": c[1], "identificacion": c[2]} for c in candidatos[:6]]
            return {"estado": "aclaracion", "opciones": opciones,
                    "respuesta": f"Encontré {len(candidatos)} pacientes que coinciden con «{mencion}». ¿Sobre cuál me preguntas?",
                    "pasos": [_paso("resolver_paciente", "Varios pacientes coinciden", mencion)]}
    if elegido is None:
        elegido = estado.get("paciente_activo")
    if elegido is None:
        return {"estado": "aclaracion", "opciones": [],
                "respuesta": "¿Sobre qué paciente me preguntas? Ábrelo en el panel de la derecha o escribe su nombre o su id (por ejemplo P-0016350).",
                "pasos": [_paso("resolver_paciente", "Falta el paciente", "Se pide aclaración en vez de adivinar")]}
    expediente_id, nombre = deps.expediente_de(elegido)
    paciente = {"id": elegido, "expediente_id": expediente_id, "nombre": nombre}
    if expediente_id is None:
        return {"paciente": paciente, "estado": "rechazada", "respuesta": f"{nombre} todavía no tiene expediente clínico. {SUGERENCIA_DOCUMENTOS}",
                "pasos": [_paso("resolver_paciente", f"Paciente: {nombre}", "Sin expediente clínico")]}
    consentimiento = estado_consentimiento_ia(deps.conn_exp, expediente_id)
    if not consentimiento.ia_habilitada:
        deps.indice.olvidar_paciente(expediente_id)
        return {"paciente": paciente, "estado": "rechazada",
                "respuesta": f"No puedo usar la información de {nombre}: {consentimiento.motivo} Las funciones de IA requieren su consentimiento "
                             "informado. Su historia clínica sigue disponible en el panel.",
                "pasos": [_paso("resolver_paciente", f"Paciente: {nombre}", "Sin consentimiento de IA vigente: no se consulta nada")]}
    return {"paciente": paciente, "pasos": [_paso("resolver_paciente", f"Paciente: {nombre}", "Consentimiento de IA vigente", paciente=paciente)]}


#: Resultados estructurados del sistema (no dependen de la similitud).
RESULTADOS = ("resumen", "dato", "diagnostico", "estadificacion", "tratamiento", "faltantes", "medicacion")
ETIQUETA_SECCION = {"ficha": "Ficha", "biomarcador": "Biomarcador", "consulta": "Consulta", "imagenologia": "Imagen",
                    "laboratorio": "Laboratorio", "antecedente": "Antecedente", "dato": "Dato clínico", "documento": "Documento",
                    "orden": "Orden médica"}
#: Cuántos registros de cada sección entran al panorama de un resumen (los más recientes).
PANORAMA = (("ficha", 1), ("biomarcador", 6), ("consulta", 3), ("imagenologia", 3), ("laboratorio", 5), ("antecedente", 3), ("dato", 6))


def _panorama(por_id: Dict[str, Any]) -> List[str]:
    """Ids de los registros clave del expediente para resumir el caso, sección por sección."""
    ids: List[str] = []
    for origen, cuantos in PANORAMA:
        de_origen = [f for f in por_id.values() if f.origen == origen]
        de_origen.sort(key=lambda f: str(f.fecha or ""), reverse=True)
        ids += [f.id for f in de_origen[:cuantos]]
    return ids


def _pregunta_previa(estado: Estado) -> Optional[str]:
    """La última pregunta del médico en esta conversación (para entender una repregunta)."""
    for m in reversed(estado.get("historia") or []):
        if m.get("rol") == "medico" and (m.get("texto") or "").strip() and m["texto"].strip() != estado["pregunta"].strip():
            return m["texto"].strip()
    return None


def _fuente(fid: str, texto: str, metadatos: Dict[str, Any], similitud: Optional[float]) -> Dict[str, Any]:
    origen = str(metadatos.get("origen") or fid.split("-", 1)[0])
    return {"id": fid, "texto": texto, "origen": origen, "seccion": SECCION_HC.get(origen, origen), "tipo": metadatos.get("tipo"),
            "fecha": metadatos.get("fecha") or None, "titulo": metadatos.get("titulo") or None,
            "similitud": None if similitud is None else round(similitud, 3)}


def recuperar(estado: Estado, config: RunnableConfig) -> Estado:
    from asistente.fragmentos import fragmentos_del_expediente

    deps = _deps(config)
    intencion, pregunta = estado["intencion"], estado["pregunta"]
    paciente = estado.get("paciente") or {}
    eid = paciente.get("expediente_id")
    contexto: List[Dict[str, Any]] = []
    estructurado: Dict[str, Any] = {}
    pasos = []
    por_id: Dict[str, Any] = {}

    # Una repregunta («dice estadio 4, ¿cómo que no sabes?») se busca junto con la pregunta anterior del médico.
    consulta = pregunta if not (previa := _pregunta_previa(estado)) else f"{previa}\n{pregunta}"
    if eid is not None:
        fragmentos = fragmentos_del_expediente(deps.conn_exp, eid)
        por_id = {f.id: f for f in fragmentos}
        nuevos = deps.indice.sincronizar_paciente(eid, fragmentos)
        pasos.append(_paso("recuperar", "Indexé el expediente", f"{len(fragmentos)} fragmentos" + (f" ({nuevos} recalculados)" if nuevos else " (ya al día)")))
        for r in deps.indice.buscar(consulta, paciente_id=eid, k=8):
            contexto.append(_fuente(r.id, r.texto, r.metadatos, r.similitud))
    if intencion in ("evidencia", "tratamiento"):
        deps.indice.asegurar_guias()
        for r in deps.indice.buscar(consulta, tipo="guia", k=5):
            contexto.append(_fuente(r.id, r.texto, r.metadatos, r.similitud))

    def citar(ids: Sequence[str]) -> List[str]:
        validos = []
        for fid in ids:
            f = por_id.get(fid)
            if f is not None and fid not in validos:
                validos.append(fid)
                ya = next((c for c in contexto if c["id"] == fid), None)
                if ya is None:
                    contexto.append({**_fuente(fid, f.texto, f.metadatos_chroma(), None), "estructurado": True})
                else:
                    ya["estructurado"] = True  # lo usa un resultado del sistema: entra aunque su similitud sea baja
        return validos

    if eid is not None:
        citar([f"paciente-{eid}"])  # la ficha (diagnóstico y estadio registrados) acompaña siempre al paciente
        if intencion == "resumen":
            # Un resumen no se busca por parecido («resume el caso» no se parece a ningún registro): se arma el panorama.
            estructurado["resumen"] = {"fuentes": citar(_panorama(por_id))}
            pasos.append(_paso("recuperar", "Armé el panorama del caso", f"{len(estructurado['resumen']['fuentes'])} registros clave del expediente"))
        elif intencion == "medicacion":
            # Solo lo ORDENADO por el oncólogo: nada de dosis sugeridas por el modelo ni por las guías.
            from datetime import datetime, timedelta

            from historia_clinica.ordenes_medicas import dosis_programadas, ordenes_de

            todas = ordenes_de(deps.conn_exp, eid)
            activas = [o for o in todas if o.activa]
            ahora = datetime.now().replace(second=0, microsecond=0)
            proximas = dosis_programadas(activas, ahora - timedelta(hours=2), ahora + timedelta(hours=24))
            suspendidas = [o for o in todas if o.suspendida_en][:3]
            estructurado["medicacion"] = {
                "activas": [{"id": f"orden-{o.id}", "texto": o.texto()} for o in activas],
                "proximas": [{"orden": f"orden-{d.orden_id}", "momento": d.momento, "medicamento": d.medicamento, "dosis": d.dosis, "via": d.via}
                             for d in proximas[:12]],
                "suspendidas": [{"id": f"orden-{o.id}", "texto": o.texto()} for o in suspendidas],
                "fuentes": citar([f"orden-{o.id}" for o in activas + suspendidas] or [f"paciente-{eid}"]),
                "ahora": ahora.isoformat(timespec="minutes")}
            pasos.append(_paso("recuperar", "Consulté las órdenes médicas", f"{len(activas)} activas · {len(proximas)} dosis en las próximas 24 h"))
        elif intencion == "dato":
            from clinical_query import NaturalLanguageClinicalQueryService, SQLiteClinicalRepository
            from clinical_query.service import Clarification

            r = NaturalLanguageClinicalQueryService(SQLiteClinicalRepository(deps.conn_exp)).ask(
                str(eid), pregunta, clarification=Clarification(confirm_active_patient=True))
            if r.found and r.datum is not None:
                estructurado["dato"] = {"respuesta": r.answer, "fuentes": citar([r.datum.source_id])}
            elif r.needs_clarification:
                estructurado["aclaracion"] = {"mensaje": r.answer, "opciones": [o for a in r.ambiguities for o in a.options]}
            pasos.append(_paso("recuperar", "Busqué el dato exacto", "Encontrado" if estructurado.get("dato") else "Sin coincidencia exacta"))
        elif intencion == "diagnostico":
            from dx_clinica.builder import construir_diagnosticos_diferenciales
            from dx_clinica.incertidumbre import analizar_incertidumbre
            from expediente.adapters import obtener_hallazgos_de_paciente
            from expediente.repository import obtener_paciente

            res = construir_diagnosticos_diferenciales(obtener_paciente(deps.conn_exp, eid), obtener_hallazgos_de_paciente(deps.conn_exp, eid))
            inc = analizar_incertidumbre(res)
            estructurado["diagnostico"] = {
                "candidatos": [{"nombre": c.nombre, "orden": c.orden,
                                "sustento": [{"criterio": cr.descripcion, "fuentes": citar(cr.hallazgos_ids)} for cr in c.criterios_sustentados],
                                "sin_sustento": list(c.criterios_sin_sustento)} for c in res.candidatos],
                "advertencia": res.advertencia_sin_sustento, "incertidumbre": inc.mensaje,
                "indagar": list(inc.informacion_adicional_sugerida), "disclaimer": res.disclaimer}
            pasos.append(_paso("recuperar", "Armé el diagnóstico diferencial", f"{len(res.candidatos)} candidatos con sustento"))
        elif intencion == "estadificacion":
            from estadificacion.builder import proponer_estadificacion
            from estadificacion.incompleta import analizar_estadificacion_incompleta

            prop = proponer_estadificacion(deps.conn_exp, eid)
            inc = analizar_estadificacion_incompleta(prop)
            fuentes = citar([fid for c in prop.componentes for fid in c.fuente_ids] + [f"paciente-{eid}"])
            fila = deps.conn_exp.execute("SELECT estadio FROM pacientes WHERE id = ?", (eid,)).fetchone()
            estructurado["estadificacion"] = {"registrado": (fila[0] if fila else None) or None,
                                              "sistema": f"{prop.sistema_nombre} (v{prop.sistema_version})", "estadio": prop.estadio_global,
                                              "fundamento": prop.fundamento_global, "componentes": [{"codigo": c.codigo, "valor": c.valor} for c in prop.componentes],
                                              "faltan": [c.codigo for c in inc.componentes_indeterminados], "mensaje": inc.mensaje, "fuentes": fuentes}
            pasos.append(_paso("recuperar", "Propuse la estadificación", prop.estadio_global or "Incompleta"))
        elif intencion == "tratamiento":
            from tx_clinica.tools.recommendation_tools import obtener_recomendaciones_tratamiento_por_id

            rec = json.loads(obtener_recomendaciones_tratamiento_por_id.invoke({"patient_id": eid}))
            datos = [fid for fid, f in por_id.items() if f.origen == "dato"]
            estructurado["tratamiento"] = {**rec, "fuentes": citar(datos[-8:])}
            pasos.append(_paso("recuperar", "Consulté la guía computable", rec.get("module_id") or ("Faltan datos" if rec.get("requiere_mas_datos") else "Sin guía aplicable")))
        elif intencion == "faltantes":
            from historia_clinica.informacion_faltante import evaluar_informacion_faltante

            ev = evaluar_informacion_faltante(deps.conn_exp, eid)
            estructurado["faltantes"] = {"estado": ev.estado.value, "faltantes": [f"{i.descripcion} ({i.motivo})" for i in ev.faltantes],
                                         "fuentes": citar([fid for fid in por_id if fid.startswith("dato-")][:6])}
            pasos.append(_paso("recuperar", "Revisé qué falta para decidir", f"{len(ev.faltantes)} datos faltantes"))

    umbral = ajustes.umbral_similitud()
    aceptados = [c for c in contexto if c.get("similitud") is None or c.get("estructurado") or c["similitud"] >= umbral]
    pasos.append(_paso("recuperar", "Busqué en la base vectorial", f"{len([c for c in contexto if c.get('similitud') is not None])} fragmentos; "
                       f"{len([c for c in contexto if c.get('similitud') is not None and c['similitud'] >= umbral])} superan la similitud {umbral:.2f}",
                       fuentes=[c["id"] for c in aceptados][:12]))
    return {"contexto": aceptados, "estructurado": estructurado, "pasos": pasos}


def evaluar_contexto(estado: Estado, config: RunnableConfig) -> Estado:
    """Nodo dedicado: ¿hay con qué responder sin inventar?"""
    estructurado = estado.get("estructurado") or {}
    contexto = estado.get("contexto") or []
    if "aclaracion" in estructurado:
        return {"suficiente": True, "motivo": "La pregunta es ambigua: se pide aclaración",
                "pasos": [_paso("evaluar_contexto", "La pregunta es ambigua", "Se pide aclaración")]}
    utiles = [k for k in RESULTADOS if k in estructurado and (k != "resumen" or estructurado[k]["fuentes"])]
    vectoriales = [c for c in contexto if c.get("similitud") is not None and c["similitud"] >= ajustes.umbral_similitud()]
    suficiente = bool(utiles) or bool(vectoriales)
    if estado["intencion"] == "diagnostico" and not (estructurado.get("diagnostico") or {}).get("candidatos") and not vectoriales:
        suficiente = False
    motivo = (f"Resultado del sistema: {', '.join(utiles)}" if utiles else "") + (f"; {len(vectoriales)} fragmentos relevantes" if vectoriales else "")
    return {"suficiente": suficiente, "motivo": motivo or "Nada supera el umbral de similitud",
            "pasos": [_paso("evaluar_contexto", "El contexto alcanza" if suficiente else "El contexto no alcanza", motivo or "Nada supera el umbral")]}


def _extractiva(estado: Estado) -> Tuple[str, List[str]]:
    """Respuesta sin modelo: el resultado del sistema y los fragmentos, con sus citas."""
    e = estado.get("estructurado") or {}
    lineas: List[str] = []
    citas: List[str] = []
    if "aclaracion" in e:
        return e["aclaracion"]["mensaje"], []
    if "dato" in e:
        lineas.append(f"{e['dato']['respuesta']} " + " ".join(f"[{f}]" for f in e["dato"]["fuentes"]))
        citas += e["dato"]["fuentes"]
    if "diagnostico" in e:
        d = e["diagnostico"]
        if not d["candidatos"]:
            lineas.append(d["advertencia"] or "El expediente no sustenta ningún diagnóstico diferencial.")
        for c in d["candidatos"]:
            sustento = "; ".join(f"{s['criterio']} " + " ".join(f"[{f}]" for f in s["fuentes"]) for s in c["sustento"])
            lineas.append(f"{c['orden']}. {c['nombre']}: {sustento or 'sin criterios sustentados'}.")
            citas += [f for s in c["sustento"] for f in s["fuentes"]]
        if d["indagar"]:
            lineas.append("Para reducir la incertidumbre, indagar: " + "; ".join(d["indagar"]) + ".")
        lineas.append(d["disclaimer"])
    if "medicacion" in e:
        m = e["medicacion"]
        if not m["activas"]:
            lineas.append("No hay órdenes médicas activas para este paciente. " + " ".join(f"[{f}]" for f in m["fuentes"]))
        else:
            lineas.append("Órdenes médicas activas:")
            lineas += [f"- {o['texto'].removeprefix('Orden médica: ')} [{o['id']}]" for o in m["activas"]]
            if m["proximas"]:
                lineas.append("Próximas administraciones:")
                lineas += [f"- {d['momento'].replace('T', ' ')} · {d['medicamento']} {d['dosis']} ({d['via']}) [{d['orden']}]" for d in m["proximas"]]
        if m["suspendidas"]:
            lineas.append("Suspendidas recientemente: " + "; ".join(f"{o['texto']} [{o['id']}]" for o in m["suspendidas"]))
        citas += m["fuentes"]
    if "resumen" in e:
        for fid in e["resumen"]["fuentes"]:
            c = next((x for x in estado.get("contexto") or [] if x["id"] == fid), None)
            if c is not None:
                lineas.append(f"- {ETIQUETA_SECCION.get(c['origen'], c['origen'].capitalize())}: {' '.join(c['texto'].split())[:240]} [{fid}]")
                citas.append(fid)
    if "estadificacion" in e:
        s = e["estadificacion"]
        ficha = [f for f in s["fuentes"] if f.startswith("paciente-")]
        if s.get("registrado"):
            # El estadio que ya consta en el expediente se informa siempre; EST-01 solo dice si puede verificarlo.
            lineas.append(f"Estadio registrado en el expediente: {s['registrado']}. " + " ".join(f"[{f}]" for f in ficha))
            if s["estadio"]:
                lineas.append(f"Con {s['sistema']} el copiloto calcula: {s['estadio']}"
                              + (" (coincide)." if str(s["estadio"]).strip().upper() == str(s["registrado"]).strip().upper() else " (no coincide: revisar)."))
            elif s["faltan"]:
                lineas.append(f"El copiloto no puede recalcularlo con {s['sistema']} porque el expediente no trae los componentes "
                              f"{', '.join(s['faltan'])}; se informa el registrado.")
            otras = [f for f in s["fuentes"] if f not in ficha]
            if otras:
                lineas[-1] += " " + " ".join(f"[{f}]" for f in otras)
        else:
            lineas.append(f"Estadio propuesto ({s['sistema']}): {s['estadio']}." if s["estadio"] else f"No se propone un estadio: {s['mensaje'] or s['fundamento']}")
            if s["faltan"]:
                lineas.append(f"Faltan los componentes: {', '.join(s['faltan'])}.")
            lineas[-1] += " " + " ".join(f"[{f}]" for f in s["fuentes"])
        citas += s["fuentes"]
    if "tratamiento" in e:
        t = e["tratamiento"]
        if t.get("candidatos"):
            lineas.append(f"Según la guía {t.get('module_id')}:")
            for c in t["candidatos"][:5]:
                lineas.append(f"- {c['regimen_id']}: {' + '.join(c['farmacos'])} — {' '.join((c.get('evidencia') or '').split())[:220]}")
        else:
            lineas.append(t.get("mensaje") or "No hay una guía computable aplicable.")
            for modulo, variables in (t.get("variables_faltantes_por_modulo") or {}).items():
                lineas.append(f"- Para {modulo} falta: {', '.join(variables)}.")
        if t.get("fuentes"):
            lineas.append("Datos considerados: " + " ".join(f"[{f}]" for f in t["fuentes"]))
            citas += t["fuentes"]
    if "faltantes" in e:
        f = e["faltantes"]
        lineas.append("Para decidir falta: " + ("; ".join(f["faltantes"]) if f["faltantes"] else "nada en las fases evaluadas") + ".")
    if not lineas or estado["intencion"] == "evidencia" or ("dato" not in e and estado["intencion"] == "dato"):
        for c in (estado.get("contexto") or [])[:4]:
            if c.get("similitud") is not None:
                lineas.append(f"- {c['texto'][:260]} [{c['id']}]")
                citas.append(c["id"])
    return "\n".join(lineas), citas


SISTEMA = (
    "Eres el copiloto clínico de un servicio de oncología. Respondes a un oncólogo, en español, de forma breve y precisa.\n"
    "REGLAS OBLIGATORIAS:\n"
    "1. Usa SOLO la información del CONTEXTO y del RESULTADO DEL SISTEMA. No uses conocimiento propio ni externo.\n"
    "2. Cita cada afirmación con el id de su fuente entre corchetes, por ejemplo [lab-12] o [guia-x-rules-3]. Usa solo ids que aparezcan en el contexto.\n"
    "3. Si el contexto no permite responder, escribe exactamente: \"" + MENSAJE_SIN_INFORMACION + "\"\n"
    "4. No inventes valores, fechas, diagnósticos ni dosis. Si un dato falta, di que falta.\n"
    "5. Es apoyo a la decisión: no des órdenes; la decisión es del médico.\n"
    "6. Lo registrado en el expediente (por ejemplo el estadio de la ficha [paciente-N]) es un dato válido: infórmalo aunque el "
    "sistema no pueda recalcularlo, y aclara que no se pudo verificar.\n"
    "7. En un resumen, organiza por: diagnóstico y estadio, biomarcadores, consultas y tratamiento, imágenes, laboratorios.\n"
    "8. La CONVERSACIÓN PREVIA solo sirve para entender a qué se refiere la pregunta; no es fuente ni se cita.\n"
    "9. Sobre medicamentos responde SOLO con las órdenes médicas [orden-N] y su horario: nunca sugieras dosis, vías ni horarios "
    "que no estén ordenados; si algo no está en la orden, di que hay que consultarlo con el oncólogo tratante."
)


def responder(estado: Estado, config: RunnableConfig) -> Estado:
    contexto = estado.get("contexto") or []
    ids_validos = {c["id"] for c in contexto}
    base, citas_base = _extractiva(estado)
    if "aclaracion" in (estado.get("estructurado") or {}):
        return {"respuesta": base, "estado": "aclaracion", "fuentes": [], "modelo": None,
                "opciones": [{"texto": o} for o in estado["estructurado"]["aclaracion"]["opciones"]],
                "pasos": [_paso("responder", "Pedí una aclaración", "")]}
    texto, modelo, pasos = base, None, []
    if llm.disponible():
        bloques = "\n".join(f"[{c['id']}] ({c['origen']}{', ' + str(c['fecha']) if c.get('fecha') else ''}) {c['texto']}" for c in contexto[:36])
        conversacion = "\n".join(f"{'Médico' if m.get('rol') == 'medico' else 'Copiloto'}: {' '.join(str(m.get('texto') or '').split())[:300]}"
                                 for m in (estado.get("historia") or [])[-4:])
        usuario = ((f"CONVERSACIÓN PREVIA:\n{conversacion}\n\n" if conversacion else "")
                   + f"Pregunta del oncólogo: {estado['pregunta']}\nIntención: {ETIQUETAS[estado['intencion']]}\n\n"
                   f"RESULTADO DEL SISTEMA (estructurado, ya verificado):\n{base}\n\nCONTEXTO:\n{bloques}")
        inicio = time.perf_counter()
        try:
            borrador = llm.redactar(SISTEMA, usuario).replace("[[", "[").replace("]]", "]")
            hay_resultado = any(k in (estado.get("estructurado") or {}) for k in RESULTADOS)
            if MENSAJE_SIN_INFORMACION.casefold() in borrador.casefold() and hay_resultado:
                # El sistema SÍ tiene un resultado verificado (p. ej. "faltan estos datos"): se responde con él, sin redactar.
                pasos.append(_paso("responder", "Uso el resultado del sistema", "El modelo no lo redactó; respondo con lo verificado"))
                borrador = ""
            elif MENSAJE_SIN_INFORMACION.casefold() in borrador.casefold():
                return {"respuesta": f"{MENSAJE_SIN_INFORMACION} {SUGERENCIA_DOCUMENTOS}", "estado": "rechazada", "fuentes": [], "modelo": llm.descripcion(),
                        "pasos": [_paso("responder", "El modelo no encontró sustento", "Rechazo explícito")]}
            citadas = [c for c in _CITA.findall(borrador)] if borrador else []
            invalidas = [c for c in citadas if c not in ids_validos]
            limpio = _CITA.sub(lambda m: m.group(0) if m.group(1) in ids_validos else "", borrador).strip()
            if citadas and len(invalidas) < len(citadas):
                texto, modelo = limpio, llm.descripcion()
                pasos.append(_paso("responder", f"Redacté con {modelo}", f"{time.perf_counter() - inicio:.1f} s · {len(citadas) - len(invalidas)} citas verificadas"
                                   + (f" · {len(invalidas)} descartadas por no estar en el contexto" if invalidas else "")))
            elif borrador:
                pasos.append(_paso("responder", "Descarté el texto del modelo", "No citaba fuentes del contexto: respondo solo con lo encontrado"))
        except llm.ModeloNoDisponible as exc:
            pasos.append(_paso("responder", "El modelo no respondió a tiempo", f"{exc} Respondo con lo encontrado, sin redactar"))
    else:
        pasos.append(_paso("responder", "Respuesta extractiva", "Sin modelo de lenguaje configurado"))
    citas = [c for c in dict.fromkeys(_CITA.findall(texto) + citas_base) if c in ids_validos]
    fuentes = [c for c in contexto if c["id"] in citas]
    return {"respuesta": texto, "estado": "respondida", "fuentes": fuentes, "modelo": modelo, "pasos": pasos}


def rechazar(estado: Estado, config: RunnableConfig) -> Estado:
    return {"respuesta": f"{MENSAJE_SIN_INFORMACION} {SUGERENCIA_DOCUMENTOS}", "estado": "rechazada", "fuentes": [],
            "pasos": [_paso("rechazar", "No respondo sin sustento", estado.get("motivo") or "")]}


def responder_saludo(estado: Estado, config: RunnableConfig) -> Estado:
    return {"respuesta": "Hola. Puedo buscar datos del expediente de tus pacientes, resumir un caso, apoyarte en el diagnóstico, la estadificación "
                         "o las opciones de tratamiento según las guías, y mostrarte de dónde sale cada respuesta. ¿Sobre qué paciente trabajamos?",
            "estado": "respondida", "fuentes": [], "pasos": [_paso("responder", "Saludo", "")]}


def guardar_historial(estado: Estado, config: RunnableConfig) -> Estado:
    deps = _deps(config)
    if deps.guardar is not None:
        deps.guardar(dict(estado))
    return {"pasos": [_paso("guardar_historial", "Guardé la conversación", "")]}


# ---------------------------------------------------------------------------
# Grafo
# ---------------------------------------------------------------------------


def _tras_paciente(estado: Estado) -> str:
    if estado.get("estado") in ("aclaracion", "rechazada", "fuera_de_rol"):
        return "guardar_historial"
    if estado["intencion"] == "saludo":
        return "responder_saludo"
    return "recuperar"


def construir_grafo():
    g = StateGraph(Estado)
    for nombre, funcion in (("validar_intencion", validar_intencion), ("resolver_paciente", resolver_paciente), ("recuperar", recuperar),
                            ("evaluar_contexto", evaluar_contexto), ("responder", responder), ("rechazar", rechazar),
                            ("responder_saludo", responder_saludo), ("guardar_historial", guardar_historial)):
        g.add_node(nombre, funcion)
    g.add_edge(START, "validar_intencion")
    g.add_edge("validar_intencion", "resolver_paciente")
    g.add_conditional_edges("resolver_paciente", _tras_paciente, ["recuperar", "responder_saludo", "guardar_historial"])
    g.add_edge("recuperar", "evaluar_contexto")
    g.add_conditional_edges("evaluar_contexto", lambda e: "responder" if e.get("suficiente") else "rechazar", ["responder", "rechazar"])
    g.add_edge("responder", "guardar_historial")
    g.add_edge("rechazar", "guardar_historial")
    g.add_edge("responder_saludo", "guardar_historial")
    g.add_edge("guardar_historial", END)
    return g.compile()


_GRAFO = None


def grafo():
    global _GRAFO
    if _GRAFO is None:
        _GRAFO = construir_grafo()
    return _GRAFO


def ejecutar(pregunta: str, deps: Dependencias, paciente_activo: Optional[int] = None, historia=None, al_paso=None) -> Estado:
    """Corre el grafo. ``al_paso(paso)`` recibe cada paso en cuanto ocurre (para mostrarlo en vivo)."""
    inicial: Estado = {"pregunta": pregunta, "paciente_activo": paciente_activo, "historia": historia or [], "pasos": []}
    final: Dict[str, Any] = dict(inicial)
    final["pasos"] = []
    for actualizacion in grafo().stream(inicial, config={"configurable": {"deps": deps}}, stream_mode="updates"):
        for _nodo, parcial in actualizacion.items():
            for clave, valor in (parcial or {}).items():
                if clave == "pasos":
                    final["pasos"] = final["pasos"] + list(valor)
                    if al_paso:
                        for p in valor:
                            al_paso(p)
                else:
                    final[clave] = valor
    return final
