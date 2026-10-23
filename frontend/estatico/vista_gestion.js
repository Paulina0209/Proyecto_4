/* Pantallas de gestión, cada una para su rol: auditoría (AUD-01/02), usuarios (ADM-01), guías (CFG-01),
   privacidad y derechos del titular (NFR-06), estado del sistema (NFR-01/02) y notificaciones (CFG-02). */
import { h, anunciar, idUnico } from "./dom.js";
import { api, descargar } from "./api.js";
import { fecha, SEVERIDADES } from "./formato.js";
import { campo, cargando, casilla, errorConReintento, formulario, insignia, listaDatos, mensaje, tabla, tarjeta, vacio } from "./ui.js";

const sinPermiso = (titulo, texto) => ({ titulo, nodo: h("div", {}, h("h1", {}, titulo), mensaje("aviso", "Sin permiso", texto)) });
const recargar = () => window.dispatchEvent(new HashChangeEvent("hashchange"));

function pantalla(titulo, sub, cargar) {
  const cuerpo = h("div", {}, cargando());
  const intentar = async () => {
    cuerpo.replaceChildren(cargando());
    try { cuerpo.replaceChildren(await cargar()); } catch (err) { cuerpo.replaceChildren(errorConReintento(err, intentar)); }
  };
  return { titulo, nodo: h("div", {}, h("h1", {}, titulo), h("p", { class: "sub" }, sub), cuerpo), alMostrar: intentar };
}

/* ---------------- Auditoría ---------------- */

export async function vistaAuditoria(ctx) {
  if (!ctx.sesion.ver_auditoria) return sinPermiso("Auditoría", "Solo el rol de auditoría consulta los registros.");
  const paciente = ctx.consulta.get("paciente_id") || "";
  const usuario = ctx.consulta.get("usuario_id") || "";
  return pantalla("Auditoría", "Quién hizo qué y cuándo sobre cada expediente, y qué sugirió la IA frente a lo que decidió el médico. Los registros no se pueden modificar.", async () => {
    const r = await api("/api/gestion/auditoria", { consulta: { paciente_id: paciente, usuario_id: usuario } });
    const filtros = h("form", { class: "tarjeta filtros", role: "search", onsubmit: (e) => {
      e.preventDefault();
      const d = new FormData(e.target), p = new URLSearchParams();
      for (const k of ["paciente_id", "usuario_id"]) if (d.get(k)) p.set(k, d.get(k));
      window.location.hash = `#/auditoria${p.toString() ? `?${p}` : ""}`;
    } }, campo({ nombre: "paciente_id", etiqueta: "Paciente (id)", tipo: "number", valor: paciente }).nodo,
      campo({ nombre: "usuario_id", etiqueta: "Usuario (id)", tipo: "number", valor: usuario }).nodo,
      h("div", { class: "campo" }, h("button", { type: "submit", class: "btn" }, "Filtrar")));
    return h("div", {}, filtros,
      r.eventos.length ? tabla(`${r.eventos.length} eventos (los más recientes primero)`, ["Fecha", "Usuario", "Paciente", "Acción", "Detalle", "Base"],
        r.eventos.map((e) => [`${fecha(e.fecha.slice(0, 10))} ${e.fecha.slice(11, 19)}`, e.usuario, e.paciente_id ?? "—", e.accion, e.detalle || "—", e.origen]))
        : tarjeta("Eventos", vacio("No hay eventos con esos filtros.")),
      paciente ? (r.trazabilidad_ia.length ? tabla("Trazabilidad de la IA frente al médico", ["Dominio", "Sugerencia del sistema", "Decisión del médico", "¿Difiere?"],
        r.trazabilidad_ia.map((t) => [t.dominio, String(t.recomendacion_sistema || "—").slice(0, 160), String(t.decision_medico || "—").slice(0, 160),
          t.difiere_de_sugerencia ? insignia({ texto: "Sí", tono: "aviso", icono: "alerta" }) : insignia({ texto: "No", tono: "ok", icono: "ok" })]))
        : tarjeta("Trazabilidad de la IA frente al médico", vacio("Sin decisiones registradas para este paciente."))) : null);
  });
}

