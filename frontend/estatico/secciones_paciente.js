/* Secciones del paciente: documentos (DOC-01), órdenes médicas, consentimiento y privacidad (SEC-03 / NFR-06) y línea de tiempo (HC-06).
   La línea de tiempo se activa sola cuando el backend publica su ruta (ver frontend/extensiones.py). */
import { h, anunciar } from "./dom.js";
import { api, descargar } from "./api.js";
import { fecha } from "./formato.js";
import { campo, casilla, formulario, insignia, listaDatos, mensaje, tabla, tarjeta, vacio } from "./ui.js";

const base = (id) => `/api/clinica/pacientes/${id}`;
const recargar = () => window.dispatchEvent(new HashChangeEvent("hashchange"));

/* ---------------- Documentos ---------------- */

export function leerComoBase64(archivo) {
  return new Promise((resolver, rechazar) => {
    const lector = new FileReader();
    lector.onload = () => resolver(String(lector.result).split(",")[1] || "");
    lector.onerror = () => rechazar(new Error("No se pudo leer el archivo."));
    lector.readAsDataURL(archivo);
  });
}

export async function secDocumentos(ctx, p) {
  const docs = await api(`${base(p.id)}/documentos`);
  const estado = h("div", { role: "status", "aria-live": "polite" });
  const archivo = campo({ nombre: "archivo", etiqueta: "Archivo", tipo: "file", requerido: true,
    ayuda: "PDF, imagen (JPG o PNG) o DICOM, hasta 15 MB. Se guarda cifrado.", atributos: { accept: ".pdf,.jpg,.jpeg,.png,.dcm" } });
  const carga = ctx.sesion.puede_registrar ? formulario({ campos: [archivo], textoBoton: "Cargar al expediente",
    enviar: async (v) => {
      if (!v.archivo) { const e = new Error("Elige un archivo."); e.mensajes = [e.message]; e.campos = { archivo: e.message }; throw e; }
      if (v.archivo.size > 15 * 1024 * 1024) { const e = new Error("El archivo supera los 15 MB."); e.mensajes = [e.message]; e.campos = { archivo: e.message }; throw e; }
      return api(`${base(p.id)}/documentos`, { metodo: "POST", cuerpo: { nombre: v.archivo.name, contenido_base64: await leerComoBase64(v.archivo) } });
    },
    alExito: (d) => { estado.replaceChildren(mensaje("ok", "Documento cargado", `${d.nombre_archivo_original} (${d.tipo_documento}).`)); anunciar("Documento cargado."); window.setTimeout(recargar, 1200); } }) : null;

  const filas = docs.map((d) => [d.nombre_archivo_original, d.tipo_documento, `${Math.max(1, Math.round(d.tamano_bytes / 1024))} KB`,
    `${fecha((d.cargado_en || "").slice(0, 10))} · ${d.cargado_por}`,
    h("button", { type: "button", class: "btn sec chico", "aria-label": `Descargar ${d.nombre_archivo_original}`, onclick: async () => {
      try { await descargar(`${base(p.id)}/documentos/${d.id}/contenido`); } catch (err) { estado.replaceChildren(mensaje("error", "No se pudo descargar", err.mensajes[0])); }
    } }, "Descargar")]);
  return h("div", {}, estado,
    carga ? tarjeta("Cargar un documento clínico", carga) : null,
    docs.length ? tabla("Documentos del expediente", ["Archivo", "Tipo", "Tamaño", "Cargado", "Contenido"], filas, { filaEncabezado: true })
      : tarjeta("Documentos del expediente", vacio("Este paciente todavía no tiene documentos cargados.")));
}

/* ---------------- Órdenes médicas: el oncólogo prescribe, enfermería suministra ---------------- */

export const horaDe = (iso) => String(iso || "").slice(11, 16);

export function tablaHorario(titulo, dosis, vias, conPaciente = false) {
  if (!dosis.length) return tarjeta(titulo, vacio("No hay administraciones programadas en este periodo."));
  const columnas = ["Fecha", "Hora", ...(conPaciente ? ["Paciente"] : []), "Medicamento", "Dosis", "Vía"];
  return tabla(titulo, columnas, dosis.map((d) => [fecha(d.momento.slice(0, 10)), horaDe(d.momento),
    ...(conPaciente ? [h("a", { href: `#/pacientes/${d.paciente.id}/ordenes` }, d.paciente.nombre)] : []),
    h("strong", {}, d.medicamento), d.dosis, vias[d.via] || d.via]), { filaEncabezado: false });
}

