import { h, anunciar } from "./dom.js";
import { api, descargar } from "./api.js";
import { CAMPOS_FALTANTES, ESTADOS_TRATAMIENTO, RELEVANCIA_BIOMARCADOR, SEVERIDADES, SEXOS, TIPOS_ALERTA, edad, fecha } from "./formato.js";
import { graficaDeSerie } from "./grafica.js";
import { cargando, errorConReintento, insignia, listaDatos, mensaje, tabla } from "./ui.js";

const SECCIONES = [
  ["resumen", "Resumen"],
  ["laboratorios", "Laboratorios"],
  ["imagenes", "Imágenes"],
  ["biomarcadores", "Biomarcadores"],
  ["historia", "Historia clínica"],
];

const vacio = (texto) => h("p", { class: "tenue" }, texto);
const tiempo = (iso) => (iso ? h("time", { datetime: iso }, fecha(iso)) : "—");
const acceso = (x) => h("span", {}, tiempo(x.fecha), " · ", x.titulo ? h("strong", {}, `${x.titulo}: `) : null, x.resumen);
const ruta = (id, sufijo = "") => `/api/pacientes/${id}${sufijo}`;

function tarjeta(titulo, ...cuerpo) {
  return h("section", { class: "tarjeta" }, h("h2", {}, titulo), ...cuerpo);
}

function lista(items, vacioTexto, pintar) {
  if (!items.length) return vacio(vacioTexto);
  return h("ul", { class: "lista-limpia" }, items.map((x) => h("li", {}, pintar(x))));
}

/* ---------------- Marco común: cabecera de la ficha, exportación y navegación por secciones ---------------- */

function marco(ctx, paciente, seccion, contenido) {
  const a = edad(paciente.fecha_nacimiento);
  const estado = h("div", { id: "estado-ficha", role: "status", "aria-live": "polite" });
  const botones = [];
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
    botones.push(exportar("html", "Exportar expediente (HTML accesible)"), exportar("pdf", "Exportar expediente (PDF)"));
  }
  return h("div", {},
    h("p", { class: "migas" }, h("a", { href: "#/pacientes" }, "Pacientes"), " / ", paciente.nombre_completo),
    h("div", { class: "ficha-cabecera" },
      h("div", {},
        h("h1", {}, paciente.nombre_completo),
        h("p", { class: "sub" }, [a === null ? null : `${a} años`, SEXOS[paciente.sexo] || paciente.sexo, `Identificación ${paciente.numero_identificacion}`].filter(Boolean).join(" · "))),
      botones.length ? h("div", { class: "acciones" }, botones) : null),
    estado,
    h("nav", { class: "secciones", "aria-label": "Secciones del expediente" },
      h("ul", {}, SECCIONES.map(([clave, texto]) =>
        h("li", {}, h("a", { href: `#/pacientes/${paciente.id}${clave === "resumen" ? "" : `/${clave}`}`, "aria-current": clave === seccion ? "page" : null }, texto))))),
    contenido);
}

/* ---------------- Secciones ---------------- */

