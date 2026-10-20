/* Núcleo de la interfaz: sesión, cabecera según el rol, capacidades del sistema y enrutador por hash
   (sin dependencias ni paso de compilación). Tema único claro: blanco y azul. */
import { h, anunciar } from "./dom.js";
import { api, ErrorApi } from "./api.js";
import { errorConReintento, mensaje } from "./ui.js";
import { vistaLogin } from "./vista_login.js";
import { vistaChat } from "./vista_chat.js";
import { vistaPacientes } from "./vista_pacientes.js";
import { vistaRegistroPaciente } from "./vista_registro.js";
import { vistaExpediente } from "./vista_expediente.js";
import { vistaMetricas } from "./vista_metricas.js";
import { vistaAuditoria, vistaGuias, vistaNotificaciones, vistaSistema, vistaUsuarios } from "./vista_gestion.js";

const NOMBRE_APP = "Copiloto oncológico";
const principal = document.getElementById("contenido");
const SIN_CAPACIDADES = { modelo_ia: { configurado: false }, agente: { disponible: false }, extensiones: { linea_tiempo: { disponible: false }, notificaciones: { disponible: false } } };
const estado = { sesion: null, info: { modo_demo: false }, capacidades: SIN_CAPACIDADES, destino: null, aviso: null, contador: 0, primera: true };

/* ---------------- Cabecera según la sesión ---------------- */
const MENU = [
  ["nav-asistente", (s) => s.acceso_clinico],
  ["nav-pacientes", (s) => s.acceso_clinico],
  ["nav-notificaciones", (s, c) => s.acceso_clinico && c.extensiones.notificaciones.disponible],
  ["nav-guias", (s) => s.acceso_clinico || s.configurar_guias],
  ["nav-metricas", (s) => s.ver_metricas],
  ["nav-auditoria", (s) => s.ver_auditoria],
  ["nav-usuarios", (s) => s.gestionar_usuarios],
  ["nav-sistema", (s) => s.ver_estado_sistema],
];

