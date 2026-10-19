/* Piezas visuales compartidas. */
import { h, idUnico } from "./dom.js";
import { icono } from "./iconos.js";

export function insignia(def) {
  return h("span", { class: `insignia ${def.tono}` }, icono(def.icono), def.texto);
}

/* tipo: error | aviso | info | ok. Los errores se anuncian al instante (role=alert); el resto, con cortesía (role=status). */
export function mensaje(tipo, titulo, ...cuerpo) {
  return h("div", { class: `mensaje ${tipo}`, role: tipo === "error" ? "alert" : "status" },
    titulo ? h("strong", { class: "titulo" }, titulo) : null, ...cuerpo);
}

export function cargando(texto = "Cargando…") {
  return h("p", { class: "cargando", role: "status" }, texto);
}

/* Error de carga con la posibilidad de reintentar. */
export function errorConReintento(err, reintentar) {
  return h("div", {},
    mensaje("error", "No se pudo cargar esta información", err.mensajes && err.mensajes.length ? err.mensajes[0] : String(err)),
    reintentar ? h("button", { type: "button", class: "btn sec", onclick: reintentar }, "Reintentar") : null);
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

export function listaDatos(pares) {
  return h("dl", { class: "dato" }, pares.flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v === null || v === undefined || v === "" ? "—" : v)]));
}
