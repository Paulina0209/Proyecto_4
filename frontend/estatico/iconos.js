import { svg } from "./dom.js";

/* Iconos de apoyo: siempre van junto a un texto, así que son decorativos (aria-hidden). */
const RUTAS = {
  alerta: "M8 1.5 15 14H1L8 1.5Zm-.75 4.5v4h1.5V6h-1.5Zm0 5.25v1.5h1.5v-1.5h-1.5Z",
  ok: "M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1Zm3.2 4.9L7.1 10 4.8 7.7l1-1 1.3 1.3 3.1-3.1 1 1Z",
  info: "M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1Zm-.75 3h1.5v1.5h-1.5V4Zm0 3h1.5v4.5h-1.5V7Z",
  reloj: "M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1Zm.75 3v3.7l2.6 1.5-.75 1.3-3.35-1.9V4h1.5Z",
  pausa: "M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1ZM6 5h1.5v6H6V5Zm2.5 0H10v6H8.5V5Z",
};

export function icono(nombre) {
  return svg("svg", { viewBox: "0 0 16 16", "aria-hidden": "true", focusable: "false" },
    svg("path", { d: RUTAS[nombre] || RUTAS.info, fill: "currentColor" }));
}
