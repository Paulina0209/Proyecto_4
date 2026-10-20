/* Expediente del paciente: banda con lo esencial y barra lateral con las secciones agrupadas.
   Las secciones del expediente están aquí; las de IA, apoyo a la decisión y paciente, en sus módulos. */
import { h, anunciar } from "./dom.js";
import { api, descargar } from "./api.js";
import { CAMPOS_FALTANTES, ESTADOS_TRATAMIENTO, RELEVANCIA_BIOMARCADOR, SEVERIDADES, SEXOS, TIPOS_ALERTA, edad, fecha } from "./formato.js";
import { graficaDeSerie } from "./grafica.js";
import { campo, cargando, errorConReintento, formulario, insignia, listaDatos, mensaje, tabla, tarjeta } from "./ui.js";
import { secAsistente, secJunta, secNotas } from "./secciones_ia.js";
import { secDiagnostico, secEstadificacion, secEvidencia, secTratamiento } from "./secciones_decision.js";
import { secConsentimiento, secDocumentos, secLineaTiempo } from "./secciones_paciente.js";

const GRUPOS = [
  ["Expediente", [["resumen", "Resumen"], ["historia", "Historia clínica"], ["laboratorios", "Laboratorios"], ["imagenes", "Imágenes"],
    ["biomarcadores", "Biomarcadores y biopsias"], ["documentos", "Documentos"], ["linea-tiempo", "Línea de tiempo"]]],
  ["Asistente de IA", [["asistente", "Preguntas y asistente"], ["notas", "Notas de consulta"], ["junta", "Resumen para junta"]]],
  ["Apoyo a la decisión", [["diagnostico", "Diagnóstico"], ["estadificacion", "Estadificación"], ["tratamiento", "Tratamiento"], ["evidencia", "Evidencia científica"]]],
  ["Paciente", [["consentimiento", "Consentimiento y privacidad"]]],
];
const SECCIONES = GRUPOS.flatMap(([, s]) => s);

const vacio = (texto) => h("p", { class: "tenue" }, texto);
const tiempo = (iso) => (iso ? h("time", { datetime: iso }, fecha(iso)) : "—");
const acceso = (x) => h("span", {}, tiempo(x.fecha), " · ", x.titulo ? h("strong", {}, `${x.titulo}: `) : null, x.resumen);
const ruta = (id, sufijo = "") => `/api/pacientes/${id}${sufijo}`;

function lista(items, vacioTexto, pintar) {
  if (!items.length) return vacio(vacioTexto);
  return h("ul", { class: "lista-limpia" }, items.map((x) => h("li", {}, pintar(x))));
}

const CONSENTIMIENTO = {
  otorgada: { texto: "IA habilitada (consentimiento vigente)", tono: "ok", icono: "ok" },
  pendiente: { texto: "Consentimiento de IA pendiente", tono: "aviso", icono: "alerta" },
  revocada: { texto: "Consentimiento de IA retirado", tono: "crit", icono: "alerta" },
  denegada: { texto: "Paciente no autorizó la IA", tono: "crit", icono: "alerta" },
  "no exigido": { texto: "IA habilitada", tono: "info", icono: "info" },
};

/* ---------------- Marco común: banda del paciente, exportación y barra lateral ---------------- */

