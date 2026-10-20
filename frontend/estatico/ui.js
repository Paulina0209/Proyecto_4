/* Piezas visuales compartidas. */
import { h, idUnico, anunciar } from "./dom.js";
import { icono } from "./iconos.js";

export function insignia(def) {
  return h("span", { class: `insignia ${def.tono}` }, icono(def.icono), def.texto);
}

/* tipo: error | aviso | info | ok | ia. Los errores se anuncian al instante (role=alert); el resto, con cortesía (role=status). */
export function mensaje(tipo, titulo, ...cuerpo) {
  return h("div", { class: `mensaje ${tipo}`, role: tipo === "error" ? "alert" : "status" },
    titulo ? h("strong", { class: "titulo" }, titulo) : null, ...cuerpo);
}

export function cargando(texto = "Cargando…") {
  return h("p", { class: "cargando", role: "status" }, texto);
}

export function vacio(texto) {
  return h("p", { class: "vacio" }, texto);
}

export function tarjeta(titulo, ...cuerpo) {
  return h("section", { class: "tarjeta" }, titulo ? h("h2", {}, titulo) : null, ...cuerpo);
}

/* Error de carga con la posibilidad de reintentar. Si falta el consentimiento de IA (SEC-03), lo explica. */
export function errorConReintento(err, reintentar) {
  if (err && err.estado === 409 && err.campos && err.campos.consentimiento) return avisoConsentimiento(err.campos.consentimiento);
  return h("div", {},
    mensaje("error", "No se pudo cargar esta información", err.mensajes && err.mensajes.length ? err.mensajes[0] : String(err)),
    reintentar ? h("button", { type: "button", class: "btn sec", onclick: reintentar }, "Reintentar") : null);
}

export function avisoConsentimiento(texto) {
  return mensaje("aviso", "Las funciones de IA no están habilitadas para este paciente",
    texto || "Falta el consentimiento informado (SEC-03).", " ",
    h("span", {}, "Regístralo en la sección "), h("strong", {}, "Consentimiento y privacidad"), ".");
}

/* Insignia que dice quién redactó un texto: el modelo (GPT) o el asistente de reglas (NFR-01). */
export function insigniaIA(uso) {
  if (!uso || !uso.proveedor) return null;
  return uso.proveedor === "modelo"
    ? insignia({ texto: uso.descripcion, tono: "ia", icono: "info" })
    : insignia({ texto: uso.descripcion, tono: "aviso", icono: "alerta" });
}

/* Tabla con título (caption) y región desplazable que se puede usar con el teclado. */
export function tabla(titulo, columnas, filas, { numericas = [], filaEncabezado = false } = {}) {
  const idTitulo = idUnico("t");
  return h("div", { class: "tabla-region", role: "region", tabindex: "0", "aria-labelledby": idTitulo },
    h("table", {},
      h("caption", { id: idTitulo }, titulo),
      h("thead", {}, h("tr", {}, columnas.map((c, i) => h("th", { scope: "col", class: numericas.includes(i) ? "num" : null }, c)))),
      h("tbody", {}, filas.map((fila) => h("tr", {}, fila.map((celda, i) =>
        i === 0 && filaEncabezado
          ? h("th", { scope: "row" }, celda)
          : h("td", { class: numericas.includes(i) ? "num" : null }, celda)))))));
}

/* Markdown sencillo de las respuestas del modelo: títulos, párrafos, viñetas, listas numeradas, tablas, **negrita**,
   *cursiva* y `código`. Construye nodos (nunca innerHTML): lo que escriba el modelo no puede inyectar HTML. */
