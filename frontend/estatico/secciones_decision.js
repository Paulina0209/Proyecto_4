/* Apoyo a la decisión: diagnóstico (DX-01/02/03 + IA-05), estadificación (EST-01/02/03), tratamiento (TX-01..04)
   y evidencia (EV-01). Lo que propone el sistema siempre se muestra como apoyo; la decisión la registra el médico. */
import { h, anunciar } from "./dom.js";
import { api } from "./api.js";
import { fecha } from "./formato.js";
import { avisoConsentimiento, campo, cargando, casilla, formulario, insignia, listaDatos, mensaje, tabla, tarjeta, vacio } from "./ui.js";

const base = (id) => `/api/clinica/pacientes/${id}`;
const recargar = () => window.dispatchEvent(new HashChangeEvent("hashchange"));
const bloqueado = (c) => c && !c.ia_habilitada;

/* ---------------- Diagnóstico ---------------- */

export async function secDiagnostico(ctx, p, consentimiento) {
  if (bloqueado(consentimiento)) return avisoConsentimiento(consentimiento.motivo);
  const sospecha = ctx.consulta.get("sospecha") || "";
  const r = await api(`${base(p.id)}/diagnostico`, { consulta: { sospecha } });
  const dif = r.diferencial;
  const textos = r.textos_hallazgos || {};
  const inc = r.incertidumbre;

  const candidatos = dif.candidatos.length ? dif.candidatos.map((c) => h("section", { class: "tarjeta" },
    h("h3", {}, `${c.orden}. ${c.nombre}`),
    h("p", { class: "tenue" }, c.resumen_sustento || ""),
    h("ul", { class: "lista-limpia" },
      c.criterios_sustentados.map((cr) => h("li", {}, insignia({ texto: "Con sustento", tono: "ok", icono: "ok" }), " ", cr.descripcion,
        h("ul", {}, cr.hallazgos_ids.slice(0, 3).map((id) => h("li", { class: "tenue" }, `${id}: ${(textos[id] || "").slice(0, 180)}`))))),
      c.criterios_sin_sustento.map((d) => h("li", {}, insignia({ texto: "Sin dato", tono: "neutra", icono: "info" }), " ", d)))))
    : [mensaje("info", "Sin candidatos con sustento", dif.advertencia_sin_sustento || "El expediente no sustenta ningún diagnóstico diferencial.")];

  const explicaciones = (r.explicaciones.explanations || []).map((e) => h("li", {},
    h("strong", {}, e.recommendation), h("p", { class: "tenue" }, e.rationale),
    e.confidence ? insignia({ texto: `Confianza: ${e.confidence}`, tono: "info", icono: "info" }) : null,
    (e.limitations || []).length ? h("p", { class: "ayuda" }, `Limitaciones: ${e.limitations.join("; ")}`) : null));

  const vigente = r.decision_vigente;
  const juicio = ctx.sesion.puede_juicio_dx ? formulario({ campos: [
    campo({ nombre: "diagnostico", etiqueta: "Tu juicio diagnóstico", tipo: "textarea", requerido: true,
      ayuda: "Queda registrado como la decisión vigente y se compara con lo que sugirió el sistema (AUD-02)." })],
  textoBoton: "Registrar juicio clínico", enviar: (v) => api(`${base(p.id)}/diagnostico/juicio`, { metodo: "POST", cuerpo: v }),
  alExito: () => { anunciar("Juicio clínico registrado."); recargar(); } }) : null;

  const estudios = r.estudios;
  return h("div", {},
    mensaje("info", null, dif.disclaimer),
    h("div", { class: "cifras" },
      h("div", { class: "cifra" }, h("strong", {}, String(r.hallazgos)), h("span", {}, "hallazgos trazables en el expediente")),
      h("div", { class: "cifra" }, h("strong", {}, String(dif.candidatos.length)), h("span", {}, "diagnósticos diferenciales con sustento")),
      h("div", { class: "cifra" }, h("strong", {}, inc.hay_incertidumbre ? "Sí" : "No"), h("span", {}, "hay incertidumbre"))),
    tarjeta("Diagnóstico diferencial (DX-02)", ...candidatos),
    tarjeta("Incertidumbre y qué más indagar (DX-03)", h("p", {}, inc.mensaje),
      inc.informacion_adicional_sugerida.length ? h("ul", {}, inc.informacion_adicional_sugerida.map((s) => h("li", {}, s))) : null,
      inc.disclaimer_sugerencias ? h("p", { class: "ayuda" }, inc.disclaimer_sugerencias) : null),
    explicaciones.length ? tarjeta("Por qué lo sugiere (IA-05)", h("ul", { class: "lista-limpia" }, explicaciones)) : null,
    tarjeta("Estudios a solicitar ante una sospecha (DX-01)",
      h("form", { class: "filtros", onsubmit: (e) => {
        e.preventDefault();
        const v = new FormData(e.target).get("sospecha");
        window.location.hash = `#/pacientes/${p.id}/diagnostico${v ? `?sospecha=${encodeURIComponent(v)}` : ""}`;
      } }, campo({ nombre: "sospecha", etiqueta: "Sospecha diagnóstica", valor: sospecha, ayuda: "Ej.: progresión, toxicidad musculoesquelética, proceso infeccioso" }).nodo,
        h("div", { class: "campo" }, h("button", { type: "submit", class: "btn" }, "Sugerir estudios"))),
      estudios ? (estudios.estudios_sugeridos.length ? tabla(`Estudios sugeridos para: ${estudios.sospecha_diagnostica}`, ["#", "Estudio", "Tipo", "Por qué"],
        estudios.estudios_sugeridos.map((e) => [String(e.orden), e.nombre, e.tipo, e.justificacion]), { numericas: [0] })
        : mensaje("info", null, "No hay estudios catalogados para esa sospecha.")) : null,
      estudios && estudios.estudios_omitidos_por_redundantes.length ? h("p", { class: "tenue" },
        `No se repiten (hay uno reciente): ${estudios.estudios_omitidos_por_redundantes.map((o) => o.nombre).join(", ")}.`) : null),
    tarjeta("Decisión diagnóstica vigente",
      listaDatos([["Fuente", vigente.fuente === "apoyo_sistema" ? "Apoyo del sistema (sin juicio registrado)" : "Juicio del médico"], ["Contenido", vigente.contenido]]),
      juicio));
}

