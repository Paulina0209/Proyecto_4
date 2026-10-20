import { h, anunciar, idUnico } from "./dom.js";
import { api } from "./api.js";
import { edad, fecha, ESTADOS_TRATAMIENTO } from "./formato.js";
import { cargando, errorConReintento, insignia, mensaje, tabla } from "./ui.js";
import { selectorEquipo } from "./vista_equipo.js";

const TAMANO = 10;
const CAMPOS = ["nombre", "diagnostico", "estado_tratamiento", "ultima_consulta_desde", "ultima_consulta_hasta"];

export async function vistaPacientes(ctx) {
  const contenedor = h("div", {});
  const resultados = h("div", {});
  const filtros = {};
  for (const c of CAMPOS) filtros[c] = ctx.consulta.get(c) || "";
  const pagina = Math.max(1, Number(ctx.consulta.get("pagina")) || 1);

  function ir(cambios) {
    const p = new URLSearchParams();
    const nuevo = { ...filtros, ...cambios };
    for (const c of CAMPOS) if (nuevo[c]) p.set(c, nuevo[c]);
    if (nuevo.pagina && Number(nuevo.pagina) > 1) p.set("pagina", nuevo.pagina);
    const texto = p.toString();
    window.location.hash = `#/pacientes${texto ? `?${texto}` : ""}`;
  }

  const campo = (id, etiqueta, nombre, tipo = "text") =>
    h("div", { class: "campo" }, h("label", { for: id }, etiqueta),
      h("input", { id, name: nombre, type: tipo, value: filtros[nombre], autocomplete: "off" }));
  const idEstado = idUnico("estado");
  const selectEstado = h("select", { id: idEstado, name: "estado_tratamiento" },
    h("option", { value: "" }, "Todos"),
    Object.entries(ESTADOS_TRATAMIENTO).map(([clave, def]) => h("option", { value: clave, selected: filtros.estado_tratamiento === clave }, def.texto)));

  const formulario = h("form", { class: "tarjeta", role: "search", "aria-label": "Buscar pacientes", onsubmit: (e) => {
    e.preventDefault();
    const datos = new FormData(e.target);
    const cambios = { pagina: 1 };
    for (const c of CAMPOS) cambios[c] = String(datos.get(c) || "").trim();
    ir(cambios);
  } },
    h("div", { class: "filtros" },
      campo(idUnico("nombre"), "Nombre", "nombre"),
      campo(idUnico("dx"), "Diagnóstico", "diagnostico"),
      h("div", { class: "campo" }, h("label", { for: idEstado }, "Estado del tratamiento"), selectEstado),
      campo(idUnico("desde"), "Última consulta desde", "ultima_consulta_desde", "date"),
      campo(idUnico("hasta"), "Última consulta hasta", "ultima_consulta_hasta", "date")),
    h("div", { class: "acciones" },
      h("button", { type: "submit", class: "btn" }, "Buscar"),
      h("a", { class: "btn sec", href: "#/pacientes" }, "Limpiar filtros")));

  async function cargar() {
    resultados.replaceChildren(cargando("Buscando pacientes…"));
    try {
      const r = await api("/api/pacientes/buscar", { consulta: { ...Object.fromEntries(CAMPOS.map((c) => [c, filtros[c]])), pagina, tamano_pagina: TAMANO,
        equipo: ctx.consulta.get("equipo") || "" } });
      resultados.replaceChildren(...pintar(r));
      anunciar(r.total === 0 ? "No se encontraron pacientes." : `${r.total} ${r.total === 1 ? "paciente encontrado" : "pacientes encontrados"}. Página ${r.pagina} de ${r.total_paginas}.`);
    } catch (err) {
      resultados.replaceChildren(err.estado === 400
        ? mensaje("error", "Revisa los filtros", ...(err.mensajes.length > 1 ? [h("ul", {}, err.mensajes.map((m) => h("li", {}, m)))] : [err.mensajes[0]]))
        : errorConReintento(err, cargar));
    }
  }

  function pintar(r) {
    if (r.total === 0) return [mensaje("info", "Sin resultados", r.mensaje || "No hay pacientes que coincidan con la búsqueda.")];
    const aplicados = Object.keys(r.filtros_aplicados || {}).length;
    const filas = r.items.map((p) => {
      const a = edad(p.fecha_nacimiento);
      return [
        h("a", { href: `#/pacientes/${p.id}` }, p.nombre_completo),
        a === null ? "—" : `${a} años`,
        p.diagnosticos.length ? p.diagnosticos.join("; ") : h("span", { class: "tenue" }, "Sin diagnóstico registrado"),
        p.estado_tratamiento && ESTADOS_TRATAMIENTO[p.estado_tratamiento] ? insignia(ESTADOS_TRATAMIENTO[p.estado_tratamiento]) : h("span", { class: "tenue" }, "Sin tratamiento"),
        p.fecha_ultima_consulta ? h("time", { datetime: p.fecha_ultima_consulta }, fecha(p.fecha_ultima_consulta)) : h("span", { class: "tenue" }, "Sin consultas"),
      ];
    });
    const anterior = r.pagina > 1 ? h("a", { class: "btn sec chico", href: enlace(r.pagina - 1) }, "Anterior") : h("span", { class: "btn sec chico", "aria-disabled": "true" }, "Anterior");
    const siguiente = r.pagina < r.total_paginas ? h("a", { class: "btn sec chico", href: enlace(r.pagina + 1) }, "Siguiente") : h("span", { class: "btn sec chico", "aria-disabled": "true" }, "Siguiente");
    return [
      tabla(`${r.total} ${r.total === 1 ? "paciente" : "pacientes"}${aplicados ? " con los filtros aplicados" : ""}`,
        ["Paciente", "Edad", "Diagnóstico", "Tratamiento", "Última consulta"], filas, { filaEncabezado: true }),
      h("nav", { class: "paginacion", "aria-label": "Páginas de resultados" }, anterior, h("span", {}, `Página ${r.pagina} de ${r.total_paginas}`), siguiente),
    ];
  }

  function enlace(n) {
    const p = new URLSearchParams();
    for (const c of CAMPOS) if (filtros[c]) p.set(c, filtros[c]);
    if (n > 1) p.set("pagina", n);
    const t = p.toString();
    return `#/pacientes${t ? `?${t}` : ""}`;
  }

  contenedor.append(
    h("div", { class: "ficha-cabecera" },
      h("div", {}, h("h1", {}, "Pacientes"), h("p", { class: "sub" }, "Solo ves a los pacientes que atiendes tú.")),
      ctx.sesion.puede_registrar ? h("div", { class: "acciones" }, h("a", { class: "btn", href: "#/pacientes/nuevo" }, "Registrar paciente")) : null,
      selectorEquipo(ctx, "#/pacientes", { todos: false })),
    formulario, resultados);
  const nodo = contenedor;
  return { titulo: "Pacientes", nodo, alMostrar: cargar };
}