function marco(ctx, paciente, consentimiento, seccion, contenido) {
  const a = edad(paciente.fecha_nacimiento);
  const estado = h("div", { id: "estado-ficha", role: "status", "aria-live": "polite" });
  const botones = [h("a", { class: "btn chico", href: `#/asistente?paciente=${paciente.id}` }, "Preguntar al asistente")];
  if (ctx.sesion.puede_exportar) {
    const exportar = (formato, texto) => h("button", { type: "button", class: "btn sec chico", onclick: async () => {
      estado.replaceChildren(h("p", { class: "tenue" }, "Preparando la descarga…"));
      try {
        await descargar(ruta(paciente.id, `/exportar?formato=${formato}`));
        estado.replaceChildren(mensaje("ok", null, `Se descargó el expediente en ${formato.toUpperCase()}.`));
      } catch (err) {
        estado.replaceChildren(mensaje("error", "No se pudo exportar", err.mensajes[0]));
      }
    } }, texto);
    botones.push(exportar("html", "Exportar (HTML accesible)"), exportar("pdf", "Exportar (PDF)"));
  }
  const ia = ctx.capacidades.modelo_ia;
  const insignias = [
    consentimiento && CONSENTIMIENTO[consentimiento.estado] ? insignia(CONSENTIMIENTO[consentimiento.estado]) : null,
    insignia(ia && ia.configurado ? { texto: ia.descripcion, tono: "ia", icono: "info" } : { texto: "IA por reglas (sin llave de OpenAI)", tono: "neutra", icono: "info" }),
  ];
  const lt = ctx.capacidades.extensiones.linea_tiempo;
  return h("div", {},
    h("p", { class: "migas" }, h("a", { href: "#/pacientes" }, "Pacientes"), " / ", paciente.nombre_completo),
    h("div", { class: "ficha-cabecera" },
      h("div", {},
        h("h1", {}, paciente.nombre_completo),
        h("p", { class: "sub" }, [a === null ? null : `${a} años`, SEXOS[paciente.sexo] || paciente.sexo, `Identificación ${paciente.numero_identificacion}`].filter(Boolean).join(" · ")),
        h("div", { class: "insignias" }, insignias)),
      botones.length ? h("div", { class: "acciones" }, botones) : null),
    estado,
    h("div", { class: "espacio" },
      h("nav", { class: "secciones", "aria-label": "Secciones del expediente" },
        GRUPOS.map(([grupo, items]) => [h("h2", {}, grupo), h("ul", {}, items.map(([clave, texto]) =>
          h("li", {}, h("a", { href: `#/pacientes/${paciente.id}${clave === "resumen" ? "" : `/${clave}`}`, "aria-current": clave === seccion ? "page" : null },
            texto, clave === "linea-tiempo" && !lt.disponible ? h("span", { class: "insignia neutra" }, "pronto") : null))))])),
      h("div", {}, contenido)));
}

/* ---------------- Secciones del expediente ---------------- */