/* ---------------- Estadificación ---------------- */

export async function secEstadificacion(ctx, p, consentimiento) {
  if (bloqueado(consentimiento)) return avisoConsentimiento(consentimiento.motivo);
  const r = await api(`${base(p.id)}/estadificacion`);
  const prop = r.propuesta, inc = r.incompleta, vig = r.vigente;
  const componentes = ctx.sesion.puede_registrar ? formulario({ columnas: true, textoBoton: "Guardar componentes", campos: Object.entries(r.variables).map(([v, e]) =>
    campo({ nombre: v, etiqueta: e, ayuda: v === "clinical_m_status" ? "Ej.: cM0, cM1" : v === "clinical_n_status" ? "Ej.: cN0, cN2" : "Ej.: cT1a, cT2" })),
  enviar: (v) => api(`${base(p.id)}/estadificacion/datos`, { metodo: "POST", cuerpo: { valores: v } }), alExito: () => { anunciar("Componentes guardados."); recargar(); } }) : null;
  const confirmar = ctx.sesion.puede_confirmar_estadio ? formulario({ campos: [
    campo({ nombre: "estadio", etiqueta: "Estadio confirmado", requerido: true, valor: prop.estadio_global || "", ayuda: "Ej.: IIIA, IV" }),
    campo({ nombre: "justificacion", etiqueta: "Justificación (si difiere de la propuesta)", tipo: "textarea" })],
  textoBoton: "Confirmar estadificación", enviar: (v) => api(`${base(p.id)}/estadificacion/confirmar`, { metodo: "POST", cuerpo: v }),
  alExito: () => { anunciar("Estadificación confirmada."); recargar(); } }) : null;
  return h("div", {},
    mensaje("info", null, prop.disclaimer || "Apoyo a la decisión: no reemplaza el juicio clínico."),
    h("div", { class: "rejilla-2" },
      tarjeta("Propuesta del sistema (EST-01)", listaDatos([
        ["Sistema", `${prop.sistema_nombre || prop.sistema_id || "—"} (v${prop.sistema_version || "—"})`],
        ["Estadio propuesto", prop.estadio_global || "No se propone: faltan datos"],
        ["Fundamento", prop.fundamento_global],
      ]), prop.componentes.length ? tabla("Componentes", ["Código", "Valor", "Fuente"], prop.componentes.map((c) => [c.codigo, c.valor, (c.fuente_ids || []).join(", ")])) : null),
      tarjeta("Estadio vigente (EST-02)", listaDatos([
        ["Estadio", vig.estadio || "Sin confirmar"],
        ["Fuente", vig.fuente === "confirmacion_medico" || vig.confirmacion ? "Confirmado por el médico" : "Propuesta del sistema"],
        ["Confirmado por", vig.confirmacion ? `${vig.confirmacion.autor} · ${fecha((vig.confirmacion.registrado_en || "").slice(0, 10))}` : "—"],
      ]), confirmar)),
    !inc.estadificacion_completa ? tarjeta("Lo que falta para estadificar (EST-03)",
      h("p", {}, inc.mensaje || "La estadificación está incompleta."),
      inc.rango_estadios_posibles && inc.rango_estadios_posibles.length ? h("p", {}, h("strong", {}, "Estadios posibles: "), inc.rango_estadios_posibles.join(", ")) : null,
      h("ul", { class: "lista-limpia" }, inc.componentes_indeterminados.map((c) => h("li", {}, h("strong", {}, `${c.codigo}: `), c.criterio_pendiente,
        h("p", { class: "ayuda" }, c.informacion_requerida)))),
      componentes) : null);
}