async function secResumen(ctx, p) {
  const [r, consentimiento] = await Promise.all([api(ruta(p.id, "/resumen-360")), api(ruta(p.id, "/consentimiento-ia")).catch(() => null)]);
  const t = r.tratamiento_mas_reciente;
  const faltantes = (r.campos_faltantes || []).map((c) => CAMPOS_FALTANTES[c] || c);
  return h("div", {},
    r.informacion_incompleta ? mensaje("aviso", "Información incompleta", `Falta: ${faltantes.join(", ")}. Complétala en el expediente para que el resumen sea confiable.`) : null,
    h("div", { class: "rejilla" },
      tarjeta("Diagnóstico y tratamiento", listaDatos([
        ["Diagnóstico", r.diagnostico_principal || "Sin registrar"],
        ["Estadio", r.estadio || "Sin registrar"],
        ["Tratamiento", t ? h("span", {}, ESTADOS_TRATAMIENTO[t.estado] ? insignia(ESTADOS_TRATAMIENTO[t.estado]) : t.estado, " ", t.regimen || "", t.fecha_inicio ? h("span", { class: "tenue" }, ` · desde ${fecha(t.fecha_inicio)}`) : null) : "Sin tratamiento registrado"],
      ])),
      tarjeta("Alertas activas", lista(r.alertas_activas, "No hay alertas activas.", (al) =>
        h("div", { class: "alerta-item" },
          h("span", {}, h("strong", {}, TIPOS_ALERTA[al.tipo] || al.tipo), ": ", al.descripcion, " ", h("span", { class: "tenue" }, `(${fecha(al.fecha)})`)),
          SEVERIDADES[al.severidad] ? insignia(SEVERIDADES[al.severidad]) : null))),
      tarjeta("Biomarcadores clave", lista(r.biomarcadores_clave || [], "Sin biomarcadores accionables registrados.", (b) =>
        h("span", {}, h("strong", {}, b.biomarcador), `: ${b.resultado}`, b.terapia ? ` · ${b.terapia}` : "", " ",
          b.confirmado ? insignia({ texto: "Confirmado", tono: "ok", icono: "ok" }) : insignia({ texto: "Por confirmar", tono: "aviso", icono: "alerta" })))),
      tarjeta("Laboratorios recientes", lista(r.labs_recientes, "Sin laboratorios recientes.", acceso),
        h("p", {}, h("a", { href: `#/pacientes/${p.id}/laboratorios` }, "Ver laboratorios y tendencias"))),
      tarjeta("Imágenes recientes", lista(r.imagenes_recientes, "Sin imágenes recientes.", acceso),
        h("p", {}, h("a", { href: `#/pacientes/${p.id}/imagenes` }, "Ver estudios de imagen"))),
      tarjeta("Notas recientes", lista(r.notas_recientes, "Sin notas recientes.", acceso)),
      consentimiento ? tarjeta("Uso de inteligencia artificial", listaDatos([
        ["Consentimiento", consentimiento.estado],
        ["IA habilitada", consentimiento.ia_habilitada ? "Sí" : "No"],
        ["Detalle", consentimiento.motivo],
      ])) : null));
}

async function secLaboratorios(ctx, p) {
  const prueba = ctx.consulta.get("prueba");
  const [alertas, conflictos, marcadores, tendencia] = await Promise.all([
    api(ruta(p.id, "/alertas-laboratorio")), api(ruta(p.id, "/conflictos-laboratorio")), api(ruta(p.id, "/laboratorios/marcadores")),
    prueba ? api(ruta(p.id, "/laboratorios/tendencia"), { consulta: { prueba } }) : Promise.resolve(null),
  ]);
  const estado = h("div", { role: "status", "aria-live": "polite" });
  const bloqueAlertas = h("div", {});

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

  return { nodo: h("div", {}, estado,
    tarjeta("Alertas por valores críticos", bloqueAlertas),
    conflictos.length ? tarjeta("Resultados en conflicto",
      h("p", { class: "tenue" }, "Dos resultados del mismo marcador y momento con valores distintos. Hay que decidir cuál es válido antes de confiar en la tendencia."),
      lista(conflictos, "", (c) => h("span", {}, h("strong", {}, c.prueba), `: ${c.valor_a}${c.unidad_a ? ` ${c.unidad_a}` : ""} frente a ${c.valor_b}${c.unidad_b ? ` ${c.unidad_b}` : ""} (${c.momento})`))) : null,
    tendenciaNodo,
    marcadores.length ? tabla("Marcadores con resultados (el más reciente primero)", ["Marcador", "Último valor", "Fecha", "Resultados"], filasMarcadores, { filaEncabezado: true, numericas: [3] })
      : tarjeta("Marcadores", vacio("Este paciente aún no tiene resultados de laboratorio en el expediente."))), foco: focoTendencia };
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
      : tarjeta("Estudios de imagen", vacio("No hay estudios de imagen para este paciente.")),
    vista.informes_sin_estudio.length ? tarjeta("Informes sin estudio en el PACS", lista(vista.informes_sin_estudio, "", (i) =>
      h("span", {}, tiempo(i.fecha), " · ", h("strong", {}, `${i.modalidad} — ${i.region}`), ": ", i.texto))) : null,
    consultas.length ? h("details", { class: "tarjeta" }, h("summary", {}, "Bitácora de consultas al PACS"),
      tabla("Intentos de consulta al PACS", ["Fecha", "Tipo", "Resultado", "Estudios", "Detalle"], consultas.map((c) => [fecha((c.fecha || "").slice(0, 10)), c.tipo, c.estado, String(c.estudios), c.mensaje || "—"]), { numericas: [3] })) : null);
}