function actualizarCabecera() {
  const s = estado.sesion;
  document.getElementById("nav-principal").hidden = !s;
  document.getElementById("usuario-barra").hidden = !s;
  for (const [id, visible] of MENU) document.getElementById(id).hidden = !(s && visible(s, estado.capacidades));
  const quien = document.getElementById("quien");
  quien.replaceChildren();
  if (s) quien.append(s.usuario.nombre_completo, h("small", {}, s.usuario.rol_etiqueta));
  const actual = (window.location.hash || "").replace(/^#/, "");
  document.querySelectorAll(".nav-principal a").forEach((a) => {
    const destino = a.getAttribute("href").replace(/^#/, "");
    if (actual === destino || actual.startsWith(`${destino}/`) || actual.startsWith(`${destino}?`)) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
}

/* ---------------- Contador de notificaciones sin leer (CFG-02) ----------------
   Se consulta al cambiar de pantalla, al volver a la pestaña y cada INTERVALO_NOTIFICACIONES_MS mientras está
   visible. Si sube, se anuncia a lectores de pantalla; la primera lectura de la sesión no se anuncia. */
const INTERVALO_NOTIFICACIONES_MS = 45000;
const avisos = { sinLeer: null, consulta: 0 };

function pintarContador(n) {
  const enlace = document.getElementById("nav-notificaciones");
  enlace.replaceChildren("Notificaciones");
  if (n > 0) enlace.append(" ", h("span", { class: "contador", "data-sin-leer": String(n) }, String(n), h("span", { class: "vh" }, " sin leer")));
}

async function actualizarContadorNotificaciones() {
  const s = estado.sesion;
  if (!s || !s.acceso_clinico || !estado.capacidades.extensiones.notificaciones.disponible) {
    avisos.sinLeer = null; pintarContador(0); return;
  }
  const mia = ++avisos.consulta;
  let n;
  try {
    const lista = await api("/api/notificaciones");
    n = Number.isInteger(lista && lista.no_leidas) ? lista.no_leidas : (lista.notificaciones || lista || []).filter((x) => !x.leida).length;
  } catch (e) { return; }                                        // sin red, el contador se queda como estaba
  if (mia !== avisos.consulta || estado.sesion !== s) return;
  const antes = avisos.sinLeer;
  avisos.sinLeer = n;
  pintarContador(n);
  if (antes !== null && n > antes) {
    const nuevas = n - antes;
    anunciar(nuevas === 1 ? `Tienes 1 notificación nueva. ${n} sin leer.` : `Tienes ${nuevas} notificaciones nuevas. ${n} sin leer.`);
  }
}

window.setInterval(() => { if (!document.hidden) actualizarContadorNotificaciones(); }, INTERVALO_NOTIFICACIONES_MS);
document.addEventListener("visibilitychange", () => { if (!document.hidden) actualizarContadorNotificaciones(); });

/* Primera pantalla de cada rol. */
function inicio(s) {
  if (!s) return "#/ingresar";
  if (s.acceso_clinico) return "#/asistente";
  if (s.ver_metricas) return "#/metricas";
  if (s.ver_auditoria) return "#/auditoria";
  if (s.gestionar_usuarios) return "#/usuarios";
  if (s.configurar_guias) return "#/guias";
  return "#/sin-acceso";
}

/* ---------------- Rutas ---------------- */
function sinAcceso(ctx) {
  return { titulo: "Sin acceso a expedientes", nodo: h("div", {}, h("h1", {}, "Sin pantallas de expediente"),
    mensaje("info", null, ctx.sesion.mensaje_sin_acceso_clinico || "Tu rol no tiene acceso a expedientes."),
    ctx.sesion.ver_metricas ? h("p", {}, h("a", { href: "#/metricas" }, "Ir a las métricas de uso")) : null) };
}
const clinica = (vista) => (ctx) => (ctx.sesion.acceso_clinico ? vista(ctx) : sinAcceso(ctx));

const RUTAS = [
  { patron: /^\/ingresar$/, vista: vistaLogin, publica: true },
  { patron: /^\/sin-acceso$/, vista: sinAcceso },
  { patron: /^\/asistente(?:\/([\w-]+))?$/, vista: clinica(vistaChat), parametros: ["conversacion"] },
  { patron: /^\/pacientes$/, vista: clinica(vistaPacientes) },
  { patron: /^\/pacientes\/nuevo$/, vista: clinica(vistaRegistroPaciente) },
  { patron: /^\/pacientes\/(\d+)(?:\/([a-z-]+))?$/, vista: clinica(vistaExpediente), parametros: ["id", "seccion"] },
  { patron: /^\/notificaciones$/, vista: clinica(vistaNotificaciones) },
  { patron: /^\/guias$/, vista: vistaGuias },
  { patron: /^\/metricas$/, vista: vistaMetricas },
  { patron: /^\/auditoria$/, vista: vistaAuditoria },
  { patron: /^\/usuarios$/, vista: vistaUsuarios },
  { patron: /^\/sistema$/, vista: vistaSistema },
];

function analizarHash() {
  const crudo = (window.location.hash || "").replace(/^#/, "") || "/";
  const [ruta, consulta = ""] = crudo.split("?");
  return { ruta, consulta: new URLSearchParams(consulta) };
}

async function navegar() {
  const mia = ++estado.contador;
  const { ruta, consulta } = analizarHash();
  if (ruta === "/" || ruta === "/inicio") { window.location.replace(inicio(estado.sesion)); return; }
  const definicion = RUTAS.find((r) => r.patron.test(ruta));
  if (!estado.sesion && !(definicion && definicion.publica)) {
    estado.destino = window.location.hash;
    window.location.replace("#/ingresar");
    return;
  }
  if (estado.sesion && definicion && definicion.publica) { window.location.replace(inicio(estado.sesion)); return; }
  actualizarCabecera();

  const ctx = { sesion: estado.sesion, info: estado.info, capacidades: estado.capacidades, consulta, parametros: {}, aviso: estado.aviso,
    alIniciarSesion: async (s) => {
      estado.sesion = s;
      await cargarCapacidades();
      actualizarCabecera();
      const d = estado.destino; estado.destino = null;
      window.location.hash = d && d !== "#/ingresar" ? d : inicio(s);
    } };
  estado.aviso = null;
  let resultado;
  if (!definicion) {
    resultado = { titulo: "Página no encontrada", nodo: h("div", {}, h("h1", {}, "Página no encontrada"), h("p", {}, h("a", { href: inicio(estado.sesion) }, "Ir al inicio"))) };
  } else {
    const m = definicion.patron.exec(ruta);
    (definicion.parametros || []).forEach((nombre, i) => { if (m[i + 1] !== undefined) ctx.parametros[nombre] = m[i + 1]; });
    principal.replaceChildren(h("h1", {}, "Cargando…"), h("p", { class: "cargando", role: "status" }, "Cargando…"));
    principal.setAttribute("aria-busy", "true");
    try {
      resultado = await definicion.vista(ctx);
    } catch (err) {
      if (mia !== estado.contador) return;
      resultado = { titulo: "Error", nodo: h("div", {}, h("h1", {}, "No se pudo abrir esta página"),
        errorConReintento(err instanceof ErrorApi ? err : new ErrorApi(0, [String(err && err.message ? err.message : err)]), navegar)) };
    }
  }
  if (mia !== estado.contador) return;
  principal.removeAttribute("aria-busy");
  principal.replaceChildren(resultado.nodo);
  document.title = `${resultado.titulo} — ${NOMBRE_APP}`;
  // El foco va al título solo cuando la persona CAMBIA de pantalla; al abrir o recargar queda al principio del
  // documento (el primer Tab llega a «Saltar al contenido»), salvo el formulario de acceso, que lo pide.
  if (!estado.primera || resultado.foco) {
    const titulo = resultado.foco || principal.querySelector("h1");
    if (titulo) { titulo.setAttribute("tabindex", "-1"); titulo.focus({ preventScroll: false }); }
  }
  estado.primera = false;
  anunciar(resultado.titulo);
  actualizarContadorNotificaciones();
  if (resultado.alMostrar) await resultado.alMostrar();
}

/* ---------------- Sesión ---------------- */
async function cargarCapacidades() {
  try { estado.capacidades = await api("/api/clinica/capacidades", { sinSesion: true }); } catch (e) { estado.capacidades = SIN_CAPACIDADES; }
}

function irAIngresar(aviso) {
  estado.sesion = null;
  estado.aviso = aviso || null;
  avisos.sinLeer = null;
  pintarContador(0);
  actualizarCabecera();
  if (window.location.hash === "#/ingresar") navegar(); else window.location.hash = "#/ingresar";
}

document.addEventListener("sesion-terminada", () => {
  if (!estado.sesion) return;
  estado.destino = window.location.hash;
  irAIngresar({ tipo: "info", texto: "Tu sesión terminó. Vuelve a entrar para continuar donde estabas." });
});

document.getElementById("btn-salir").addEventListener("click", async () => {
  try { await api("/api/sesion", { metodo: "DELETE", sinSesion: true }); } catch (e) { /* aunque falle el servidor, se cierra la pantalla */ }
  estado.destino = null;
  irAIngresar({ tipo: "ok", texto: "Cerraste tu sesión." });
});

// El enrutador usa el hash de la URL, así que «#contenido» del enlace de salto se tomaría por una ruta: se maneja aquí.
document.querySelector(".saltar").addEventListener("click", (e) => { e.preventDefault(); principal.focus(); });

window.addEventListener("hashchange", navegar);

async function arrancar() {
  try { estado.info = await api("/api/info", { sinSesion: true }); } catch (e) { estado.info = { modo_demo: false }; }
  const aviso = document.getElementById("aviso-demo");
  if (estado.info.modo_demo) {
    aviso.textContent = "Entorno de demostración: todos los datos son inventados. No escribas información real de pacientes.";
    aviso.hidden = false;
  }
  try { const s = await api("/api/sesion", { sinSesion: true }); estado.sesion = s && s.autenticado ? s : null; } catch (e) { estado.sesion = null; }
  if (estado.sesion) await cargarCapacidades();
  actualizarCabecera();
  await navegar();
}
arrancar();