/* ---------------- Tratamiento ---------------- */

const valoresPermitidos = (def) => [...String(def.valores || "").matchAll(/'([^']+)'/g)].map((m) => m[1]).sort();

export async function secTratamiento(ctx, p, consentimiento) {
  if (bloqueado(consentimiento)) return avisoConsentimiento(consentimiento.motivo);
  const r = await api(`${base(p.id)}/tratamiento`);
  const rec = r.recomendacion, med = r.medicacion, defs = r.definiciones;
  const estado = h("div", { role: "status", "aria-live": "polite" });

  const faltantes = new Set();
  Object.values(rec.variables_faltantes_por_modulo || {}).forEach((vs) => vs.forEach((v) => faltantes.add(v)));
  (rec.variables_faltantes_para_candidatos || []).forEach((v) => faltantes.add(v));
  const formDatos = faltantes.size && ctx.sesion.puede_registrar ? formulario({ columnas: true, textoBoton: "Guardar datos y volver a evaluar",
    campos: [...faltantes].map((v) => {
      const def = defs[v] || {};
      const opciones = valoresPermitidos(def);
      return opciones.length ? campo({ nombre: v, etiqueta: v, tipo: "select", opciones: [["", "Elegir…"], ...opciones.map((o) => [o, o])] })
        : campo({ nombre: v, etiqueta: v, tipo: def.tipo === "numeric" ? "number" : "text" });
    }),
    enviar: (v) => {
      const valores = Object.fromEntries(Object.entries(v).filter(([, x]) => x !== "").map(([k, x]) => [k, defs[k] && defs[k].tipo === "numeric" ? Number(x) : x]));
      return api(`${base(p.id)}/tratamiento/datos`, { metodo: "POST", cuerpo: { valores } });
    }, alExito: () => { anunciar("Datos guardados."); recargar(); } }) : null;

  let cuerpoRec;
  if (rec.requiere_mas_datos) cuerpoRec = [mensaje("aviso", "Faltan datos clínicos para elegir la guía", rec.mensaje), formDatos];
  else if (rec.sin_guia_aplicable) cuerpoRec = [mensaje("info", "Sin guía computable para este caso", rec.mensaje)];
  else {
    cuerpoRec = [h("p", {}, h("strong", {}, "Guía aplicada: "), rec.module_id),
      rec.variables_faltantes_para_candidatos && rec.variables_faltantes_para_candidatos.length ? mensaje("aviso", null, rec.mensaje) : null,
      (rec.candidatos || []).length ? h("ol", { class: "lista-limpia" }, rec.candidatos.map((c) => h("li", {},
        h("strong", {}, `${c.regimen_id}${c.fase ? ` (${c.fase})` : ""}`), ": ", c.farmacos.join(" + "), " ",
        insignia({ texto: c.audit_effect === "supports_prescription" ? "Respaldado por la guía" : c.audit_effect, tono: c.audit_effect === "supports_prescription" ? "ok" : "aviso", icono: "info" }),
        h("p", { class: "ayuda" }, `Regla ${c.rule_id_disparada} — ${(c.evidencia || "").replace(/\s+/g, " ")}`),
        c.advertencia_comorbilidad ? mensaje("aviso", null, c.advertencia_comorbilidad) : null,
        h("div", { class: "acciones" }, h("button", { type: "button", class: "btn sec chico", onclick: () => revisarInteracciones(c.regimen_id) }, "Revisar interacciones")))))
        : vacio("La guía no tiene candidatos para los datos actuales."),
      formDatos];
  }

  const zonaInteracciones = h("div", {});
  async function revisarInteracciones(regimen) {
    zonaInteracciones.replaceChildren(cargando("Revisando interacciones…"));
    try {
      const i = await api(`${base(p.id)}/tratamiento/interacciones`, { consulta: { regimen } });
      zonaInteracciones.replaceChildren(tarjeta(`Interacciones de ${regimen} (TX-03)`,
        i.requiere_conciliacion_medicamentos ? mensaje("aviso", "Falta conciliar la medicación", "Sin la conciliación, el sistema no puede afirmar que no hay interacciones.") : null,
        i.advertencia_cobertura_incompleta ? mensaje("aviso", null, "El catálogo de interacciones no cubre todo el régimen: revisa con farmacia.") : null,
        (i.interacciones || []).length ? h("ul", { class: "lista-limpia" }, i.interacciones.map((x) => h("li", {},
          h("strong", {}, x.descripcion || x.interaccion_id || "Interacción"), " ", x.audit_effect ? insignia({ texto: x.audit_effect, tono: "crit", icono: "alerta" }) : null,
          h("p", { class: "ayuda" }, Object.entries(x).filter(([k]) => !["descripcion", "audit_effect"].includes(k)).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(" · ")))))
          : (i.sin_interacciones_conocidas ? mensaje("ok", null, "Sin interacciones conocidas con la medicación conciliada.") : null)));
      zonaInteracciones.querySelector("h2").focus();
    } catch (err) { zonaInteracciones.replaceChildren(mensaje("error", "No se pudieron revisar las interacciones", err.mensajes[0])); }
  }

  const conciliacion = ctx.sesion.puede_registrar ? formulario({ textoBoton: "Guardar conciliación", campos: [
    campo({ nombre: "medicamentos", etiqueta: "Medicación concomitante", tipo: "textarea", ayuda: "Un medicamento por línea. Si no toma ninguno, marca la casilla de abajo." }),
    casilla({ nombre: "sin_medicacion", etiqueta: "Confirmo que no toma ninguna medicación concomitante" }),
  ], enviar: (v) => api(`${base(p.id)}/tratamiento/conciliacion`, { metodo: "POST", cuerpo: {
    medicamentos: String(v.medicamentos || "").split("\n").map((x) => x.trim()).filter(Boolean), sin_medicacion: v.sin_medicacion } }),
  alExito: () => { anunciar("Conciliación guardada."); recargar(); } }) : null;

  const candidatos = (rec.candidatos || []).map((c) => c.regimen_id);
  const decision = ctx.sesion.puede_decidir_tratamiento && candidatos.length ? formulario({ textoBoton: "Registrar decisión final", campos: [
    campo({ nombre: "tipo", etiqueta: "Decisión", tipo: "select", requerido: true, opciones: [["accept", `Aceptar la sugerencia (${candidatos[0]})`], ["modify", "Elegir otro régimen candidato"], ["reject", "Rechazar la recomendación"]] }),
    campo({ nombre: "regimen_final", etiqueta: "Régimen elegido (si modificas)", tipo: "select", opciones: [["", "—"], ...candidatos.map((c) => [c, c])] }),
    campo({ nombre: "motivo", etiqueta: "Motivo (obligatorio si rechazas)", tipo: "textarea" }),
  ], enviar: async (v) => {
    const res = await api(`${base(p.id)}/tratamiento/decision`, { metodo: "POST", cuerpo: v });
    if (!res.registrado) { const e = new Error(res.mensaje || res.motivo_rechazo || "No se registró la decisión."); e.mensajes = [e.message]; throw e; }
    return res;
  }, alExito: (res) => { estado.replaceChildren(mensaje("ok", "Decisión registrada", `Decisión #${res.decision_id}: ${res.tipo_decision}. Queda en la trazabilidad IA frente a médico (AUD-02).`)); } }) : null;

  return h("div", {}, estado,
    tarjeta("Opciones de tratamiento según la guía (TX-01 / TX-02)", ...cuerpoRec),
    zonaInteracciones,
    h("div", { class: "rejilla-2" },
      tarjeta("Medicación actual", listaDatos([["Conciliación", med.estado_conciliacion === "no_realizada" ? "No realizada" : med.estado_conciliacion],
        ["Medicamentos", (med.medicacion_activa || []).map((m) => (typeof m === "string" ? m : m.nombre || JSON.stringify(m))).join(", ") || "—"]]),
        med.estado_conciliacion === "no_realizada" ? h("p", { class: "ayuda" }, "Sin conciliar, una lista vacía significa «no se sabe», no «no toma nada».") : null, conciliacion),
      decision ? tarjeta("Decisión del oncólogo (TX-04)", h("p", { class: "tenue" }, "La responsabilidad clínica es tuya: el sistema registra tu decisión, no la toma."), decision) : null));
}

