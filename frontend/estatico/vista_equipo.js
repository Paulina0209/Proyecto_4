/* Pantallas del equipo de atención del oncólogo:
   - Medicamentos (enfermería): el horario de administración de las órdenes médicas de sus pacientes.
   - Admisiones (administrativo): buscar pacientes del equipo con sus datos de admisión, registrar el consentimiento
     y exportar el resumen. Sin datos clínicos. */
import { h, anunciar } from "./dom.js";
import { api, descargar } from "./api.js";
import { SEXOS, edad } from "./formato.js";
import { campo, cargando, errorConReintento, formulario, insignia, mensaje, tabla, tarjeta, vacio } from "./ui.js";
import { tablaHorario } from "./secciones_paciente.js";

const VIAS = { VO: "Oral", IV: "Intravenosa", SC: "Subcutánea", IM: "Intramuscular", TOP: "Tópica", INH: "Inhalada", SL: "Sublingual" };

function pantalla(titulo, sub, cargar) {
  const cuerpo = h("div", {}, cargando());
  const intentar = async () => {
    cuerpo.replaceChildren(cargando());
    try { cuerpo.replaceChildren(await cargar()); } catch (err) { cuerpo.replaceChildren(errorConReintento(err, intentar)); }
  };
  return { titulo, nodo: h("div", {}, h("h1", {}, titulo), h("p", { class: "sub" }, sub), cuerpo), alMostrar: intentar };
}

/* Si la persona trabaja con varios oncólogos, elige con cuál equipo trabaja ahora (queda en la dirección). */
export function selectorEquipo(ctx, ruta, { todos = true } = {}) {
  const equipo = ctx.sesion.equipo || [];
  if (equipo.length < 2) return null;
  const actual = ctx.consulta.get("equipo") || (todos ? "" : String(equipo[0].id));
  const select = h("select", { id: "equipo-actual", onchange: () => { window.location.hash = `${ruta}${select.value ? `?equipo=${select.value}` : ""}`; } },
    todos ? h("option", { value: "" }, "Todos mis oncólogos") : null, equipo.map((o) => h("option", { value: String(o.id), selected: String(o.id) === actual }, o.nombre)));
  return h("div", { class: "campo selector-equipo" }, h("label", { for: "equipo-actual" }, "Equipo de"), select);
}

/* ---------------- Enfermería: horario de administración ---------------- */

export async function vistaMedicamentos(ctx) {
  if (!ctx.sesion.ver_ordenes) return { titulo: "Medicamentos", nodo: h("div", {}, h("h1", {}, "Medicamentos"), mensaje("aviso", null, ctx.sesion.mensaje_sin_acceso_clinico || "Tu rol no administra medicamentos.")) };
  const equipo = ctx.consulta.get("equipo") || "";
  const nombres = (ctx.sesion.equipo || []).map((o) => o.nombre).join(", ");
  return pantalla("Medicamentos", `Lo que toca administrar según las órdenes médicas de los pacientes de ${nombres || "tu equipo"}. Las órdenes las prescribe el oncólogo tratante.`, async () => {
    const r = await api("/api/clinica/enfermeria/horario", { consulta: { equipo, horas: 24 } });
    const ahora = new Date().toISOString().slice(0, 16);
    const pendientes = r.dosis.filter((d) => d.momento >= ahora.slice(0, 13));
    return h("div", {},
      selectorEquipo(ctx, "#/medicamentos"),
      tablaHorario("Próximas 24 horas", pendientes, VIAS, true),
      r.pacientes.length ? tabla("Pacientes con órdenes vigentes", ["Paciente", "Identificación", ""], r.pacientes.map((p) => [
        h("a", { href: `#/pacientes/${p.id}/ordenes` }, p.nombre), p.identificacion,
        h("a", { class: "btn sec chico", href: `#/asistente?paciente=${p.id}` }, "Preguntar al asistente")]), { filaEncabezado: true })
        : tarjeta("Pacientes con órdenes vigentes", vacio("Ningún paciente de tu equipo tiene órdenes médicas vigentes.")),
      mensaje("info", "Consultas sobre medicamentos", "En el Asistente puedes preguntar, por ejemplo, «¿qué le toca a las 14:00?» o «¿qué dosis tiene ordenada?». Responde solo con las órdenes del oncólogo."));
  });
}

/* ---------------- Admisiones ---------------- */

const CONSENTIMIENTO = { otorgada: ["Otorgado", "ok"], pendiente: ["Pendiente", "aviso"], revocada: ["Retirado", "crit"], denegada: ["No otorgado", "crit"], "no exigido": ["No exigido", "info"] };