/* ---------------- Usuarios ---------------- */

export async function vistaUsuarios(ctx) {
  if (!ctx.sesion.gestionar_usuarios) return sinPermiso("Usuarios", "Solo el administrador del sistema gestiona usuarios.");
  return pantalla("Usuarios y roles", "Alta, cambio de rol y baja lógica. Nadie se borra: el historial se conserva. Enfermería y admisiones ven los pacientes de los oncólogos de su equipo.", async () => {
    const [r, eq] = await Promise.all([api("/api/gestion/usuarios"), api("/api/gestion/equipos")]);
    const nombreOncologo = Object.fromEntries(eq.oncologos.map((o) => [o.id, o.nombre]));
    const estado = h("div", { role: "status", "aria-live": "polite" });
    const opcionesRol = r.roles.map((x) => [x.valor, x.etiqueta]);
    const filas = r.usuarios.map((u) => {
      const selectorRol = h("select", { "aria-label": `Rol de ${u.nombre_usuario}` }, opcionesRol.map(([v, t]) => h("option", { value: v, selected: v === u.rol }, t)));
      const operar = async (operacion, cuerpo, texto) => {
        try {
          await api(`/api/gestion/usuarios/${u.id}/${operacion}`, { metodo: "POST", cuerpo });
          anunciar(texto); recargar();
        } catch (err) { estado.replaceChildren(mensaje("error", `No se pudo actualizar a ${u.nombre_usuario}`, err.mensajes[0])); }
      };
      const asignados = eq.asignaciones[String(u.id)];
      let columnaEquipo = h("span", { class: "tenue" }, "—");
      if (asignados) {
        const equipo = async (oncologo_id, retirar) => {
          try {
            await api(`/api/gestion/equipos/${u.id}`, { metodo: "POST", cuerpo: { oncologo_id, retirar } });
            anunciar(retirar ? "Oncólogo retirado del equipo." : "Oncólogo agregado al equipo."); recargar();
          } catch (err) { estado.replaceChildren(mensaje("error", `No se pudo actualizar el equipo de ${u.nombre_usuario}`, err.mensajes[0])); }
        };
        const libres = eq.oncologos.filter((o) => !asignados.includes(o.id));
        const selector = h("select", { "aria-label": `Agregar oncólogo al equipo de ${u.nombre_usuario}` }, libres.map((o) => h("option", { value: String(o.id) }, o.nombre)));
        columnaEquipo = h("div", { class: "equipo" },
          asignados.length ? h("ul", { class: "lista-limpia" }, asignados.map((id) => h("li", {}, nombreOncologo[id] || `Oncólogo ${id}`, " ",
            h("button", { type: "button", class: "btn sec chico", "aria-label": `Retirar a ${nombreOncologo[id]} del equipo de ${u.nombre_usuario}`, onclick: () => equipo(id, true) }, "Retirar"))))
            : insignia({ texto: "Sin equipo: no ve pacientes", tono: "aviso", icono: "alerta" }),
          libres.length ? h("span", { class: "acciones" }, selector, h("button", { type: "button", class: "btn sec chico", onclick: () => equipo(Number(selector.value), false) }, "Agregar")) : null);
      }
      return [u.nombre_usuario, u.nombre_completo || "—", selectorRol, columnaEquipo,
        u.activo ? insignia({ texto: "Activo", tono: "ok", icono: "ok" }) : insignia({ texto: "Inactivo", tono: "neutra", icono: "pausa" }),
        h("span", { class: "acciones" },
          h("button", { type: "button", class: "btn sec chico", onclick: () => operar("rol", { rol: selectorRol.value, motivo: "Cambio desde la interfaz de administración" }, "Rol actualizado.") }, "Guardar rol"),
          u.activo ? h("button", { type: "button", class: "btn peligro chico", onclick: () => operar("desactivar", { motivo: "Baja desde la interfaz de administración" }, "Usuario desactivado.") }, "Desactivar")
            : h("button", { type: "button", class: "btn sec chico", onclick: () => operar("reactivar", {}, "Usuario reactivado.") }, "Reactivar"))];
    });
    const alta = formulario({ columnas: true, textoBoton: "Crear usuario", campos: [
      campo({ nombre: "nombre_usuario", etiqueta: "Usuario", requerido: true }),
      campo({ nombre: "nombre_completo", etiqueta: "Nombre completo", requerido: true }),
      campo({ nombre: "correo", etiqueta: "Correo", tipo: "email" }),
      campo({ nombre: "rol", etiqueta: "Rol", tipo: "select", opciones: opcionesRol }),
      campo({ nombre: "contrasena", etiqueta: "Contraseña inicial", tipo: "password", requerido: true, ayuda: "Mínimo 10 caracteres, con letras y números." }),
    ], enviar: (v) => api("/api/gestion/usuarios", { metodo: "POST", cuerpo: v }), alExito: () => { anunciar("Usuario creado."); recargar(); } });
    return h("div", {}, estado,
      tabla(`${r.usuarios.length} usuarios`, ["Usuario", "Nombre", "Rol", "Equipo de atención", "Estado", "Acciones"], filas, { filaEncabezado: true }),
      h("details", { class: "tarjeta" }, h("summary", {}, "Crear un usuario"), alta));
  });
}