/* ---------------- Evidencia ---------------- */

export async function secEvidencia(ctx, p, consentimiento) {
  if (bloqueado(consentimiento)) return avisoConsentimiento(consentimiento.motivo);
  const q = ctx.consulta.get("q") || "";
  const r = await api(`${base(p.id)}/evidencia`, { consulta: { q } });
  const resultados = r.resultados.map((res) => {
    const d = res.document;
    return h("li", {}, h("strong", {}, `${d.organization} — ${d.title}`),
      h("p", { class: "tenue" }, [d.publication_date ? `Publicada: ${fecha(d.publication_date)}` : null, d.doi ? `DOI ${d.doi}` : null, `Módulo ${d.module_id}`].filter(Boolean).join(" · ")),
      (res.matched_terms || []).length ? h("p", { class: "ayuda" }, `Coincide con: ${res.matched_terms.join(", ")}`) : null,
      insignia({ texto: `Validación clínica: ${d.validation_status || "no especificada"}`, tono: "neutra", icono: "info" }));
  });
  return h("div", {},
    tarjeta("Evidencia científica (EV-01)",
      h("p", { class: "tenue" }, `Solo guías versionadas incluidas en la plataforma y habilitadas por la institución (${r.organizaciones.join(", ")}). No se inventan referencias.`),
      h("form", { class: "filtros", role: "search", onsubmit: (e) => {
        e.preventDefault();
        const v = new FormData(e.target).get("q");
        window.location.hash = `#/pacientes/${p.id}/evidencia${v ? `?q=${encodeURIComponent(v)}` : ""}`;
      } }, campo({ nombre: "q", etiqueta: "Buscar (vacío: según el expediente del paciente)", valor: q }).nodo,
        h("div", { class: "campo" }, h("button", { type: "submit", class: "btn" }, "Buscar evidencia")))),
    resultados.length ? tarjeta(q ? `Resultados para «${q}»` : "Evidencia relevante para este paciente", h("ul", { class: "lista-limpia" }, resultados))
      : mensaje("info", "Sin evidencia registrada", "No hay guías en la plataforma que coincidan. El sistema no inventa referencias externas."));
}
