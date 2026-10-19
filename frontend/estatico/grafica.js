/* Gráfica de tendencia de un marcador: SVG con título y descripción, forma distinta por estado (no solo color)
   y, debajo, la misma información en una tabla (la gráfica nunca es la única vía a los datos). */
import { h, svg, idUnico } from "./dom.js";
import { fecha } from "./formato.js";
import { tabla } from "./ui.js";

const W = 560, ALTO = 260, MI = 56, MD = 16, MS = 16, MB = 40;

function tiempo(iso) { return new Date(`${iso}T00:00:00Z`).getTime(); }

function estadoDe(p) {
  if (p.critico) return { clave: "critico", texto: "Crítico" };
  if (p.alterado) return { clave: "alterado", texto: "Fuera de rango" };
  return { clave: "normal", texto: "Normal" };
}

function marcador(x, y, clave) {
  if (clave === "critico") return svg("path", { class: "punto critico", d: `M${x} ${y - 8} L${x + 8} ${y} L${x} ${y + 8} L${x - 8} ${y} Z` });
  if (clave === "alterado") return svg("rect", { class: "punto alterado", x: x - 6, y: y - 6, width: 12, height: 12 });
  return svg("circle", { class: "punto", cx: x, cy: y, r: 6 });
}

function describir(prueba, unidad, puntos) {
  const a = puntos[0], z = puntos[puntos.length - 1];
  const u = unidad ? ` ${unidad}` : "";
  const ultimo = estadoDe(z).clave === "normal" ? "" : `; el último valor es ${estadoDe(z).texto.toLowerCase()}`;
  return `${prueba}: ${puntos.length} resultados, de ${a.valor}${u} el ${fecha(a.fecha)} a ${z.valor}${u} el ${fecha(z.fecha)}${ultimo}.`;
}

export function graficaDeSerie(prueba, serie) {
  const unidad = serie.unidad || "";
  const todos = serie.puntos;
  const numericos = todos.filter((p) => typeof p.valor_numerico === "number");
  const caja = h("div", {});
  const titulo = `${prueba}${unidad ? ` (${unidad})` : ""}`;
  caja.appendChild(h("h3", {}, titulo));
  if (numericos.length >= 2) {
    const ids = { t: idUnico("gt"), d: idUnico("gd") };
    const ts = numericos.map((p) => tiempo(p.fecha));
    const t0 = Math.min(...ts), t1 = Math.max(...ts);
    const vs = numericos.map((p) => p.valor_numerico);
    let v0 = Math.min(...vs), v1 = Math.max(...vs);
    if (v0 === v1) { v0 -= 1; v1 += 1; }
    const margen = (v1 - v0) * 0.12;
    v0 -= margen; v1 += margen;
    const x = (t) => MI + (t1 === t0 ? (W - MI - MD) / 2 : ((t - t0) / (t1 - t0)) * (W - MI - MD));
    const y = (v) => MS + (1 - (v - v0) / (v1 - v0)) * (ALTO - MS - MB);
    const g = svg("svg", { class: "grafica", viewBox: `0 0 ${W} ${ALTO}`, role: "img", "aria-labelledby": `${ids.t} ${ids.d}` },
      svg("title", { id: ids.t }, `Tendencia de ${titulo}`),
      svg("desc", { id: ids.d }, describir(prueba, unidad, numericos)));
    for (let i = 0; i <= 3; i += 1) {
      const v = v0 + ((v1 - v0) * i) / 3;
      g.appendChild(svg("line", { class: "rejilla-h", x1: MI, x2: W - MD, y1: y(v), y2: y(v) }));
      g.appendChild(svg("text", { class: "etiqueta", x: MI - 8, y: y(v) + 4, "text-anchor": "end" }, v.toFixed(Math.abs(v) < 10 ? 1 : 0)));
    }
    g.appendChild(svg("line", { class: "eje", x1: MI, x2: W - MD, y1: ALTO - MB, y2: ALTO - MB }));
    const marcas = numericos.length <= 5 ? numericos : [numericos[0], numericos[Math.floor(numericos.length / 2)], numericos[numericos.length - 1]];
    marcas.forEach((p) => g.appendChild(svg("text", { class: "etiqueta", x: x(tiempo(p.fecha)), y: ALTO - MB + 20, "text-anchor": "middle" }, fecha(p.fecha))));
    g.appendChild(svg("polyline", { class: "linea", points: numericos.map((p) => `${x(tiempo(p.fecha))},${y(p.valor_numerico)}`).join(" ") }));
    numericos.forEach((p) => g.appendChild(marcador(x(tiempo(p.fecha)), y(p.valor_numerico), estadoDe(p).clave)));
    caja.appendChild(h("div", { class: "zona-grafica", role: "region", tabindex: "0", "aria-label": `Gráfica: ${titulo}` }, g));
    caja.appendChild(h("p", { class: "ayuda" }, "Círculo: normal. Cuadrado: fuera de rango. Rombo: crítico."));
  } else {
    caja.appendChild(h("p", { class: "tenue" }, "Hace falta más de un resultado numérico para dibujar una tendencia; los valores están en la tabla."));
  }
  caja.appendChild(tabla(`Resultados de ${titulo}`, ["Fecha", "Valor", "Estado"],
    todos.map((p) => [h("time", { datetime: p.fecha }, fecha(p.fecha)), `${p.valor}${unidad ? ` ${unidad}` : ""}`,
      estadoDe(p).texto + (p.en_conflicto ? " · en conflicto" : "")])));
  return caja;
}