async function secResumen(ctx, p) {
  const [r, consentimiento, faltantes] = await Promise.all([
    api(ruta(p.id, "/resumen-360")), api(ruta(p.id, "/consentimiento-ia")).catch(() => null),
    api(`/api/clinica/pacientes/${p.id}/faltantes`).catch(() => null)]);
  const t = r.tratamiento_mas_reciente;
  const camposFaltantes = (r.campos_faltantes || []).map((c) => CAMPOS_FALTANTES[c] || c);
  const enlace = (s, texto) => h("a", { href: `#/pacientes/${p.id}/${s}` }, texto);
  return h("div", {},
    r.informacion_incompleta ? mensaje("aviso", "Información incompleta", `Falta: ${camposFaltantes.join(", ")}.`) : null,
    consentimiento && !consentimiento.ia_habilitada ? mensaje("aviso", "Las funciones de IA no se aplican a este paciente", consentimiento.motivo, " ",
      enlace("consentimiento", "Gestionar el consentimiento")) : null,
    h("div", { class: "rejilla" },
      tarjeta("Diagnóstico y tratamiento", listaDatos([
        ["Diagnóstico", r.diagnostico_principal || "Sin registrar"],
        ["Estadio", r.estadio || "Sin registrar"],
        ["Tratamiento", t ? h("span", {}, ESTADOS_TRATAMIENTO[t.estado] ? insignia(ESTADOS_TRATAMIENTO[t.estado]) : t.estado, " ", t.regimen || "", t.fecha_inicio ? h("span", { class: "tenue" }, ` · desde ${fecha(t.fecha_inicio)}`) : null) : "Sin tratamiento registrado"],
      ]), h("p", { class: "acciones" }, enlace("tratamiento", "Opciones de tratamiento"), enlace("estadificacion", "Estadificación"))),
      tarjeta("Alertas activas", lista(r.alertas_activas, "No hay alertas activas.", (al) =>
        h("div", { class: "alerta-item" },
          h("span", {}, h("strong", {}, TIPOS_ALERTA[al.tipo] || al.tipo), ": ", al.descripcion, " ", h("span", { class: "tenue" }, `(${fecha(al.fecha)})`)),
          SEVERIDADES[al.severidad] ? insignia(SEVERIDADES[al.severidad]) : null))),
      tarjeta("Biomarcadores clave", lista(r.biomarcadores_clave || [], "Sin biomarcadores accionables registrados.", (b) =>
        h("span", {}, h("strong", {}, b.biomarcador), `: ${b.resultado}`, b.terapia ? ` · ${b.terapia}` : "", " ",
          b.confirmado ? insignia({ texto: "Confirmado", tono: "ok", icono: "ok" }) : insignia({ texto: "Por confirmar", tono: "aviso", icono: "alerta" })))),
      faltantes ? tarjeta("¿Qué falta para decidir? (HC-05)",
        faltantes.faltantes.length ? lista(faltantes.faltantes.slice(0, 8), "", (f) => h("span", {}, h("strong", {}, f.descripcion), h("span", { class: "tenue" }, ` — ${f.motivo}`)))
          : mensaje("ok", null, "El expediente tiene la información necesaria para las fases evaluadas."),
        faltantes.faltantes.length > 8 ? h("p", { class: "tenue" }, `Y ${faltantes.faltantes.length - 8} más.`) : null) : null,
      tarjeta("Laboratorios recientes", lista(r.labs_recientes, "Sin laboratorios recientes.", acceso), h("p", {}, enlace("laboratorios", "Ver laboratorios y tendencias"))),
      tarjeta("Imágenes recientes", lista(r.imagenes_recientes, "Sin imágenes recientes.", acceso), h("p", {}, enlace("imagenes", "Ver estudios de imagen"))),
      tarjeta("Notas recientes", lista(r.notas_recientes, "Sin notas recientes.", acceso), h("p", {}, enlace("notas", "Notas de consulta con IA")))));
}