/* ---------------- Guías institucionales ---------------- */

export async function vistaGuias(ctx) {
  if (!ctx.sesion.acceso_clinico && !ctx.sesion.configurar_guias) return sinPermiso("Guías clínicas", "Las guías las consulta oncología y las configura la administración clínica.");
  return pantalla("Guías clínicas institucionales", "Qué guías usa la institución por defecto para la evidencia y las recomendaciones.", async () => {
    const r = await api("/api/gestion/guias");
    const v = r.vigente;
    const config = r.puede_configurar ? formulario({ textoBoton: "Publicar nueva versión", campos: [
      campo({ nombre: "organizaciones", etiqueta: "Organizaciones, en orden de prioridad", valor: v.organizaciones.join(", "), ayuda: `Disponibles: ${r.organizaciones_disponibles.join(", ")}. Separadas por coma.` }),
      campo({ nombre: "motivo", etiqueta: "Motivo del cambio", requerido: true, ayuda: "Por ejemplo: acta del comité de oncología." }),
      campo({ nombre: "protocolo_nombre", etiqueta: "Protocolo interno (opcional)" }),
      campo({ nombre: "protocolo_codigo", etiqueta: "Referencia del protocolo" }),
    ], enviar: (x) => api("/api/gestion/guias", { metodo: "POST", cuerpo: { ...x, organizaciones: x.organizaciones.split(",").map((o) => o.trim()).filter(Boolean) } }),
    alExito: () => { anunciar("Nueva versión publicada."); recargar(); } }) : null;
    return h("div", {},
      tarjeta("Configuración vigente", listaDatos([
        ["Versión", v.version ? `v${v.version}` : "Por defecto del sistema (sin configurar)"],
        ["Organizaciones", v.organizaciones.join(" > ")],
        ["Protocolo interno", v.protocolo_interno ? `${v.protocolo_interno.nombre} (${v.protocolo_interno.referencia})` : "—"],
        ["Módulos de guía habilitados", String(v.modulos_habilitados.length)],
        ["Configurada", v.fecha ? `${fecha(v.fecha.slice(0, 10))} · ${v.motivo}` : "—"],
      ]), ...(v.advertencias || []).map((a) => mensaje("aviso", null, a))),
      config ? tarjeta("Cambiar la configuración", config) : mensaje("info", null, "Solo la administración clínica puede cambiar las guías."),
      r.historial.length ? tabla("Historial de versiones", ["Versión", "Organizaciones", "Motivo", "Fecha"], r.historial.map((x) => [`v${x.version}`, x.organizaciones.join(" > "), x.motivo || "—", fecha((x.fecha || "").slice(0, 10))])) : null);
  });
}

