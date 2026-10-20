/* Secciones de IA del expediente: preguntas (IA-01/IA-06) y agente de tratamiento (GPT), notas (IA-02/IA-03)
   y resumen para junta (IA-04). Todo borrador de IA se presenta como borrador, con quién lo redactó. */
import { h, anunciar } from "./dom.js";
import { api } from "./api.js";
import { fecha } from "./formato.js";
import { avisoConsentimiento, campo, cargando, formulario, insignia, insigniaIA, mensaje, tabla, tarjeta, textoMarkdown, vacio } from "./ui.js";

const base = (id) => `/api/clinica/pacientes/${id}`;
const bloqueado = (consentimiento) => consentimiento && !consentimiento.ia_habilitada;

function burbuja(quien, ...contenido) {
  return h("div", { class: `burbuja ${quien === "medico" ? "medico" : "asistente"}` },
    h("span", { class: "autor" }, quien === "medico" ? "Tú" : "Copiloto"), ...contenido);
}

/* ---------------- Preguntas y asistente ---------------- */

export async function secAsistente(ctx, p, consentimiento) {
  if (bloqueado(consentimiento)) return avisoConsentimiento(consentimiento.motivo);
  return h("div", { class: "rejilla-2" }, preguntas(ctx, p), agente(ctx, p));
}

const SUGERENCIAS = ["¿Cuál es el CEA más reciente?", "¿Tiene mutación de EGFR?", "¿Cuál es el HER2?", "¿Cuál es la hemoglobina?"];

function preguntas(ctx, p) {
  const chat = h("div", { class: "chat", role: "log", "aria-live": "polite", "aria-label": "Respuestas sobre el paciente" });
  const entrada = campo({ nombre: "pregunta", etiqueta: "Pregunta sobre este paciente", ayuda: "Solo se busca en su expediente; cada respuesta muestra su fuente." });

  async function preguntar(texto, aclaracion = {}) {
    chat.append(burbuja("medico", texto));
    const espera = burbuja("asistente", "Buscando en el expediente…");
    chat.append(espera);
    try {
      const r = await api(`${base(p.id)}/preguntar`, { metodo: "POST", cuerpo: { pregunta: texto, ...aclaracion } });
      const nodos = [r.answer];
      if (r.datum) nodos.push(h("span", { class: "fuente" }, `Fuente: ${r.datum.source} (${r.datum.source_id}) · ${fecha((r.datum.observed_at || "").slice(0, 10))}`));
      if (r.needs_clarification) {
        for (const amb of r.ambiguities || []) {
          if (!(amb.options || []).length && amb.kind !== "PATIENT") continue;
          const botones = amb.kind === "PATIENT"
            ? [h("button", { type: "button", class: "btn sec chico", onclick: () => preguntar(texto, { confirmar_paciente: true }) }, "Sí, sobre este paciente")]
            : amb.options.map((o) => h("button", { type: "button", class: "btn sec chico", onclick: () =>
              preguntar(texto, amb.kind === "EPISODE" ? { episodio: o } : { concepto: o }) }, o));
          nodos.push(h("div", { class: "sugerencias" }, botones));
        }
      }
      espera.replaceWith(burbuja("asistente", ...nodos));
    } catch (err) {
      espera.replaceWith(burbuja("asistente", err.campos && err.campos.consentimiento ? err.campos.consentimiento : err.mensajes[0]));
    }
    chat.scrollTop = chat.scrollHeight;
  }

  const form = h("form", { onsubmit: (e) => {
    e.preventDefault();
    const texto = entrada.control.value.trim();
    if (!texto) { entrada.marcar("Escribe una pregunta."); entrada.control.focus(); return; }
    entrada.limpiar();
    entrada.control.value = "";
    preguntar(texto);
  } }, entrada.nodo, h("div", { class: "acciones" }, h("button", { type: "submit", class: "btn" }, "Preguntar")));

  return h("section", { class: "tarjeta" },
    h("h2", {}, "Preguntas sobre el expediente", insignia({ texto: "Sin inventar datos", tono: "ia", icono: "info" })),
    h("p", { class: "tenue" }, "Responde con el dato exacto y su fuente. Si la pregunta es ambigua, te pide aclararla en vez de adivinar."),
    h("div", { class: "sugerencias" }, SUGERENCIAS.map((s) => h("button", { type: "button", class: "btn sec chico", onclick: () => preguntar(s) }, s))),
    chat, form);
}