export async function secOrdenes(ctx, p) {
  const r = await api(`${base(p.id)}/ordenes`);
  const estado = h("div", { role: "status", "aria-live": "polite" });
  const activas = r.ordenes.filter((o) => o.activa);
  const historial = r.ordenes.filter((o) => !o.activa);

  const suspender = (o) => h("button", { type: "button", class: "btn sec chico", onclick: async () => {
    const motivo = window.prompt(`Motivo para suspender ${o.medicamento} ${o.dosis}`);
    if (!motivo) return;
    try {
      await api(`${base(p.id)}/ordenes/${o.id}/suspender`, { metodo: "POST", cuerpo: { motivo } });
      anunciar("Orden suspendida."); recargar();
    } catch (err) { estado.replaceChildren(mensaje("error", "No se pudo suspender", err.mensajes[0])); }
  } }, "Suspender");

  const filasActivas = activas.map((o) => [h("strong", {}, o.medicamento), o.dosis, o.via_etiqueta, o.frecuencia,
    `${fecha(o.fecha_inicio)} · ${o.hora_inicio}${o.fecha_fin ? ` → ${fecha(o.fecha_fin)}` : ""}`, o.indicaciones || "—", o.ordenado_por,
    ...(r.puede_prescribir ? [suspender(o)] : [])]);
  const filasHistorial = historial.map((o) => [o.medicamento, o.dosis, o.via_etiqueta, o.frecuencia, `${fecha(o.fecha_inicio)}${o.fecha_fin ? ` → ${fecha(o.fecha_fin)}` : ""}`,
    o.suspendida_en ? `Suspendida el ${fecha(o.suspendida_en.slice(0, 10))}: ${o.motivo_suspension}` : "Terminada", o.ordenado_por]);

  let prescribir = null;
  if (r.puede_prescribir) {
    const hoy = new Date().toISOString().slice(0, 10);
    const medicamento = campo({ nombre: "medicamento", etiqueta: "Medicamento", requerido: true });
    const atajos = r.decision && r.decision.farmacos.length ? h("p", { class: "acciones" }, h("span", { class: "tenue" }, "De tu decisión de tratamiento: "),
      r.decision.farmacos.map((f) => h("button", { type: "button", class: "btn sec chico", onclick: () => { medicamento.control.value = f; medicamento.control.focus(); } }, f))) : null;
    prescribir = tarjeta("Prescribir un medicamento",
      r.decision ? mensaje("info", "Decisión de tratamiento vigente", `${r.decision.regimen || "Régimen sin código"}${r.decision.farmacos.length ? ` — ${r.decision.farmacos.join(" + ")}` : ""}. `,
        "Prescribe cada medicamento con su dosis, vía y horario: es lo que enfermería va a administrar.") : null,
      atajos,
      formulario({ columnas: true, textoBoton: "Prescribir", campos: [
        medicamento,
        campo({ nombre: "dosis", etiqueta: "Dosis", requerido: true, ayuda: "Cantidad y unidad, por ejemplo 200 mg o 500 mg/m²." }),
        campo({ nombre: "via", etiqueta: "Vía", tipo: "select", opciones: Object.entries(r.vias) }),
        campo({ nombre: "intervalo_horas", etiqueta: "Frecuencia", tipo: "select", opciones: Object.entries(r.frecuencias).sort((a, b) => Number(a[0]) - Number(b[0])) }),
        campo({ nombre: "fecha_inicio", etiqueta: "Fecha de inicio", tipo: "date", requerido: true, valor: hoy }),
        campo({ nombre: "hora_inicio", etiqueta: "Hora de la primera dosis", tipo: "time", requerido: true, valor: "08:00" }),
        campo({ nombre: "fecha_fin", etiqueta: "Fecha de fin (opcional)", tipo: "date" }),
        campo({ nombre: "indicaciones", etiqueta: "Indicaciones para enfermería", tipo: "textarea", ayuda: "Por ejemplo: diluir en 100 ml de SSN, pasar en 30 minutos." }),
        ...(r.decision ? [casilla({ nombre: "desde_decision", etiqueta: "Vincular a la decisión de tratamiento vigente" })] : []),
      ], enviar: (v) => api(`${base(p.id)}/ordenes`, { metodo: "POST", cuerpo: { ...v, intervalo_horas: Number(v.intervalo_horas), fecha_fin: v.fecha_fin || null } }),
      alExito: (o) => { anunciar(`Orden de ${o.medicamento} registrada.`); recargar(); } }));
  }

  return h("div", {}, estado,
    ctx.sesion.solo_lectura ? mensaje("info", null, "Consulta de enfermería: las órdenes las prescribe y suspende el oncólogo tratante.") : null,
    tablaHorario("Horario de administración (próximas 48 horas)", r.horario, r.vias),
    activas.length ? tabla("Órdenes vigentes", ["Medicamento", "Dosis", "Vía", "Frecuencia", "Desde", "Indicaciones", "Ordenada por", ...(r.puede_prescribir ? ["Acciones"] : [])], filasActivas, { filaEncabezado: true })
      : tarjeta("Órdenes vigentes", vacio("Este paciente no tiene órdenes médicas vigentes.")),
    prescribir,
    filasHistorial.length ? tabla("Suspendidas o terminadas", ["Medicamento", "Dosis", "Vía", "Frecuencia", "Periodo", "Estado", "Ordenada por"], filasHistorial, { filaEncabezado: true }) : null);
}