/* ---------------- Privacidad y derechos del titular (NFR-06) ---------------- */

const ETIQUETA_ESTADO = { recibida: "Recibida", en_tramite: "En trámite", atendida: "Atendida", rechazada: "Rechazada" };
const lista = (texto) => String(texto || "").split(",").map((x) => x.trim()).filter(Boolean);

export async function vistaPrivacidad(ctx) {
  if (!ctx.sesion.configurar_privacidad) return sinPermiso("Privacidad", "Las políticas de datos y las solicitudes de derechos las gestiona la administración clínica.");
  return pantalla("Privacidad y derechos del titular", "Políticas de tratamiento de datos de la institución, con su finalidad y base legal, y solicitudes de los pacientes sobre sus datos. Todo queda en la auditoría.", async () => {
    const r = await api("/api/gestion/privacidad");
    const politicas = r.politicas || [];
    const estado = h("div", { role: "status", "aria-live": "polite" });

    const filasPoliticas = politicas.map((p) => [`${p.nombre} (v${p.version})`, p.jurisdiccion, p.marco_normativo || "—",
      p.finalidades.map((f) => f.codigo).join(", "), p.derechos.join(", "), `${p.plazo_respuesta_dias} días`]);
    const nuevaPolitica = formulario({ columnas: true, textoBoton: "Publicar política", campos: [
      campo({ nombre: "codigo", etiqueta: "Código", requerido: true, ayuda: "Minúsculas, sin espacios. Si ya existe, se publica una nueva versión." }),
      campo({ nombre: "nombre", etiqueta: "Nombre", requerido: true }),
      campo({ nombre: "jurisdiccion", etiqueta: "Jurisdicción", requerido: true, valor: "CO" }),
      campo({ nombre: "marco_normativo", etiqueta: "Marco normativo", valor: "Ley 1581 de 2012" }),
      campo({ nombre: "finalidades", etiqueta: "Finalidades", requerido: true, valor: "atencion_clinica, asistencia_ia", ayuda: "Separadas por coma." }),
      campo({ nombre: "bases_legales", etiqueta: "Bases legales", requerido: true, valor: "consentimiento_informado" }),
      campo({ nombre: "derechos", etiqueta: "Derechos que reconoce", requerido: true, valor: "acceso, rectificacion, supresion, revocatoria" }),
      campo({ nombre: "plazo_respuesta_dias", etiqueta: "Plazo de respuesta (días)", tipo: "number", requerido: true, valor: "15" }),
    ], enviar: (v) => api("/api/gestion/privacidad/politicas", { metodo: "POST", cuerpo: { ...v, finalidades: lista(v.finalidades),
      bases_legales: lista(v.bases_legales), derechos: lista(v.derechos), plazo_respuesta_dias: Number(v.plazo_respuesta_dias) } }),
    alExito: () => { anunciar("Política publicada."); recargar(); } });

    const nuevaSolicitud = politicas.length ? formulario({ columnas: true, textoBoton: "Registrar solicitud", campos: [
      campo({ nombre: "identificacion", etiqueta: "Identificación del titular", requerido: true, ayuda: "Documento o id de cBioPortal (p. ej. P-0000057)." }),
      campo({ nombre: "codigo_politica", etiqueta: "Política", tipo: "select", opciones: politicas.map((p) => [p.codigo, `${p.nombre} (v${p.version})`]) }),
      campo({ nombre: "tipo_derecho", etiqueta: "Derecho", tipo: "select", opciones: [...new Set(politicas.flatMap((p) => p.derechos))].map((d) => [d, d]) }),
      campo({ nombre: "solicitante", etiqueta: "Quién la presenta", requerido: true, ayuda: "El titular o su representante." }),
      campo({ nombre: "descripcion", etiqueta: "Qué pide", tipo: "textarea", requerido: true }),
    ], enviar: (v) => api("/api/gestion/privacidad/solicitudes", { metodo: "POST", cuerpo: v }),
    alExito: () => { anunciar("Solicitud registrada."); recargar(); } }) : mensaje("aviso", null, "Primero publica una política: de ella sale el plazo de respuesta.");

    const avanzar = (s, estadoNuevo) => h("button", { type: "button", class: "btn sec chico", onclick: async () => {
      const detalle = estadoNuevo === "en_tramite" ? null : window.prompt(estadoNuevo === "atendida" ? "¿Cómo se atendió?" : "Motivo del rechazo");
      if (estadoNuevo !== "en_tramite" && !detalle) return;
      try {
        await api(`/api/gestion/privacidad/solicitudes/${s.id}/estado`, { metodo: "POST", cuerpo: { estado: estadoNuevo, detalle } });
        anunciar("Solicitud actualizada."); recargar();
      } catch (err) { estado.replaceChildren(mensaje("error", "No se pudo actualizar", err.mensajes[0])); }
    } }, ETIQUETA_ESTADO[estadoNuevo]);
    const informacion = (s) => h("button", { type: "button", class: "btn sec chico", onclick: async () => {
      try { await descargar(`/api/gestion/privacidad/solicitudes/${s.id}/informacion`); anunciar("Información del titular descargada."); }
      catch (err) { estado.replaceChildren(mensaje("error", "No se pudo descargar", err.mensajes[0])); }
    } }, "Descargar su información");
    const filasAbiertas = (r.abiertas || []).map((s) => [s.identificacion || `#${s.paciente_id}`, s.tipo_derecho, s.solicitante,
      `${fecha(s.fecha_limite.slice(0, 10))}${s.vencida ? " (vencida)" : ""}`,
      insignia({ texto: ETIQUETA_ESTADO[s.estado] || s.estado, tono: s.vencida ? "crit" : "info", icono: s.vencida ? "alerta" : "info" }),
      h("div", { class: "acciones" }, s.estado === "recibida" ? avanzar(s, "en_tramite") : null, avanzar(s, "atendida"), avanzar(s, "rechazada"), informacion(s))]);

    return h("div", {}, estado,
      filasPoliticas.length ? tabla("Políticas vigentes", ["Política", "Jurisdicción", "Marco normativo", "Finalidades", "Derechos", "Plazo"], filasPoliticas, { filaEncabezado: true })
        : vacio("La institución todavía no ha publicado políticas de tratamiento de datos."),
      h("details", { class: "tarjeta" }, h("summary", {}, "Publicar una política o una nueva versión"), nuevaPolitica),
      filasAbiertas.length ? tabla("Solicitudes abiertas (la que vence primero arriba)", ["Titular", "Derecho", "Solicitante", "Vence", "Estado", "Acciones"], filasAbiertas, { filaEncabezado: true })
        : vacio("No hay solicitudes de derechos abiertas."),
      tarjeta("Registrar una solicitud de derechos", nuevaSolicitud),
      (r.recientes || []).length ? tabla("Últimas solicitudes", ["#", "Titular", "Derecho", "Recibida", "Estado"], r.recientes.map((x) => [String(x.id), x.identificacion || "—", x.tipo_derecho, fecha((x.fecha_recepcion || "").slice(0, 10)), ETIQUETA_ESTADO[x.estado] || x.estado || "—"])) : null);
  });
}

