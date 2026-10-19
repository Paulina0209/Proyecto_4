import { h } from "./dom.js";
import { mensaje } from "./ui.js";

/* El tablero ADM-02 se muestra tal cual lo genera el sistema (ya revisado en NFR-03), dentro de un marco del mismo sitio. */
export async function vistaMetricas(ctx) {
  if (!ctx.sesion.ver_metricas) {
    return { titulo: "Métricas de uso", nodo: h("div", {}, h("h1", {}, "Métricas de uso"),
      mensaje("aviso", "Sin permiso", "Solo la dirección médica puede ver las métricas de uso de la institución.")) };
  }
  const marco = h("iframe", { class: "marco-tablero", src: "/panel/metricas", title: "Tablero de métricas de uso de la institución" });
  const nodo = h("div", {},
    h("h1", {}, "Métricas de uso"),
    h("p", { class: "sub" }, "Datos agregados de toda la institución. Nunca se muestran por médico."),
    marco);
  return { titulo: "Métricas de uso", nodo };
}