async function secLaboratorios(ctx, p) {
  const prueba = ctx.consulta.get("prueba");
  const [alertas, conflictos, marcadores, tendencia] = await Promise.all([
    api(ruta(p.id, "/alertas-laboratorio")), api(ruta(p.id, "/conflictos-laboratorio")), api(ruta(p.id, "/laboratorios/marcadores")),
    prueba ? api(ruta(p.id, "/laboratorios/tendencia"), { consulta: { prueba } }) : Promise.resolve(null),
  ]);
  const estado = h("div", { role: "status", "aria-live": "polite" });
  const bloqueAlertas = h("div", {});
  const bloqueConflictos = h("div", {});

  function pintarAlertas(items) {
    bloqueAlertas.replaceChildren(lista(items, "No hay alertas de laboratorio por revisar.", (al) =>
      h("div", { class: "alerta-item" },
        h("span", {}, h("strong", {}, al.prueba), `: ${al.valor}${al.unidad ? ` ${al.unidad}` : ""} — ${al.limite_superado} `, h("span", { class: "tenue" }, `(${fecha(al.fecha)})`)),
        h("span", { class: "acciones" },
          SEVERIDADES[al.severidad] ? insignia(SEVERIDADES[al.severidad]) : null,
          ctx.sesion.puede_revisar_alertas ? h("button", { type: "button", class: "btn sec chico", "aria-label": `Marcar como revisada la alerta de ${al.prueba} ${al.valor}`, onclick: async (e) => {
            e.target.disabled = true;
            try {
              await api(ruta(p.id, `/alertas-laboratorio/${al.id}/revisar`), { metodo: "POST", cuerpo: { revisada_por: ctx.sesion.usuario.nombre_usuario } });
              items = items.filter((x) => x.id !== al.id);
              pintarAlertas(items);
              estado.replaceChildren(mensaje("ok", null, `La alerta de ${al.prueba} quedó revisada por ${ctx.sesion.usuario.nombre_completo}.`));
              anunciar(`Alerta de ${al.prueba} revisada.`);
            } catch (err) {
              e.target.disabled = false;
              estado.replaceChildren(mensaje("error", "No se pudo marcar como revisada", err.mensajes[0]));
            }
          } }, "Marcar como revisada") : null))));
  }
  pintarAlertas(alertas);

  function pintarConflictos(items) {
    bloqueConflictos.replaceChildren(lista(items, "No hay resultados en conflicto.", (c) =>
      h("div", { class: "alerta-item" },
        h("span", {}, h("strong", {}, c.prueba), `: A = ${c.valor_a}${c.unidad_a ? ` ${c.unidad_a}` : ""} · B = ${c.valor_b}${c.unidad_b ? ` ${c.unidad_b}` : ""} (${c.momento})`),
        ctx.sesion.puede_registrar ? h("span", { class: "acciones" }, [["valido_a", "Vale A"], ["valido_b", "Vale B"], ["ambos_validos", "Ambos"], ["ninguno_valido", "Ninguno"]].map(([res, texto]) =>
          h("button", { type: "button", class: "btn sec chico", "aria-label": `${texto}: conflicto de ${c.prueba}`, onclick: async () => {
            try {
              await api(ruta(p.id, `/conflictos-laboratorio/${c.id}/resolver`), { metodo: "POST", cuerpo: { resolucion: res, resuelto_por: ctx.sesion.usuario.nombre_usuario } });
              items = items.filter((x) => x.id !== c.id);
              pintarConflictos(items);
              estado.replaceChildren(mensaje("ok", null, `Conflicto de ${c.prueba} resuelto (${texto}). Ningún resultado se borró.`));
            } catch (err) { estado.replaceChildren(mensaje("error", "No se pudo resolver el conflicto", err.mensajes[0])); }
          } }, texto))) : null)));
  }
  pintarConflictos(conflictos);

  const filasMarcadores = marcadores.map((m) => [
    h("a", { href: `#/pacientes/${p.id}/laboratorios?prueba=${encodeURIComponent(m.prueba)}`, "aria-label": `Ver tendencia de ${m.prueba}` }, m.prueba),
    `${m.ultimo_valor}${m.unidad ? ` ${m.unidad}` : ""}`, tiempo(m.ultima_fecha), String(m.cantidad)]);

  let focoTendencia = null;
  const tendenciaNodo = tendencia ? (() => {
    const titulo = h("h2", { tabindex: "-1" }, `Tendencia: ${tendencia.prueba}`);
    focoTendencia = titulo;
    return h("section", { class: "tarjeta" }, titulo,
      ...(tendencia.advertencias || []).map((a) => mensaje("aviso", null, a)),
      tendencia.series.length ? tendencia.series.map((s) => graficaDeSerie(tendencia.prueba, s)) : vacio("No hay resultados de este marcador."),
      h("p", {}, h("a", { href: `#/pacientes/${p.id}/laboratorios` }, "Cerrar tendencia")));
  })() : null;

  const registro = ctx.sesion.puede_registrar ? h("details", { class: "tarjeta" }, h("summary", {}, "Registrar un resultado de laboratorio (HC-02)"),
    h("p", { class: "tenue" }, "Doble validación: la identificación y el nombre de la orden deben coincidir con el paciente."),
    formulario({ columnas: true, textoBoton: "Guardar resultado", campos: [
      campo({ nombre: "identificacion", etiqueta: "Identificación en la orden", requerido: true, valor: String(p.numero_identificacion).split(":").pop() }),
      campo({ nombre: "nombre", etiqueta: "Nombre en la orden", requerido: true, valor: p.nombre_completo }),
      campo({ nombre: "prueba", etiqueta: "Prueba", requerido: true, ayuda: "Por ejemplo: Hemoglobina, CEA, Potasio" }),
      campo({ nombre: "valor", etiqueta: "Valor", requerido: true }),
      campo({ nombre: "unidad", etiqueta: "Unidad" }),
      campo({ nombre: "fecha", etiqueta: "Fecha", tipo: "date", requerido: true }),
      campo({ nombre: "hora", etiqueta: "Hora", tipo: "time" }),
    ], enviar: (v) => api(ruta(p.id, "/laboratorios"), { metodo: "POST", cuerpo: { ...v, unidad: v.unidad || null, hora: v.hora || null } }),
    alExito: (r) => {
      estado.replaceChildren(mensaje(r.alerta ? "aviso" : "ok", r.alerta ? "Resultado guardado con alerta crítica" : "Resultado guardado",
        r.alerta ? `${r.alerta.prueba}: ${r.alerta.limite_superado}.` : "Ya aparece en la tendencia.", r.conflictos && r.conflictos.length ? " Quedó en conflicto con otro resultado del mismo momento." : ""));
      window.setTimeout(() => window.dispatchEvent(new HashChangeEvent("hashchange")), 1200);
    } })) : null;

  return { nodo: h("div", {}, estado,
    tarjeta("Alertas por valores críticos", bloqueAlertas),
    tarjeta("Resultados en conflicto", h("p", { class: "tenue" }, "Dos resultados del mismo marcador y momento con valores distintos: decide cuál es válido antes de confiar en la tendencia."), bloqueConflictos),
    tendenciaNodo,
    marcadores.length ? tabla("Marcadores con resultados (el más reciente primero)", ["Marcador", "Último valor", "Fecha", "Resultados"], filasMarcadores, { filaEncabezado: true, numericas: [3] })
      : tarjeta("Marcadores", vacio("Este paciente aún no tiene resultados de laboratorio en el expediente.")),
    registro), foco: focoTendencia };
}