/* ---------------- Estado del sistema ---------------- */

const TONOS = { ok: { texto: "Bien", tono: "ok", icono: "ok" }, degradado: { texto: "Degradado", tono: "aviso", icono: "alerta" }, falla: { texto: "Falla", tono: "crit", icono: "alerta" } };

export async function vistaSistema(ctx) {
  if (!ctx.sesion.ver_estado_sistema) return sinPermiso("Estado del sistema", "Solo el administrador del sistema ve el estado de la plataforma.");
  return pantalla("Estado del sistema", "Disponibilidad y tiempos de respuesta por ruta de esta réplica (objetivo: consultas < 2 s, notas < 10 s).", async () => {
    const r = await api("/api/gestion/salud");
    return h("div", {},
      tarjeta("Verificaciones", h("p", {}, "Estado general: ", insignia(TONOS[r.estado] || TONOS.falla)),
        tabla("Lo que necesita la réplica para atender", ["Verificación", "Estado", "Detalle", "Crítica"], r.verificaciones.map((v) =>
          [v.nombre, insignia(TONOS[v.estado] || TONOS.falla), v.detalle, v.critica ? "Sí" : "No (hay respaldo)"]), { filaEncabezado: true })),
      r.rutas.length ? tabla("Tiempos de respuesta por ruta", ["Ruta", "Peticiones", "p50 (ms)", "p95 (ms)", "Objetivo", "Cumple"], r.rutas.map((x) =>
        [x.ruta, String(x.peticiones), String(x.p50_ms), String(x.p95_ms), `${x.objetivo_ms / 1000} s`,
          x.cumple ? insignia({ texto: "Sí", tono: "ok", icono: "ok" }) : insignia({ texto: "No", tono: "crit", icono: "alerta" })]), { numericas: [1, 2, 3], filaEncabezado: true })
        : tarjeta("Tiempos de respuesta", vacio("Aún no hay peticiones medidas en esta réplica.")));
  });
}