/* ---------------- Consentimiento y privacidad ---------------- */

const ESTADOS = {
  otorgada: { texto: "Otorgado", tono: "ok", icono: "ok" },
  pendiente: { texto: "Pendiente", tono: "aviso", icono: "alerta" },
  revocada: { texto: "Retirado", tono: "crit", icono: "alerta" },
  denegada: { texto: "No otorgado", tono: "crit", icono: "alerta" },
  "no exigido": { texto: "No exigido", tono: "neutra", icono: "info" },
};
const FINALIDADES = { asistencia_ia: "Uso de IA en la atención", investigacion: "Investigación", atencion_clinica: "Atención clínica" };

export async function secConsentimiento(ctx, p) {
  const [c, priv] = await Promise.all([api(`/api/pacientes/${p.id}/consentimiento-ia`), api(`${base(p.id)}/privacidad`)]);
  const puede = ctx.sesion.puede_consentimiento;
  const otorgar = (otorgado) => formulario({ campos: [
    campo({ nombre: "medio", etiqueta: "Medio", tipo: "select", opciones: [["escrito", "Escrito (firmado)"], ["digital", "Digital"], ["verbal_registrado", "Verbal, con registro"]] }),
    campo({ nombre: "soporte", etiqueta: "Soporte del documento", requerido: true, ayuda: "Número o nombre del documento firmado (queda como evidencia)." }),
  ], textoBoton: otorgado ? "Registrar consentimiento otorgado" : "Registrar que no lo otorgó",
  enviar: (v) => api(`/api/pacientes/${p.id}/consentimiento-ia`, { metodo: "POST", cuerpo: { ...v, otorgado } }),
  alExito: () => { anunciar(otorgado ? "Consentimiento registrado. La IA queda habilitada." : "Quedó registrado que el paciente no otorgó el consentimiento."); recargar(); } });
  const retirar = formulario({ campos: [campo({ nombre: "soporte", etiqueta: "Soporte del retiro (opcional)" })], textoBoton: "Registrar retiro del consentimiento",
    enviar: (v) => api(`/api/pacientes/${p.id}/consentimiento-ia/retiro`, { metodo: "POST", cuerpo: { medio: "escrito", soporte: v.soporte || null } }),
    alExito: () => { anunciar("Retiro registrado. La IA deja de aplicarse; la historia clínica no se borra."); recargar(); } });

  return h("div", {},
    h("section", { class: "tarjeta destacada" },
      h("h2", {}, "Consentimiento para el uso de IA", ESTADOS[c.estado] ? insignia(ESTADOS[c.estado]) : null),
      listaDatos([["Funciones de IA", c.ia_habilitada ? "Habilitadas" : "Bloqueadas para este paciente"], ["Detalle", c.motivo],
        ["Último registro", c.fecha ? `${fecha(c.fecha.slice(0, 10))} · ${c.medio || "—"} · soporte ${c.soporte || "—"}` : "—"]]),
      !c.ia_habilitada && c.exigido ? mensaje("info", null, "Sin consentimiento, el copiloto no usa los datos del paciente en preguntas, notas, resúmenes, diagnóstico, estadificación ni tratamiento. Su historia clínica sigue disponible.") : null),
    puede ? h("div", { class: "rejilla-2" },
      c.ia_habilitada && c.estado === "otorgada" ? tarjeta("El paciente retira el consentimiento", h("p", { class: "tenue" }, "Las funciones de IA dejan de aplicarse de inmediato. No se borra nada: el consentimiento anterior queda como evidencia."), retirar)
        : tarjeta("Registrar el consentimiento", otorgar(true)),
      c.estado === "pendiente" ? tarjeta("El paciente no lo otorga", otorgar(false)) : null)
      : mensaje("info", null, "Tu rol no registra consentimientos."),
    priv.autorizaciones.length ? tabla("Historial de autorizaciones (solo se agregan registros, nunca se borran)", ["Fecha", "Finalidad", "Estado", "Medio", "Soporte"],
      priv.autorizaciones.map((a) => [fecha((a.fecha || "").slice(0, 10)), FINALIDADES[a.finalidad] || a.finalidad,
        ESTADOS[a.estado] ? insignia(ESTADOS[a.estado]) : a.estado, a.medio || "—", a.evidencia_ref || "—"]))
      : tarjeta("Historial de autorizaciones", vacio("Todavía no hay registros.")));
}