function enLinea(texto) {
  return String(texto).split(/(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/).filter(Boolean).map((t) =>
    /^\*\*[^*]+\*\*$/.test(t) ? h("strong", {}, enLinea(t.slice(2, -2)))
      : /^`[^`]+`$/.test(t) ? h("code", {}, t.slice(1, -1))
        : /^\*[^*\s][^*]*\*$/.test(t) ? h("em", {}, t.slice(1, -1)) : t);
}

const celdas = (linea) => linea.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());

export function textoMarkdown(texto, { nivelTitulo = 3 } = {}) {
  const lineas = String(texto || "").replace(/\r\n?/g, "\n").split("\n");
  // El título más alto del texto toma «nivelTitulo» (el modelo empieza a veces en ## o ###).
  const minimo = Math.min(6, ...lineas.map((l) => (/^\s*(#{1,6})\s/.exec(l) || [, "######"])[1].length));
  const bloques = [];
  let lista = null;
  const cerrarLista = () => { lista = null; };
  for (let i = 0; i < lineas.length; i++) {
    const linea = lineas[i];
    if (!linea.trim()) { cerrarLista(); continue; }
    const titulo = /^\s*(#{1,6})\s+(.*)$/.exec(linea);
    if (titulo) {
      cerrarLista();
      bloques.push(h(`h${Math.min(6, nivelTitulo + titulo[1].length - minimo)}`, { class: "md-titulo" }, enLinea(titulo[2].replace(/\s*#+\s*$/, ""))));
      continue;
    }
    if (/^\s*\|/.test(linea) && i + 1 < lineas.length && /^\s*\|?\s*:?-{2,}/.test(lineas[i + 1])) {
      cerrarLista();
      const columnas = celdas(linea);
      const filas = [];
      for (i += 2; i < lineas.length && /^\s*\|/.test(lineas[i]); i++) filas.push(celdas(lineas[i]).map(enLinea));
      i--;
      bloques.push(tabla("Tabla de la respuesta", columnas.map(enLinea), filas));
      continue;
    }
    const item = /^(\s*)([-*•]|\d+[.)])\s+(.*)$/.exec(linea);
    if (item) {
      const tipo = /\d/.test(item[2]) ? "ol" : "ul";
      if (!lista || lista.tipo !== tipo) { lista = { tipo, nodo: h(tipo, { class: "md-lista" }) }; bloques.push(lista.nodo); }
      lista.nodo.append(h("li", {}, enLinea(item[3])));
      continue;
    }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(linea)) { cerrarLista(); bloques.push(h("hr", {})); continue; }
    cerrarLista();
    bloques.push(h("p", {}, enLinea(linea.trim())));
  }
  return h("div", { class: "md" }, bloques);
}

export function listaDatos(pares) {
  return h("dl", { class: "dato" }, pares.flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v === null || v === undefined || v === "" ? "—" : v)]));
}

/* ---------------- Formularios ---------------- */

/* Un campo con etiqueta, ayuda opcional y su mensaje de error (aria-describedby). tipo: text|date|number|textarea|select|password|email|file. */
export function campo({ nombre, etiqueta, tipo = "text", valor = "", ayuda, opciones, requerido = false, atributos = {} }) {
  const id = idUnico(nombre);
  const idError = `${id}-error`, idAyuda = `${id}-ayuda`;
  let control;
  if (tipo === "textarea") control = h("textarea", { id, name: nombre, required: requerido, ...atributos }, valor);
  else if (tipo === "select") {
    control = h("select", { id, name: nombre, required: requerido, ...atributos },
      (opciones || []).map(([v, t]) => h("option", { value: v, selected: String(v) === String(valor) }, t)));
  } else control = h("input", { id, name: nombre, type: tipo, value: tipo === "file" ? null : valor, required: requerido, ...atributos });
  const error = h("p", { class: "error-campo", id: idError, hidden: true });
  if (ayuda) control.setAttribute("aria-describedby", idAyuda);
  const nodo = h("div", { class: "campo" }, h("label", { for: id }, etiqueta, requerido ? h("span", { class: "tenue" }, " (obligatorio)") : null),
    control, ayuda ? h("p", { class: "ayuda", id: idAyuda }, ayuda) : null, error);
  return { nodo, control, error, nombre, marcar(texto) {
    error.textContent = texto; error.hidden = false; control.setAttribute("aria-invalid", "true");
    control.setAttribute("aria-describedby", [ayuda ? idAyuda : null, idError].filter(Boolean).join(" "));
  }, limpiar() {
    error.hidden = true; error.textContent = ""; control.removeAttribute("aria-invalid");
    if (ayuda) control.setAttribute("aria-describedby", idAyuda); else control.removeAttribute("aria-describedby");
  } };
}

export function casilla({ nombre, etiqueta, marcada = false }) {
  const id = idUnico(nombre);
  const control = h("input", { id, name: nombre, type: "checkbox", checked: marcada });
  return { nodo: h("div", { class: "campo-check" }, control, h("label", { for: id }, etiqueta)), control, nombre, marcar() {}, limpiar() {} };
}

/* Formulario con resumen de errores y errores por campo (WCAG 3.3.1). enviar(valores) -> Promise; errores ErrorApi con .campos. */
export function formulario({ campos, textoBoton, enviar, alExito, secundario, columnas = false }) {
  const resumen = h("div", { tabindex: "-1" });
  const boton = h("button", { type: "submit", class: "btn" }, textoBoton);
  const cuerpo = columnas ? h("div", { class: "formulario-rejilla" }, campos.map((c) => c.nodo)) : campos.map((c) => c.nodo);
  const form = h("form", { novalidate: true, onsubmit: async (e) => {
    e.preventDefault();
    resumen.replaceChildren();
    campos.forEach((c) => c.limpiar());
    const valores = {};
    for (const c of campos) {
      if (c.control.type === "checkbox") valores[c.nombre] = c.control.checked;
      else if (c.control.type === "file") valores[c.nombre] = c.control.files && c.control.files[0];
      else valores[c.nombre] = typeof c.control.value === "string" ? c.control.value.trim() : c.control.value;
    }
    boton.disabled = true; boton.setAttribute("aria-busy", "true");
    try {
      const r = await enviar(valores);
      if (alExito) await alExito(r, form);
    } catch (err) {
      const camposErr = (err && err.campos) || {};
      let primero = null;
      for (const c of campos) if (camposErr[c.nombre]) { c.marcar(camposErr[c.nombre]); primero = primero || c.control; }
      const mensajes = (err && err.mensajes) || [String(err)];
      resumen.replaceChildren(mensaje("error", "No se pudo guardar",
        ...(mensajes.length > 1 ? [h("ul", {}, mensajes.map((m) => h("li", {}, m)))] : [mensajes[0]])));
      (primero || resumen).focus();
    } finally {
      boton.disabled = false; boton.removeAttribute("aria-busy");
    }
  } }, cuerpo, h("div", { class: "acciones" }, boton, secundario || null));
  return h("div", {}, resumen, form);
}

/* Botón que ejecuta una acción con estado (ocupado / resultado) y anuncia el resultado. */
export function botonAccion(texto, accion, { clase = "btn", etiqueta, alTerminar } = {}) {
  const estado = h("span", { role: "status", class: "tenue" });
  const b = h("button", { type: "button", class: clase, "aria-label": etiqueta || null, onclick: async () => {
    b.disabled = true; b.setAttribute("aria-busy", "true"); estado.textContent = "Procesando…";
    try {
      const r = await accion();
      estado.textContent = "";
      if (alTerminar) await alTerminar(r);
    } catch (err) {
      estado.textContent = (err && err.mensajes && err.mensajes[0]) || "No se pudo completar la acción.";
      anunciar(estado.textContent);
    } finally {
      b.disabled = false; b.removeAttribute("aria-busy");
    }
  } }, texto);
  return h("span", { class: "acciones" }, b, estado);
}
