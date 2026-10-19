/* Construcción de DOM sin innerHTML: todo texto (incluido el clínico) entra como texto, nunca como HTML. */
const SVG_NS = "http://www.w3.org/2000/svg";

function aplicar(el, atributos) {
  for (const [clave, valor] of Object.entries(atributos || {})) {
    if (valor === null || valor === undefined || valor === false) continue;
    if (clave === "texto") el.textContent = valor;
    else if (clave.startsWith("on") && typeof valor === "function") el.addEventListener(clave.slice(2), valor);
    else if (valor === true) el.setAttribute(clave, "");
    else el.setAttribute(clave, String(valor));
  }
}

function agregar(el, hijos) {
  for (const hijo of hijos) {
    if (hijo === null || hijo === undefined || hijo === false) continue;
    if (Array.isArray(hijo)) agregar(el, hijo);
    else el.appendChild(hijo instanceof Node ? hijo : document.createTextNode(String(hijo)));
  }
}

export function h(etiqueta, atributos, ...hijos) {
  const el = document.createElement(etiqueta);
  aplicar(el, atributos);
  agregar(el, hijos);
  return el;
}

export function svg(etiqueta, atributos, ...hijos) {
  const el = document.createElementNS(SVG_NS, etiqueta);
  aplicar(el, atributos);
  agregar(el, hijos);
  return el;
}

export function vaciar(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
  return el;
}

let _contador = 0;
export function idUnico(prefijo) {
  _contador += 1;
  return `${prefijo}-${_contador}`;
}

/* Anuncio para lectores de pantalla (región con aria-live del documento). */
export function anunciar(texto) {
  const region = document.getElementById("anuncios");
  if (!region) return;
  region.textContent = "";
  window.setTimeout(() => { region.textContent = texto; }, 60);
}