/* ---------------- Notificaciones (CFG-02, se conecta sola) ---------------- */

/* Qué eventos avisan y por qué canal: un grupo por evento, con su error junto al grupo y un resumen arriba (WCAG 3.3.1).
   Con un solo canal no hay nada que elegir: se oculta «Por qué canal» y se guarda ese canal. */
function formularioPreferencias(prefs) {
  const unSoloCanal = prefs.canales.length === 1;
  const grupos = prefs.eventos.map((ev) => {
    const activo = casilla({ nombre: `${ev.evento}-activo`, etiqueta: "Avisarme", marcada: ev.activo });
    const canales = prefs.canales.map((c) => ({ valor: c.valor, ...casilla({ nombre: `${ev.evento}-${c.valor}`,
      etiqueta: c.disponible ? c.etiqueta : `${c.etiqueta} (se guarda; aún no se envía)`, marcada: ev.canales.includes(c.valor) }) }));
    const error = h("p", { class: "error-campo", id: idUnico(`error-${ev.evento}`), hidden: true });
    const grupoCanales = h("fieldset", { "aria-describedby": error.id }, h("legend", {}, "Por qué canal"), canales.map((c) => c.nodo));
    return { ev, activo, canales, error, grupoCanales,
      nodo: h("fieldset", {}, h("legend", {}, ev.etiqueta), h("p", { class: "ayuda" }, ev.descripcion), activo.nodo, unSoloCanal ? null : grupoCanales, error) };
  });
  const resumen = h("div", { tabindex: "-1" });
  const boton = h("button", { type: "submit", class: "btn" }, "Guardar preferencias");
  const notas = prefs.canales.filter((c) => !c.disponible && c.nota).map((c) => mensaje("info", c.etiqueta, c.nota));
  return h("div", {}, resumen, h("form", { class: "preferencias", novalidate: true, onsubmit: async (e) => {
    e.preventDefault();
    resumen.replaceChildren();
    grupos.forEach((g) => { g.error.hidden = true; g.error.textContent = ""; g.grupoCanales.removeAttribute("aria-invalid"); });
    boton.disabled = true; boton.setAttribute("aria-busy", "true");
    try {
      await api("/api/notificaciones/preferencias", { metodo: "PUT", cuerpo: { preferencias: grupos.map((g) => ({
        evento: g.ev.evento, activo: g.activo.control.checked,
        canales: unSoloCanal ? [prefs.canales[0].valor] : g.canales.filter((c) => c.control.checked).map((c) => c.valor) })) } });
      anunciar("Preferencias guardadas."); recargar();
    } catch (err) {
      let primero = null;
      for (const g of grupos) {
        const texto = err.campos && err.campos[`canales.${g.ev.evento}`];
        if (texto) { g.error.textContent = texto; g.error.hidden = false; g.grupoCanales.setAttribute("aria-invalid", "true"); primero = primero || (unSoloCanal ? g.activo.control : g.canales[0].control); }
      }
      resumen.replaceChildren(mensaje("error", "No se guardaron las preferencias", ...(err.mensajes.length > 1 ? [h("ul", {}, err.mensajes.map((m) => h("li", {}, m)))] : [err.mensajes[0]])));
      (primero || resumen).focus();
    } finally {
      boton.disabled = false; boton.removeAttribute("aria-busy");
    }
  } }, grupos.map((g) => g.nodo), ...notas, h("div", { class: "acciones" }, boton)));
}

