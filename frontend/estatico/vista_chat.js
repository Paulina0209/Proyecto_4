/* El asistente: la forma principal de trabajar. Conversaciones a la izquierda, el chat al centro y la historia
   clínica del paciente a la derecha. Mientras el asistente trabaja se ve cada paso (entender, buscar, evaluar,
   redactar); al responder, los registros que usó se resaltan en la historia clínica. */
import { h, anunciar, idUnico, reemplazar } from "./dom.js";
import { api, apiFlujo } from "./api.js";
import { edad, fecha } from "./formato.js";
import { cargando, insignia, mensaje, vacio } from "./ui.js";
import { leerComoBase64 } from "./secciones_paciente.js";

const SECCIONES_HC = [["ficha", "Ficha"], ["consultas", "Consultas"], ["laboratorios", "Laboratorios"], ["imagenes", "Imágenes"],
  ["biomarcadores", "Biomarcadores"], ["antecedentes", "Antecedentes"], ["datos", "Datos clínicos"], ["ordenes", "Órdenes médicas"], ["documentos", "Documentos"],
  ["guias", "Guías clínicas"]];
const SUGERENCIAS = ["Resúmeme el caso", "¿Cuál es el EGFR?", "¿Qué diagnóstico diferencial sugieres?", "¿En qué estadio está?",
  "¿Qué opciones de tratamiento tiene?", "¿Qué falta para decidir?"];
const SUGERENCIAS_ENFERMERIA = ["¿Qué medicamentos tiene ordenados?", "¿Qué le toca hoy y a qué hora?", "¿Cuándo es la próxima dosis?",
  "¿Por qué vía se administra?", "¿Cuál es el último potasio?"];
const FORMATOS_ADJUNTO = ".pdf,.jpg,.jpeg,.png,.dcm";
const ESTADO_RESPUESTA = {
  rechazada: { texto: "Sin sustento: no respondo", tono: "aviso", icono: "alerta" },
  aclaracion: { texto: "Necesito una aclaración", tono: "info", icono: "info" },
  fuera_de_rol: { texto: "Consulta para el oncólogo tratante", tono: "info", icono: "info" },
};

/* Texto del asistente: líneas, **negrita**, viñetas y citas [id] como botones que resaltan la fuente en la HC. */
function textoConCitas(texto, alCitar) {
  return h("div", { class: "respuesta" }, String(texto || "").split("\n").map((linea) => {
    const vineta = /^\s*[-•]\s+/.test(linea);
    const partes = [];
    linea.replace(/^\s*[-•]\s+/, "").split(/(\[[a-z]+(?:-[\w.]+)+\]|\*\*[^*]+\*\*)/i).forEach((trozo) => {
      if (!trozo) return;
      const cita = /^\[([a-z]+(?:-[\w.]+)+)\]$/i.exec(trozo);
      if (cita) partes.push(h("button", { type: "button", class: "cita", "aria-label": `Ver la fuente ${cita[1]} en la historia clínica`, onclick: () => alCitar([cita[1]]) }, cita[1]));
      else if (/^\*\*[^*]+\*\*$/.test(trozo)) partes.push(h("strong", {}, trozo.slice(2, -2)));
      else partes.push(trozo);
    });
    return partes.length ? h(vineta ? "li" : "p", {}, partes) : null;
  }));
}