export async function vistaAdmisiones(ctx) {
  if (!ctx.sesion.acceso_admision) return { titulo: "Admisiones", nodo: h("div", {}, h("h1", {}, "Admisiones"), mensaje("aviso", null, ctx.sesion.mensaje_sin_acceso_clinico || "Tu rol no trabaja en admisiones.")) };
  const equipo = ctx.consulta.get("equipo") || "";
  const q = ctx.consulta.get("q") || "";
  return pantalla("Admisiones", "Pacientes de los oncólogos de tu equipo: datos de admisión, consentimiento informado y exportación del resumen. Sin datos clínicos.", async () => {
    const r = await api("/api/clinica/admision/pacientes", { consulta: { equipo, q } });
    const estado = h("div", { role: "status", "aria-live": "polite" });
    const buscar = h("form", { class: "tarjeta filtros", role: "search", onsubmit: (e) => {
      e.preventDefault();
      const p = new URLSearchParams();
      const texto = e.target.elements.q.value.trim();
      if (texto) p.set("q", texto);
      if (equipo) p.set("equipo", equipo);
      window.location.hash = `#/admisiones${p.toString() ? `?${p}` : ""}`;
    } }, h("div", { class: "campo" }, h("label", { for: "buscar-admision" }, "Nombre o identificación"), h("input", { id: "buscar-admision", name: "q", value: q })),
      h("div", { class: "acciones" }, h("button", { type: "submit", class: "btn" }, "Buscar"),
        ctx.sesion.puede_registrar_paciente ? h("a", { class: "btn sec", href: `#/pacientes/nuevo${equipo ? `?equipo=${equipo}` : ""}` }, "Registrar paciente") : null));

    const zonaConsentimiento = h("div", {});
    const consentir = (p) => {
      zonaConsentimiento.replaceChildren(tarjeta(`Consentimiento de IA — ${p.nombre_completo}`,
        mensaje("info", null, "Registra lo que el paciente decidió y el documento que lo respalda (SEC-03)."),
        formulario({ campos: [
          campo({ nombre: "otorgado", etiqueta: "Decisión del paciente", tipo: "select", opciones: [["si", "Otorga el consentimiento"], ["no", "No lo otorga"]] }),
          campo({ nombre: "medio", etiqueta: "Medio", tipo: "select", opciones: [["escrito", "Escrito (firmado)"], ["digital", "Digital"], ["verbal_registrado", "Verbal, con registro"]] }),
          campo({ nombre: "soporte", etiqueta: "Soporte del documento", requerido: true, ayuda: "Número o nombre del documento firmado." }),
        ], textoBoton: "Registrar", enviar: (v) => api(`/api/pacientes/${p.id}/consentimiento-ia`, { metodo: "POST", cuerpo: { medio: v.medio, soporte: v.soporte, otorgado: v.otorgado === "si" } }),
        alExito: () => { anunciar("Consentimiento registrado."); window.dispatchEvent(new HashChangeEvent("hashchange")); } })));
      zonaConsentimiento.querySelector("h2").focus();
    };
    const exportar = (p) => h("button", { type: "button", class: "btn sec chico", onclick: async () => {
      try { await descargar(`/api/pacientes/${p.id}/exportar?formato=pdf`); anunciar("Resumen descargado."); }
      catch (err) { estado.replaceChildren(mensaje("error", "No se pudo exportar", err.mensajes[0])); }
    } }, "Exportar PDF");
    const filas = r.pacientes.map((p) => {
      const a = edad(p.fecha_nacimiento);
      const [texto, tono] = CONSENTIMIENTO[p.consentimiento_ia] || [p.consentimiento_ia, "info"];
      return [p.nombre_completo, `${p.tipo_identificacion || ""} ${p.numero_identificacion || ""}`.trim(), a === null ? "—" : `${a} años`,
        SEXOS[p.sexo] || p.sexo || "—", insignia({ texto, tono, icono: tono === "ok" ? "ok" : "info" }),
        h("div", { class: "acciones" }, ctx.sesion.puede_consentimiento ? h("button", { type: "button", class: "btn sec chico", onclick: () => consentir(p) }, "Consentimiento") : null,
          ctx.sesion.puede_exportar ? exportar(p) : null)];
    });
    return h("div", {}, estado, selectorEquipo(ctx, "#/admisiones"), buscar,
      filas.length ? tabla(`${filas.length} pacientes${q ? ` para «${q}»` : " (los más recientes)"}`, ["Paciente", "Identificación", "Edad", "Sexo", "Consentimiento de IA", "Acciones"], filas, { filaEncabezado: true })
        : mensaje("info", "Sin resultados", "No hay pacientes de tu equipo que coincidan con la búsqueda."),
      zonaConsentimiento);
  });
}