export async function vistaNotificaciones(ctx) {
  const ext = ctx.capacidades.extensiones.notificaciones;
  if (!ext.disponible) {
    return { titulo: "Notificaciones", nodo: h("div", {}, h("h1", {}, "Notificaciones y alertas"),
      mensaje("info", "Pendiente de integrar", "Esta pantalla se activa sola cuando el sistema publique las notificaciones y alertas. Mientras tanto, las alertas críticas de laboratorio e interacciones se ven en el resumen de cada paciente.")) };
  }
  return pantalla("Notificaciones y alertas", "Resultados críticos, estudios pendientes e interacciones que no debes perderte.", async () => {
    const [lista, prefs] = await Promise.all([api("/api/notificaciones"), ext.preferencias ? api("/api/notificaciones/preferencias").catch(() => null) : null]);
    const items = Array.isArray(lista) ? lista : lista.notificaciones || lista.items || [];
    const noLeidas = items.filter((n) => !n.leida).length;
    const pintar = (n) => h("li", {}, h("strong", {}, n.titulo || n.tipo || "Notificación"), " ",
      n.severidad ? insignia(SEVERIDADES[n.severidad] || { texto: n.severidad, tono: "info", icono: "alerta" }) : null, " ",
      n.leida ? insignia({ texto: "Leída", tono: "neutra", icono: "ok" }) : null,
      n.paciente_id !== undefined ? h("p", {}, "Paciente: ", h("a", { href: `#/pacientes/${n.paciente_id}${n.evento === "resultado_critico" ? "/laboratorios" : ""}` }, n.paciente || `#${n.paciente_id}`)) : null,
      h("p", {}, n.mensaje || n.descripcion || n.detalle || ""), h("p", { class: "ayuda" }, fecha(String(n.fecha || n.creada_en || "").slice(0, 10))),
      ext.marcar_leida && n.id !== undefined && !n.leida ? h("button", { type: "button", class: "btn sec chico", onclick: async () => {
        try { await api(`/api/notificaciones/${encodeURIComponent(n.id)}/leida`, { metodo: "POST", cuerpo: {} }); anunciar("Notificación marcada como leída."); recargar(); } catch (err) { anunciar(err.mensajes[0]); }
      } }, "Marcar como leída") : null);
    const nodoPrefs = prefs && Array.isArray(prefs.eventos) ? tarjeta("Qué me avisa y por dónde",
      prefs.es_por_defecto ? h("p", { class: "ayuda" }, "Aún no has cambiado nada: todos los eventos te avisan en la aplicación.") : null,
      ext.guardar_preferencias ? formularioPreferencias(prefs)
        : prefs.canales.length === 1
          ? tabla("Preferencias", ["Evento", "Avisa"], prefs.eventos.map((ev) => [ev.etiqueta, ev.activo ? "Sí" : "No"]), { filaEncabezado: true })
          : tabla("Preferencias", ["Evento", "Avisa", "Canales"], prefs.eventos.map((ev) => [ev.etiqueta, ev.activo ? "Sí" : "No", ev.canales.join(", ") || "—"]), { filaEncabezado: true }))
      : null;
    return h("div", {}, items.length ? tarjeta(`${items.length} notificaciones${noLeidas ? ` (${noLeidas} sin leer)` : ""}`, h("ul", { class: "lista-limpia" }, items.map(pintar)))
      : tarjeta("Notificaciones", vacio("No tienes notificaciones.")), nodoPrefs);
  });
}