async function secImagenes(ctx, p) {
  const [vista, consultas] = await Promise.all([api(ruta(p.id, "/imagenes")), api(ruta(p.id, "/imagenes/consultas")).catch(() => [])]);
  const estado = h("div", { role: "status", "aria-live": "polite" });
  const filas = vista.estudios.map((e) => [
    tiempo(e.fecha), `${e.modalidad || "—"}`, e.descripcion || "—", `${e.series ?? "—"} series · ${e.instancias ?? "—"} imágenes`,
    e.informe ? h("details", {}, h("summary", {}, "Ver informe"), h("p", {}, e.informe.texto)) : h("span", { class: "tenue" }, "Sin informe"),
    h("button", { type: "button", class: "btn sec chico", "aria-label": `Abrir en el visor el estudio ${e.modalidad || ""} del ${fecha(e.fecha)}`, onclick: async () => {
      estado.replaceChildren(h("p", { class: "tenue" }, "Abriendo el visor…"));
      try {
        const v = await api(ruta(p.id, `/imagenes/${encodeURIComponent(e.study_uid)}/visor`));
        const enlace = h("a", { href: v.url, target: "_blank", rel: "noopener noreferrer" }, "Abrir el visor (se abre en una pestaña nueva)");
        estado.replaceChildren(mensaje("ok", null, v.mensaje, " ", enlace));
        window.open(v.url, "_blank", "noopener,noreferrer");
      } catch (err) {
        estado.replaceChildren(mensaje("aviso", "El visor no está disponible", err.mensajes[0]));
      }
    } }, "Abrir en el visor"),
  ]);
  return h("div", {},
    !vista.integracion_disponible ? mensaje("aviso", "No se pudo consultar el PACS", vista.mensaje || "La integración con el PACS no está disponible.",
      vista.desde_indice_local ? " Se muestran los estudios que ya estaban indexados." : "") : (vista.mensaje ? mensaje("info", null, vista.mensaje) : null),
    estado,
    vista.estudios.length ? tabla("Estudios de imagen del PACS", ["Fecha", "Modalidad", "Descripción", "Contenido", "Informe", "Visor"], filas)
      : tarjeta("Estudios de imagen", vacio("No hay estudios de imagen del PACS para este paciente.")),
    vista.informes_sin_estudio.length ? tarjeta("Informes de imagen del expediente", lista(vista.informes_sin_estudio, "", (i) =>
      h("span", {}, tiempo(i.fecha), " · ", h("strong", {}, `${i.modalidad} — ${i.region}`), ": ", i.texto))) : null,
    consultas.length ? h("details", { class: "tarjeta" }, h("summary", {}, "Bitácora de consultas al PACS"),
      tabla("Intentos de consulta al PACS", ["Fecha", "Tipo", "Resultado", "Estudios", "Detalle"], consultas.map((c) => [fecha((c.fecha || "").slice(0, 10)), c.tipo, c.estado, String(c.estudios), c.mensaje || "—"]), { numericas: [3] })) : null);
}