/* Nombre legible de cada tool del agente de TX (si llega una nueva, se muestra su nombre técnico). */
const HERRAMIENTAS = {
  obtener_datos_paciente: "datos del paciente", obtener_recomendaciones_tratamiento_por_id: "recomendaciones de la guía",
  completar_datos_paciente_y_recomendar: "recomendaciones con datos del chat", obtener_recomendaciones_tratamiento_con_datos: "recomendaciones con datos del chat",
  listar_variables_requeridas: "datos que pide la guía", consultar_medicacion_actual: "medicación actual",
  chequear_interacciones_tratamiento: "interacciones", registrar_decision_tratamiento: "registro de la decisión",
  registrar_datos_clinicos_paciente: "guardar datos clínicos", registrar_conciliacion_medicamentos: "conciliación de medicamentos",
};
const nombreHerramienta = (n) => HERRAMIENTAS[n] || n;

/* Lo que se va a guardar, como tabla (dato → valor) cuando es un objeto plano; si no, el JSON tal cual. */
function argumentosLegibles(args) {
  const datos = args && typeof args.datos === "object" && !Array.isArray(args.datos) ? args.datos : null;
  const otros = args ? Object.entries(args).filter(([k]) => k !== "datos" && k !== "patient_id") : [];
  const plano = (v) => v === null || ["string", "number", "boolean"].includes(typeof v);
  if ((datos && Object.values(datos).every(plano) && otros.every(([, v]) => plano(v))) || (!datos && otros.length && otros.every(([, v]) => plano(v)))) {
    const filas = [...Object.entries(datos || {}), ...otros].map(([k, v]) => [h("code", {}, k), String(v)]);
    return tabla("Datos que se guardarán", ["Dato", "Valor"], filas, { filaEncabezado: true });
  }
  return h("pre", {}, JSON.stringify(args, null, 2));
}

function agente(ctx, p) {
  const disponible = ctx.capacidades.agente && ctx.capacidades.agente.disponible;
  const titulo = h("h2", {}, "Asistente de tratamiento", insignia(disponible ? { texto: ctx.capacidades.modelo_ia.descripcion, tono: "ia", icono: "info" }
    : { texto: "No disponible", tono: "neutra", icono: "info" }));
  if (!disponible) {
    return h("section", { class: "tarjeta" }, titulo,
      mensaje("info", null, "El asistente conversacional necesita la llave de OpenAI (OPENAI_API_KEY). Las demás funciones siguen disponibles."));
  }
  const chat = h("div", { class: "chat", role: "log", "aria-live": "polite", "aria-label": "Conversación con el asistente de tratamiento" });
  const entrada = campo({ nombre: "mensaje", etiqueta: "Mensaje para el asistente", tipo: "textarea",
    ayuda: "Consulta opciones según la guía, interacciones o pídele que registre datos. Lo que quiera guardar necesita tu aprobación." });
  let hilo = null;

  function pintarRespuesta(r) {
    hilo = r.hilo;
    if (r.texto) chat.append(burbuja("asistente", textoMarkdown(r.texto), r.herramientas && r.herramientas.length ? h("span", { class: "fuente" }, `Consultó: ${[...new Set(r.herramientas.map(nombreHerramienta))].join(" · ")}`) : null));
    for (const pend of r.pendientes || []) {
      const tarjetaAprob = h("div", { class: "aprobacion", role: "group", "aria-label": "Acción que requiere tu aprobación" },
        h("strong", {}, `El asistente quiere guardar esto en el expediente (${nombreHerramienta(pend.herramienta)}):`),
        argumentosLegibles(pend.argumentos));
      const motivo = campo({ nombre: "motivo", etiqueta: "Motivo si la rechazas (opcional)" });
      const decidir = async (aprobar) => {
        tarjetaAprob.querySelectorAll("button").forEach((b) => { b.disabled = true; });
        try {
          const res = await api(`${base(p.id)}/agente/${hilo}/decision`, { metodo: "POST", cuerpo: { aprobar, motivo: motivo.control.value.trim() } });
          tarjetaAprob.replaceWith(mensaje(aprobar ? "ok" : "info", null, aprobar ? "Aprobaste la acción." : "Rechazaste la acción; no se guardó nada."));
          pintarRespuesta(res);
        } catch (err) {
          tarjetaAprob.append(mensaje("error", null, err.mensajes[0]));
          tarjetaAprob.querySelectorAll("button").forEach((b) => { b.disabled = false; });
        }
      };
      tarjetaAprob.append(motivo.nodo, h("div", { class: "acciones" },
        h("button", { type: "button", class: "btn", onclick: () => decidir(true) }, "Aprobar y guardar"),
        h("button", { type: "button", class: "btn peligro", onclick: () => decidir(false) }, "Rechazar")));
      chat.append(tarjetaAprob);
      anunciar("El asistente necesita tu aprobación para guardar.");
    }
    chat.scrollTop = chat.scrollHeight;
  }

  const form = h("form", { onsubmit: async (e) => {
    e.preventDefault();
    const texto = entrada.control.value.trim();
    if (!texto) { entrada.marcar("Escribe un mensaje."); entrada.control.focus(); return; }
    entrada.limpiar();
    entrada.control.value = "";
    chat.append(burbuja("medico", texto));
    const espera = burbuja("asistente", "Pensando… (el modelo consulta la guía y el expediente)");
    chat.append(espera);
    try {
      const r = await api(`${base(p.id)}/agente`, { metodo: "POST", cuerpo: { mensaje: texto, hilo } });
      espera.remove();
      pintarRespuesta(r);
    } catch (err) {
      espera.replaceWith(burbuja("asistente", err.mensajes[0]));
    }
  } }, entrada.nodo, h("div", { class: "acciones" }, h("button", { type: "submit", class: "btn" }, "Enviar")));

  return h("section", { class: "tarjeta ia" }, titulo,
    h("p", { class: "tenue" }, "Conversa con un modelo de lenguaje que usa las mismas herramientas del sistema (guías, interacciones, datos). Solo ve a este paciente."),
    h("div", { class: "sugerencias" }, ["¿Qué opciones de primera línea tiene según la guía?", "¿Qué dato clínico falta para recomendar?", "¿Qué biomarcadores clave tiene?"]
      .map((s) => h("button", { type: "button", class: "btn sec chico", onclick: () => { entrada.control.value = s; entrada.control.focus(); } }, s))),
    chat, form);
}