async function secBiomarcadores(ctx, p) {
  const [bios, biopsias, episodios] = await Promise.all([api(ruta(p.id, "/biomarcadores")), api(ruta(p.id, "/biopsias")), api(ruta(p.id, "/episodios"))]);
  return h("div", {},
    bios.length ? tabla("Biomarcadores", ["Fecha", "Biomarcador", "Resultado", "Relevancia", "Terapia asociada"], bios.map((b) => [
      tiempo(b.fecha), b.biomarcador, `${b.resultado}${b.metodo ? ` (${b.metodo})` : ""}`,
      RELEVANCIA_BIOMARCADOR[b.relevancia] ? insignia(RELEVANCIA_BIOMARCADOR[b.relevancia]) : b.relevancia, b.terapia_asociada || "—"]), { filaEncabezado: false })
      : tarjeta("Biomarcadores", vacio("Sin biomarcadores registrados.")),
    biopsias.length ? tabla("Biopsias", ["Fecha", "Sitio", "Procedimiento", "Diagnóstico histológico"], biopsias.map((b) => [tiempo(b.fecha), b.sitio, b.procedimiento, b.diagnostico_histologico || "—"]))
      : tarjeta("Biopsias", vacio("Sin biopsias registradas.")),
    episodios.length ? tabla("Episodios diagnósticos", ["Fecha", "Descripción", "Tipo de cáncer", "Origen"], episodios.map((e) => [tiempo(e.fecha_diagnostico), e.descripcion, e.tipo_cancer || "—", e.origen]))
      : null);
}

async function secHistoria(ctx, p) {
  const [dx, tx, consultas] = await Promise.all([api(ruta(p.id, "/diagnosticos")), api(ruta(p.id, "/tratamientos")), api(ruta(p.id, "/consultas"))]);
  return h("div", {},
    dx.length ? tabla("Diagnósticos", ["Fecha", "Descripción", "Estadio"], dx.map((d) => [tiempo(d.fecha), d.descripcion, d.estadio || "—"])) : tarjeta("Diagnósticos", vacio("Sin diagnósticos registrados.")),
    tx.length ? tabla("Tratamientos", ["Inicio", "Estado", "Régimen"], tx.map((t) => [tiempo(t.fecha_inicio), ESTADOS_TRATAMIENTO[t.estado] ? insignia(ESTADOS_TRATAMIENTO[t.estado]) : t.estado, t.regimen || "—"])) : tarjeta("Tratamientos", vacio("Sin tratamientos registrados.")),
    consultas.length ? tabla("Consultas", ["Fecha", "Nota"], consultas.map((c) => [tiempo(c.fecha), c.nota || "—"])) : tarjeta("Consultas", vacio("Sin consultas registradas.")));
}

const CARGADORES = { resumen: secResumen, laboratorios: secLaboratorios, imagenes: secImagenes, biomarcadores: secBiomarcadores, historia: secHistoria };

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
  const cuerpo = h("div", {}, cargando("Cargando…"));
  const nombreSeccion = (SECCIONES.find(([c]) => c === seccion) || [])[1];
  async function cargar() {
    cuerpo.replaceChildren(cargando());
    try {
      const r = await CARGADORES[seccion](ctx, paciente);
      const nodo = r instanceof Node ? r : r.nodo;
      cuerpo.replaceChildren(nodo);
      if (!(r instanceof Node) && r.foco) { r.foco.focus(); anunciar(r.foco.textContent); }
    } catch (err) {
      cuerpo.replaceChildren(errorConReintento(err, cargar));
    }
  }
  return { titulo: `${paciente.nombre_completo} — ${nombreSeccion}`, nodo: marco(ctx, paciente, seccion, cuerpo), alMostrar: cargar };
}