async function secBiomarcadores(ctx, p) {
  const [bios, biopsias, episodios] = await Promise.all([api(ruta(p.id, "/biomarcadores")), api(ruta(p.id, "/biopsias")), api(ruta(p.id, "/episodios"))]);
  const estado = h("div", { role: "status", "aria-live": "polite" });
  const acciones = (b) => {
    if (!ctx.sesion.puede_registrar || b.relevancia !== "pendiente_confirmacion") return "—";
    return h("span", { class: "acciones" },
      h("button", { type: "button", class: "btn chico", "aria-label": `Confirmar ${b.biomarcador}`, onclick: async () => {
        try {
          await api(ruta(p.id, `/biomarcadores/${b.id}/confirmar`), { metodo: "POST", cuerpo: { confirmado_por: ctx.sesion.usuario.nombre_usuario, confirmacion: b.resultado } });
          estado.replaceChildren(mensaje("ok", null, `${b.biomarcador} confirmado: ya es insumo de las recomendaciones de tratamiento.`));
          window.setTimeout(() => window.dispatchEvent(new HashChangeEvent("hashchange")), 1200);
        } catch (err) { estado.replaceChildren(mensaje("error", `No se pudo confirmar ${b.biomarcador}`, err.mensajes[0])); }
      } }, "Confirmar"),
      h("button", { type: "button", class: "btn sec chico", "aria-label": `Descartar ${b.biomarcador}`, onclick: async () => {
        try {
          await api(ruta(p.id, `/biomarcadores/${b.id}/descartar`), { metodo: "POST", cuerpo: { revisado_por: ctx.sesion.usuario.nombre_usuario } });
          estado.replaceChildren(mensaje("ok", null, `${b.biomarcador} descartado (queda en el historial).`));
          window.setTimeout(() => window.dispatchEvent(new HashChangeEvent("hashchange")), 1200);
        } catch (err) { estado.replaceChildren(mensaje("error", `No se pudo descartar ${b.biomarcador}`, err.mensajes[0])); }
      } }, "Descartar"));
  };
  return h("div", {}, estado,
    bios.length ? tabla("Biomarcadores", ["Fecha", "Biomarcador", "Resultado", "Relevancia", "Terapia asociada", "Revisión"], bios.map((b) => [
      tiempo(b.fecha), b.biomarcador, `${b.resultado}${b.metodo ? ` (${b.metodo})` : ""}`,
      RELEVANCIA_BIOMARCADOR[b.relevancia] ? insignia(RELEVANCIA_BIOMARCADOR[b.relevancia]) : b.relevancia, b.terapia_asociada || "—", acciones(b)]))
      : tarjeta("Biomarcadores", vacio("Sin biomarcadores registrados.")),
    biopsias.length ? tabla("Biopsias", ["Fecha", "Sitio", "Procedimiento", "Diagnóstico histológico"], biopsias.map((b) => [tiempo(b.fecha), b.sitio, b.procedimiento, b.diagnostico_histologico || "—"]))
      : tarjeta("Biopsias", vacio("Sin biopsias registradas.")),
    episodios.length ? tabla("Episodios diagnósticos", ["Fecha", "Descripción", "Tipo de cáncer", "Origen"], episodios.map((e) => [tiempo(e.fecha_diagnostico), e.descripcion, e.tipo_cancer || "—", e.origen]))
      : null);
}