/* ---------------- Notas de consulta (IA-02 / IA-03) ---------------- */

export async function secNotas(ctx, p, consentimiento) {
  const [consultas, notas] = await Promise.all([api(`${base(p.id)}/consultas-expediente`), api(`${base(p.id)}/notas`)]);
  const estado = h("div", { role: "status", "aria-live": "polite" });
  const zonaNotas = h("div", {});
  const ia = !bloqueado(consentimiento);

  function pintarNota(nota, uso) {
    const secciones = Object.entries(nota.contenido_actual);
    return h("section", { class: `tarjeta ${nota.oficial ? "" : "ia"}` },
      h("h2", {}, nota.oficial ? "Nota clínica oficial" : "Borrador de nota (IA)",
        nota.oficial ? insignia({ texto: "Aprobada", tono: "ok", icono: "ok" }) : insignia({ texto: "Borrador: requiere tu revisión", tono: "aviso", icono: "alerta" }),
        insigniaIA(uso)),
      h("p", { class: "tenue" }, `Creada ${fecha((nota.creado_en || "").slice(0, 10))}`, nota.aprobacion ? ` · aprobada por ${nota.aprobacion.aprobado_por}` : "",
        nota.historial_ediciones.length ? ` · ${nota.historial_ediciones.length} edición(es)` : ""),
      secciones.map(([clave, texto]) => {
        const editor = campo({ nombre: `sec-${clave}`, etiqueta: clave, tipo: "textarea", valor: texto });
        if (nota.oficial) return h("div", { class: "campo" }, h("h3", {}, clave), h("pre", { class: "texto" }, texto));
        return h("div", {}, editor.nodo, h("div", { class: "acciones" }, h("button", { type: "button", class: "btn sec chico", onclick: async () => {
          try {
            const r = await api(`${base(p.id)}/notas/${nota.nota_id}/secciones/${encodeURIComponent(clave)}`, { metodo: "PUT", cuerpo: { contenido: editor.control.value } });
            estado.replaceChildren(mensaje("ok", null, `Sección ${clave} guardada (queda en el historial de ediciones).`));
            Object.assign(nota, r);
          } catch (err) { estado.replaceChildren(mensaje("error", `No se pudo guardar ${clave}`, err.mensajes[0])); }
        } }, `Guardar ${clave}`)));
      }),
      nota.oficial ? null : h("div", { class: "acciones" }, h("button", { type: "button", class: "btn", onclick: async () => {
        try {
          const r = await api(`${base(p.id)}/notas/${nota.nota_id}/aprobar`, { metodo: "POST", cuerpo: {} });
          estado.replaceChildren(mensaje("ok", "Nota aprobada", "Ahora es la nota clínica oficial y ya no se puede editar."));
          zonaNotas.prepend(pintarNota(r));
        } catch (err) { estado.replaceChildren(mensaje("error", "No se pudo aprobar", err.mensajes[0])); }
      } }, "Aprobar como nota oficial")));
  }

  const opciones = consultas.map((c) => [c.id, `${fecha(c.fecha)} — ${c.motivo}`]);
  const selector = campo({ nombre: "consulta_id", etiqueta: "Consulta a documentar", tipo: "select", opciones: opciones.length ? opciones : [["", "No hay consultas registradas"]] });
  const formato = campo({ nombre: "formato", etiqueta: "Formato", tipo: "select", opciones: [["SOAP", "SOAP (subjetivo, objetivo, análisis y plan)"]] });

  const generar = ia && consultas.length ? formulario({ campos: [selector, formato], textoBoton: "Generar borrador con IA",
    enviar: (v) => { estado.replaceChildren(cargando("Redactando el borrador (máximo 10 s)…")); return api(`${base(p.id)}/notas`, { metodo: "POST", cuerpo: v }); },
    alExito: (r) => {
      estado.replaceChildren(mensaje("ia", "Borrador generado", r.uso_modelo.descripcion, ". Revisa cada sección: nada es oficial hasta que lo apruebes."));
      zonaNotas.prepend(pintarNota(r.nota, r.uso_modelo));
    } }) : null;

  const nuevaConsulta = ctx.sesion.puede_registrar ? h("details", { class: "tarjeta", open: !consultas.length },
    h("summary", {}, "Registrar la consulta de hoy"),
    formulario({ campos: [
      campo({ nombre: "motivo", etiqueta: "Motivo", requerido: true, valor: "Control" }),
      campo({ nombre: "notas", etiqueta: "Lo que pasó en la consulta", tipo: "textarea", requerido: true,
        ayuda: "Síntomas, examen, impresión y plan, en tus palabras. Es lo único que el borrador puede usar." }),
    ], textoBoton: "Guardar consulta", enviar: (v) => api(`${base(p.id)}/consultas-expediente`, { metodo: "POST", cuerpo: v }),
    alExito: () => window.dispatchEvent(new HashChangeEvent("hashchange")) })) : null;

  zonaNotas.replaceChildren(...(notas.length ? notas.map((n) => pintarNota(n)) : [vacio("Todavía no hay notas generadas para este paciente.")]));
  return h("div", {},
    !ia ? avisoConsentimiento(consentimiento.motivo) : null,
    tarjeta("Borrador de nota con IA",
      h("p", { class: "tenue" }, "El borrador se arma solo con lo registrado en la consulta y cita su fuente. Si el modelo no responde en 8 s, lo redacta el asistente de reglas."),
      generar || vacio(ia ? "Registra primero una consulta." : "Sin consentimiento de IA no se generan borradores.")),
    nuevaConsulta, estado, zonaNotas);
}