/* ---------------- Línea de tiempo (HC-06, se conecta sola) ---------------- */

function valor(evento, nombres) {
  for (const n of nombres) if (evento[n] !== undefined && evento[n] !== null && evento[n] !== "") return evento[n];
  return null;
}

const MESES_LARGOS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];

/* AC2: una fecha con solo mes y año (o solo año) se dice aproximada, con texto y no solo con el borde punteado. */
function fechaEvento(e) {
  if (!e.fecha) return "Fecha desconocida";
  if (!e.aproximada) return fecha(e.fecha);
  const m = /^(\d{4})-(\d{2})/.exec(e.fecha);
  return m ? `${MESES_LARGOS[Number(m[2]) - 1]} de ${m[1]} (fecha aproximada: solo mes y año)` : `${e.fecha.slice(0, 4)} (fecha aproximada: solo año)`;
}

export async function secLineaTiempo(ctx, p) {
  const ext = ctx.capacidades.extensiones.linea_tiempo;
  if (!ext.disponible) {
    return tarjeta("Línea de tiempo del paciente",
      mensaje("info", "Pendiente de integrar", "Esta vista se activa sola cuando el sistema publique la línea de tiempo cronológica. No hay que cambiar nada en la interfaz."),
      h("p", { class: "tenue" }, "Mientras tanto, la historia clínica, los laboratorios y las imágenes muestran los eventos por separado."));
  }
  const crudo = await api(`/api${ext.ruta.replace("{id}", p.id)}`);
  const eventos = (Array.isArray(crudo) ? crudo : crudo.eventos || []).map((e) => {
    const precision = e.precision || e.precision_fecha;
    const tipo = String(valor(e, ext.campos.tipo) || "evento");
    return { fecha: valor(e, ext.campos.fecha) ? String(valor(e, ext.campos.fecha)) : "", tipo, etiqueta: String(e.tipo_etiqueta || tipo),
      descripcion: String(valor(e, ext.campos.descripcion) || ""), aproximada: Boolean(valor(e, ext.campos.aproximada)) || precision === "mes" || precision === "anio" };
  }).sort((a, b) => (!a.fecha) - (!b.fecha) || a.fecha.localeCompare(b.fecha));  // sin fecha, al final
  const tipos = [...new Map(eventos.map((e) => [e.tipo, e.etiqueta])).entries()].sort((a, b) => a[1].localeCompare(b[1]));
  const lista = h("ol", { class: "linea-tiempo" });
  const pintar = (tipo) => {
    const visibles = eventos.filter((e) => !tipo || e.tipo === tipo);
    lista.replaceChildren(...visibles.map((e) => h("li", { class: e.aproximada ? "aproximada" : null },
      h("strong", {}, fechaEvento(e)), " · ", insignia({ texto: e.etiqueta, tono: "info", icono: "info" }),
      h("p", {}, e.descripcion))));
    anunciar(`${visibles.length} eventos.`);
  };
  pintar("");
  const filtro = campo({ nombre: "tipo", etiqueta: "Tipo de evento", tipo: "select", opciones: [["", `Todos (${eventos.length})`],
    ...tipos.map(([t, etiqueta]) => [t, `${etiqueta} (${eventos.filter((e) => e.tipo === t).length})`])] });
  filtro.control.addEventListener("change", () => pintar(filtro.control.value));
  const aproximadas = eventos.filter((e) => e.aproximada).length;
  return h("div", {}, tarjeta("Línea de tiempo del paciente",
    h("p", { class: "ayuda" }, "Del evento más antiguo al más reciente. Los laboratorios de un mismo día se agrupan en un solo evento."),
    filtro.nodo,
    aproximadas ? h("p", { class: "ayuda" }, `Borde punteado: fecha aproximada (${aproximadas} ${aproximadas === 1 ? "evento solo tiene" : "eventos solo tienen"} mes y año, o solo año).`) : null,
    eventos.length ? lista : vacio("Sin eventos registrados.")));
}