export async function vistaChat(ctx) {
  const { conversacion: idConversacion } = ctx.parametros;
  const pacienteInicial = Number(ctx.consulta.get("paciente")) || null;
  const estado = { conversacion: idConversacion || null, paciente: null, hc: null, ocupado: false };

  /* ---------------- Historia clínica (panel derecho) ---------------- */
  const panel = h("aside", { class: "panel-hc", "aria-label": "Historia clínica del paciente" });
  const marcados = new Set();

  function resaltar(ids, { desplazar = true } = {}) {
    panel.querySelectorAll(".resaltado").forEach((n) => n.classList.remove("resaltado"));
    marcados.clear();
    let primero = null;
    for (const id of ids) {
      const nodo = panel.querySelector(`[data-fuente="${CSS.escape(id)}"]`);
      if (!nodo) continue;
      nodo.classList.add("resaltado");
      marcados.add(id);
      const seccion = nodo.closest("details");
      if (seccion) seccion.open = true;
      primero = primero || nodo;
    }
    if (primero && desplazar) {
      // Solo se desplaza el panel (scrollIntoView movería toda la página y el chat se saldría de la vista).
      if (panel.scrollHeight > panel.clientHeight) {
        const arriba = primero.getBoundingClientRect().top - panel.getBoundingClientRect().top + panel.scrollTop;
        panel.scrollTo({ top: Math.max(0, arriba - panel.clientHeight / 3), behavior: "smooth" });
      } else primero.scrollIntoView({ block: "center", behavior: "smooth" });
      primero.focus({ preventScroll: true });
    }
    anunciar(marcados.size ? `${marcados.size} ${marcados.size === 1 ? "fuente resaltada" : "fuentes resaltadas"} en la historia clínica.` : "Esa fuente no está en la historia clínica abierta.");
  }

  function pintarPanel(extra = []) {
    if (!estado.paciente) {
      panel.replaceChildren(h("h2", {}, "Historia clínica"), vacio("Elige un paciente arriba o nómbralo en tu pregunta (por ejemplo «¿cuál es el CEA de P-0008538?»). Su historia clínica se abre aquí."));
      return;
    }
    if (!estado.hc) { panel.replaceChildren(h("h2", {}, estado.paciente.nombre), cargando("Abriendo la historia clínica…")); return; }
    const p = estado.hc.paciente, secciones = { ...estado.hc.secciones };
    // Fuentes que no son del expediente (guías, documentos): se agregan al panel para poder resaltarlas.
    for (const f of extra) {
      const clave = f.seccion === "guias" ? "guias" : f.seccion === "documentos" ? "documentos" : null;
      if (clave && !(secciones[clave] || []).some((x) => x.id === f.id)) secciones[clave] = [...(secciones[clave] || []), { id: f.id, texto: f.texto, fecha: f.fecha, grupo: f.titulo }];
    }
    const c = estado.hc.consentimiento;
    const a = edad(p.fecha_nacimiento);
    panel.replaceChildren(...[
      h("div", { class: "panel-cabecera" },
        h("h2", {}, p.nombre),
        h("p", { class: "tenue" }, [a === null ? null : `${a} años`, p.identificacion].filter(Boolean).join(" · ")),
        c ? insignia(c.ia_habilitada ? { texto: "IA habilitada", tono: "ok", icono: "ok" } : { texto: `IA bloqueada: consentimiento ${c.etiqueta}`, tono: "crit", icono: "alerta" }) : null,
        h("p", {}, h("a", { href: `#/pacientes/${p.id}` }, "Abrir el expediente completo"))),
      !p.expediente_id ? vacio("Este paciente todavía no tiene expediente clínico.") : null,
      ...SECCIONES_HC.filter(([clave]) => (secciones[clave] || []).length).map(([clave, titulo]) => {
        const items = secciones[clave];
        let grupoActual = null;
        const lista = h("ul", { class: "lista-hc" });
        for (const it of items) {
          if (it.grupo && it.grupo !== grupoActual) { grupoActual = it.grupo; lista.append(h("li", { class: "grupo-hc" }, it.grupo)); }
          lista.append(h("li", { "data-fuente": it.id, tabindex: "-1", class: marcados.has(it.id) ? "resaltado" : null },
            it.fecha && clave !== "consultas" ? h("span", { class: "fecha-hc" }, fecha(String(it.fecha).slice(0, 10))) : null,
            h("span", {}, it.texto), h("span", { class: "id-hc" }, it.id)));
        }
        return h("details", { class: "seccion-hc", open: clave === "ficha" || items.some((x) => marcados.has(x.id)) },
          h("summary", {}, `${titulo} (${items.length})`), lista);
      })].filter(Boolean));   // replaceChildren (a diferencia de h) escribiría "null"
  }

  async function abrirPaciente(id) {
    if (!id) return;
    if (estado.paciente && estado.paciente.id === id && estado.hc) return;
    estado.paciente = { id, nombre: "Paciente" };
    estado.hc = null;
    pintarPanel();
    try {
      estado.hc = await api(`/api/chat/pacientes/${id}/hc`);
      estado.paciente = { id, nombre: estado.hc.paciente.nombre };
      selectorPaciente.value = estado.hc.paciente.nombre;
      etiquetaActivo.replaceChildren("Paciente activo: ", h("strong", {}, estado.hc.paciente.nombre));
    } catch (err) {
      estado.paciente = null;
      panel.replaceChildren(mensaje("error", "No se pudo abrir la historia clínica", err.mensajes[0]));
      return;
    }
    pintarPanel();
  }

  /* ---------------- Conversaciones (izquierda) ---------------- */
  const listaConversaciones = h("nav", { class: "conversaciones", "aria-label": "Tus conversaciones" });
  async function cargarConversaciones() {
    try {
      const lista = await api("/api/chat/conversaciones");
      listaConversaciones.replaceChildren(
        h("a", { class: "btn chico", href: "#/asistente" }, "Nueva conversación"),
        lista.length ? h("ul", {}, lista.map((c) => h("li", {}, h("a", { href: `#/asistente/${c.id}`, "aria-current": c.id === estado.conversacion ? "page" : null },
          h("span", {}, c.titulo), h("small", {}, `${fecha(c.actualizada.slice(0, 10))} · ${c.mensajes} mensajes`)))))
          : h("p", { class: "tenue" }, "Aún no tienes conversaciones."));
    } catch (err) { listaConversaciones.replaceChildren(mensaje("error", null, err.mensajes[0])); }
  }

  /* ---------------- Chat (centro) ---------------- */
  const hilo = h("div", { class: "chat chat-principal", role: "log", "aria-live": "polite", "aria-label": "Conversación con el copiloto" });
  const etiquetaActivo = h("p", { class: "tenue", role: "status" }, "Sin paciente activo");
  const selectorPaciente = h("input", { type: "search", id: idUnico("buscar-paciente"), placeholder: "Buscar paciente por nombre o documento", autocomplete: "off", "aria-label": "Buscar paciente" });
  const resultadosPaciente = h("ul", { class: "resultados-paciente", hidden: true });
  let temporizador = null;
  selectorPaciente.addEventListener("input", () => {
    window.clearTimeout(temporizador);
    const texto = selectorPaciente.value.trim();
    if (texto.length < 2) { resultadosPaciente.hidden = true; return; }
    temporizador = window.setTimeout(async () => {
      try {
        const r = await api("/api/pacientes/buscar", { consulta: { nombre: texto, tamano_pagina: 6 } });
        resultadosPaciente.replaceChildren(...r.items.map((p) => h("li", {}, h("button", { type: "button", class: "btn sec chico", onclick: () => {
          resultadosPaciente.hidden = true; abrirPaciente(p.id);
        } }, p.nombre_completo, p.diagnosticos && p.diagnosticos.length ? h("small", {}, ` · ${p.diagnosticos[0]}`) : null))));
        resultadosPaciente.hidden = !r.items.length;
      } catch (e) { resultadosPaciente.hidden = true; }
    }, 300);
  });

  function burbujaMedico(texto) { return h("div", { class: "burbuja medico" }, h("span", { class: "autor" }, "Tú"), texto); }

  function pintarRespuesta(contenedor, r, pasos) {
    const fuentes = r.fuentes || [];
    const alCitar = (ids) => resaltar(ids);
    reemplazar(contenedor,
      h("span", { class: "autor" }, "Copiloto", r.modelo ? h("small", {}, ` · ${r.modelo}`) : null),
      ESTADO_RESPUESTA[r.estado] ? insignia(ESTADO_RESPUESTA[r.estado]) : null,
      textoConCitas(r.respuesta, alCitar),
      (r.opciones || []).length ? h("div", { class: "sugerencias" }, r.opciones.map((o) => o.paciente_id
        ? h("button", { type: "button", class: "btn sec chico", onclick: async () => { await abrirPaciente(o.paciente_id); enviar(r.pregunta || ultimaPregunta); } }, `${o.nombre} (${o.identificacion})`)
        : h("button", { type: "button", class: "btn sec chico", onclick: () => enviar(`${ultimaPregunta} (${o.texto})`) }, o.texto))) : null,
      fuentes.length ? h("div", { class: "fuentes" }, h("strong", {}, "Fuentes: "),
        fuentes.map((f) => h("button", { type: "button", class: "cita", onclick: () => resaltar([f.id]),
          "aria-label": `Ver en la historia clínica: ${f.id}` }, f.id, f.similitud !== null && f.similitud !== undefined ? h("small", {}, ` ${Math.round(f.similitud * 100)}%`) : null)),
        h("button", { type: "button", class: "btn sec chico", onclick: () => resaltar(fuentes.map((f) => f.id)) }, "Resaltar todas")) : null,
      pasos.length ? h("details", { class: "pasos" }, h("summary", {}, `Cómo lo resolví (${pasos.length} pasos)`),
        h("ol", {}, pasos.map((p) => h("li", {}, h("strong", {}, p.titulo), p.detalle ? ` — ${p.detalle}` : "")))) : null);
  }

  let ultimaPregunta = "";
  async function enviar(texto) {
    texto = String(texto || "").trim();
    if (!texto || estado.ocupado) return;
    estado.ocupado = true;
    ultimaPregunta = texto;
    const bienvenida = hilo.querySelector(".bienvenida");
    if (bienvenida) bienvenida.remove();
    botonEnviar.disabled = true;
    hilo.append(burbujaMedico(texto));
    const progreso = h("ol", { class: "progreso" });
    const respuesta = h("div", { class: "burbuja asistente", "aria-busy": "true" }, h("span", { class: "autor" }, "Copiloto"), h("p", { class: "tenue" }, "Trabajando…"), progreso);
    hilo.append(respuesta);
    hilo.scrollTop = hilo.scrollHeight;
    const pasos = [];
    try {
      await apiFlujo("/api/chat/mensajes", { mensaje: texto, conversacion_id: estado.conversacion, paciente_id: estado.paciente ? estado.paciente.id : null }, async (ev) => {
        if (ev.tipo === "conversacion" && !estado.conversacion) {
          estado.conversacion = ev.conversacion_id;
          window.history.replaceState(null, "", `#/asistente/${ev.conversacion_id}`);
        } else if (ev.tipo === "paso") {
          pasos.push(ev);
          progreso.append(h("li", {}, h("strong", {}, ev.titulo), ev.detalle ? ` — ${ev.detalle}` : ""));
          if (ev.paciente && ev.paciente.id && (!estado.paciente || estado.paciente.id !== ev.paciente.id)) abrirPaciente(ev.paciente.id);
          if (ev.fuentes && ev.fuentes.length && estado.hc) resaltar(ev.fuentes.slice(0, 6), { desplazar: false });
          hilo.scrollTop = hilo.scrollHeight;
        } else if (ev.tipo === "final") {
          if (ev.paciente && ev.paciente.id) await abrirPaciente(ev.paciente.id);
          pintarRespuesta(respuesta, ev, pasos);
          pintarPanel(ev.fuentes || []);
          if ((ev.fuentes || []).length) resaltar(ev.fuentes.map((f) => f.id));
          anunciar(ev.estado === "rechazada" ? "El copiloto no encontró sustento para responder." : "Respuesta lista.");
        } else if (ev.tipo === "error") {
          respuesta.replaceChildren(mensaje("error", "El copiloto no pudo responder", ev.mensaje));
        }
      });
    } catch (err) {
      respuesta.replaceChildren(mensaje("error", "El copiloto no pudo responder", err.mensajes ? err.mensajes[0] : String(err)));
    } finally {
      respuesta.removeAttribute("aria-busy");
      estado.ocupado = false;
      botonEnviar.disabled = false;
      hilo.scrollTop = hilo.scrollHeight;
      cargarConversaciones();
    }
  }

  const enfermeria = Boolean(ctx.sesion.solo_lectura);
  const entrada = h("textarea", { id: idUnico("pregunta"), rows: 2, placeholder: enfermeria
    ? "Pregunta por las órdenes médicas de un paciente: medicamentos, dosis, vías y horarios…"
    : "Pregunta sobre un paciente, pide un resumen, un diagnóstico diferencial, la estadificación o las opciones de tratamiento…" });
  entrada.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); formulario.requestSubmit(); } });
  const botonEnviar = h("button", { type: "submit", class: "btn" }, "Enviar");
  /* Adjuntar un documento al expediente del paciente activo (DOC-01): queda cifrado y, con consentimiento de IA,
     entra a la base de conocimiento del asistente, así que se le puede preguntar enseguida. */
  const archivo = h("input", { type: "file", id: idUnico("adjunto"), accept: FORMATOS_ADJUNTO, class: "vh", tabindex: "-1" });
  const botonAdjuntar = ctx.sesion.puede_registrar ? h("button", { type: "button", class: "btn sec", title: "PDF, imagen o DICOM, hasta 15 MB",
    onclick: () => {
      if (!estado.paciente) {
        hilo.append(h("div", { class: "burbuja asistente" }, mensaje("info", null, "Primero abre al paciente (arriba) para adjuntarle el documento.")));
        hilo.scrollTop = hilo.scrollHeight;
        return;
      }
      archivo.click();
    } }, "Adjuntar documento") : null;
  archivo.addEventListener("change", async () => {
    const f = archivo.files && archivo.files[0];
    archivo.value = "";
    if (!f || !estado.paciente) return;
    const bienvenida = hilo.querySelector(".bienvenida");
    if (bienvenida) bienvenida.remove();
    hilo.append(burbujaMedico(`Adjunté «${f.name}» al expediente de ${estado.paciente.nombre}.`));
    const aviso = h("div", { class: "burbuja asistente", "aria-busy": "true" }, h("span", { class: "autor" }, "Copiloto"), h("p", { class: "tenue" }, "Guardando el documento…"));
    hilo.append(aviso);
    hilo.scrollTop = hilo.scrollHeight;
    try {
      if (f.size > 15 * 1024 * 1024) throw Object.assign(new Error("El archivo supera los 15 MB."), { mensajes: ["El archivo supera los 15 MB."] });
      const d = await api(`/api/clinica/pacientes/${estado.paciente.id}/documentos`, { metodo: "POST",
        cuerpo: { nombre: f.name, contenido_base64: await leerComoBase64(f) } });
      const p = d.procesamiento || {};
      aviso.replaceChildren(h("span", { class: "autor" }, "Copiloto"),
        mensaje(p.indexado ? "ok" : "info", "Documento guardado en el expediente", `${d.nombre_archivo_original} (${d.tipo_documento}). ${p.mensaje || ""}`),
        p.indexado ? h("p", { class: "tenue" }, "Ya puedes preguntarme por su contenido.") : null);
      anunciar("Documento guardado.");
      const id = estado.paciente.id;
      estado.hc = null;
      await abrirPaciente(id);
    } catch (err) {
      aviso.replaceChildren(mensaje("error", "No se pudo adjuntar el documento", err.mensajes ? err.mensajes[0] : String(err)));
    } finally {
      aviso.removeAttribute("aria-busy");
      hilo.scrollTop = hilo.scrollHeight;
    }
  });
  const formulario = h("form", { class: "entrada-chat", onsubmit: (e) => { e.preventDefault(); const t = entrada.value; entrada.value = ""; enviar(t); } },
    h("label", { for: entrada.id, class: "vh" }, "Tu pregunta"), archivo, botonAdjuntar, entrada, botonEnviar);

  async function cargarConversacion() {
    if (!estado.conversacion) {
      hilo.replaceChildren(h("div", { class: "bienvenida" },
        h("h2", {}, `Hola, ${ctx.sesion.usuario.nombre_completo.split(" ").slice(0, 2).join(" ")}`),
        h("p", {}, enfermeria
          ? "Pregúntame por las órdenes médicas de tus pacientes: qué medicamento, qué dosis, por qué vía y a qué hora. Respondo solo con lo que ordenó el oncólogo y te muestro la orden."
          : "Pregúntame por tus pacientes. Respondo solo con lo que hay en sus historias clínicas y en las guías de la institución, y te muestro de dónde sale cada dato."),
        h("div", { class: "sugerencias" }, (enfermeria ? SUGERENCIAS_ENFERMERIA : SUGERENCIAS).map((s) => h("button", { type: "button", class: "btn sec chico", onclick: () => enviar(s) }, s)))));
      return;
    }
    hilo.replaceChildren(cargando("Cargando la conversación…"));
    try {
      const mensajes = await api(`/api/chat/conversaciones/${estado.conversacion}`);
      hilo.replaceChildren();
      let ultimoPaciente = null;
      for (const m of mensajes) {
        if (m.rol === "medico") { hilo.append(burbujaMedico(m.texto)); ultimaPregunta = m.texto; continue; }
        const b = h("div", { class: "burbuja asistente" });
        pintarRespuesta(b, { respuesta: m.texto, estado: m.estado, fuentes: m.fuentes, modelo: m.modelo }, m.pasos || []);
        hilo.append(b);
        if (m.paciente_id) ultimoPaciente = m.paciente_id;
      }
      if (ultimoPaciente && !pacienteInicial) await abrirPaciente(ultimoPaciente);
      hilo.scrollTop = hilo.scrollHeight;
    } catch (err) { hilo.replaceChildren(mensaje("error", "No se pudo cargar la conversación", err.mensajes[0])); }
  }

  const nodo = h("div", { class: "chat-app" },
    listaConversaciones,
    h("section", { class: "chat-centro", "aria-label": "Chat" },
      h("div", { class: "chat-cabecera" },
        h("div", {}, h("h1", {}, "Asistente clínico"), etiquetaActivo),
        h("div", { class: "buscador-paciente" }, selectorPaciente, resultadosPaciente)),
      hilo,
      h("p", { class: "ayuda" }, enfermeria ? "Enter envía; Mayús+Enter, nueva línea. Las órdenes las prescribe y cambia el oncólogo tratante."
        : "Enter envía; Mayús+Enter, nueva línea. Es apoyo a la decisión: las decisiones clínicas son tuyas."),
      formulario),
    panel);
  pintarPanel();
  return { titulo: "Asistente clínico", nodo, foco: entrada, alMostrar: async () => {
    await Promise.all([cargarConversaciones(), cargarConversacion(), pacienteInicial ? abrirPaciente(pacienteInicial) : Promise.resolve()]);
  } };
}