/* ---------------- Resumen para junta (IA-04) ---------------- */

export async function secJunta(ctx, p, consentimiento) {
  if (bloqueado(consentimiento)) return avisoConsentimiento(consentimiento.motivo);
  const zona = h("div", {});
  const boton = h("button", { type: "button", class: "btn", onclick: async () => {
    boton.disabled = true;
    zona.replaceChildren(cargando("Preparando el resumen del caso (máximo 10 s)…"));
    try {
      const r = await api(`${base(p.id)}/resumen-junta`, { metodo: "POST", cuerpo: {} });
      const res = r.resumen;
      zona.replaceChildren(h("section", { class: "tarjeta ia" },
        h("h2", {}, "Resumen del caso", insigniaIA(r.uso_modelo)),
        mensaje("aviso", null, res.disclaimer),
        res.sections.map((s) => h("div", { class: "campo" }, h("h3", {}, s.label),
          s.status === "missing" ? h("p", { class: "tenue" }, s.content || "Sin información suficiente en el expediente.") : h("pre", { class: "texto" }, s.content),
          s.source_span_ids && s.source_span_ids.length ? h("p", { class: "ayuda" }, `Fuentes: ${s.source_span_ids.join(", ")}`) : null)),
        (res.warnings || []).map((w) => mensaje("aviso", null, w))));
      anunciar("Resumen listo.");
    } catch (err) {
      zona.replaceChildren(err.campos && err.campos.consentimiento ? avisoConsentimiento(err.campos.consentimiento) : mensaje("error", "No se pudo preparar el resumen", err.mensajes[0]));
    } finally { boton.disabled = false; }
  } }, "Preparar resumen para junta médica");
  return h("div", {}, tarjeta("Resumen para junta médica o interconsulta",
    h("p", { class: "tenue" }, "Diagnóstico y estadio salen del registro estructurado; tratamientos previos y estado actual los redacta la IA citando cada fuente. Lo que falta queda marcado, nunca inventado."),
    h("div", { class: "acciones" }, boton)), zona);
}