async function secHistoria(ctx, p) {
  const [dx, tx, consultas, externa] = await Promise.all([api(ruta(p.id, "/diagnosticos")), api(ruta(p.id, "/tratamientos")), api(ruta(p.id, "/consultas")),
    api(`/api/clinica/pacientes/${p.id}/historia-externa`).catch(() => ({ sincronizaciones: [], antecedentes: [] }))]);
  return h("div", {},
    dx.length ? tabla("Diagnósticos", ["Fecha", "Descripción", "Estadio"], dx.map((d) => [tiempo(d.fecha), d.descripcion, d.estadio || "—"])) : tarjeta("Diagnósticos", vacio("Sin diagnósticos registrados.")),
    tx.length ? tabla("Tratamientos", ["Inicio", "Estado", "Régimen"], tx.map((t) => [tiempo(t.fecha_inicio), ESTADOS_TRATAMIENTO[t.estado] ? insignia(ESTADOS_TRATAMIENTO[t.estado]) : t.estado, t.regimen || "—"])) : tarjeta("Tratamientos", vacio("Sin tratamientos registrados.")),
    consultas.length ? tabla("Consultas", ["Fecha", "Nota"], consultas.map((c) => [tiempo(c.fecha), c.nota || "—"])) : null,
    externa.antecedentes.length ? tabla("Antecedentes importados de fuentes externas (HC-01)", ["Fecha", "Tipo", "Descripción", "Fuente"],
      externa.antecedentes.map((a) => [tiempo(a.fecha), a.tipo, a.descripcion, a.fuente])) : null,
    externa.sincronizaciones.length ? tarjeta("Sincronizaciones con fuentes externas", lista(externa.sincronizaciones, "", (s) =>
      h("span", {}, tiempo((s.fecha || "").slice(0, 10)), " · ", h("strong", {}, `${s.fuente} (${s.formato})`), ` — ${s.estado}: ${s.mensaje || ""}`))) : null);
}

const CARGADORES = {
  resumen: secResumen, historia: secHistoria, laboratorios: secLaboratorios, imagenes: secImagenes, biomarcadores: secBiomarcadores,
  documentos: secDocumentos, "linea-tiempo": secLineaTiempo,
  asistente: secAsistente, notas: secNotas, junta: secJunta,
  diagnostico: secDiagnostico, estadificacion: secEstadificacion, tratamiento: secTratamiento, evidencia: secEvidencia,
  consentimiento: secConsentimiento,
};

/* ---------------- Vista ---------------- */

export async function vistaExpediente(ctx) {
  const { id, seccion = "resumen" } = ctx.parametros;
  if (!CARGADORES[seccion]) return { titulo: "No encontrado", nodo: h("div", {}, h("h1", {}, "Sección no encontrada"), h("p", {}, h("a", { href: `#/pacientes/${id}` }, "Volver al expediente"))) };
  let paciente;
  try {
    paciente = await api(ruta(id));
  } catch (err) {
    if (err.estado === 404) {
      return { titulo: "Paciente no encontrado", nodo: h("div", {}, h("h1", {}, "Paciente no encontrado"),
        mensaje("aviso", null, "No encontramos a ese paciente entre los que atiendes."), h("p", {}, h("a", { href: "#/pacientes" }, "Volver a la lista de pacientes"))) };
    }
    throw err;
  }
  const consentimiento = await api(ruta(id, "/consentimiento-ia")).catch(() => null);
  const cuerpo = h("div", {}, cargando("Cargando…"));
  const nombreSeccion = (SECCIONES.find(([c]) => c === seccion) || [])[1];
  async function cargar() {
    cuerpo.replaceChildren(h("h2", { class: "vh" }, nombreSeccion), cargando());
    try {
      const r = await CARGADORES[seccion](ctx, paciente, consentimiento);
      const nodo = r instanceof Node ? r : r.nodo;
      cuerpo.replaceChildren(nodo);
      if (!(r instanceof Node) && r.foco) { r.foco.focus(); anunciar(r.foco.textContent); }
    } catch (err) {
      cuerpo.replaceChildren(errorConReintento(err, cargar));
    }
  }
  return { titulo: `${paciente.nombre_completo} — ${nombreSeccion}`, nodo: marco(ctx, paciente, consentimiento, seccion, cuerpo), alMostrar: cargar };
}
