/* Núcleo de la interfaz: sesión, cabecera, tema y enrutador por hash (sin dependencias ni paso de compilación). */
import { h, anunciar } from "./dom.js";
import { api, ErrorApi } from "./api.js";
import { errorConReintento, mensaje } from "./ui.js";
import { vistaLogin } from "./vista_login.js";
import { vistaPacientes } from "./vista_pacientes.js";
import { vistaExpediente } from "./vista_expediente.js";
import { vistaMetricas } from "./vista_metricas.js";

const NOMBRE_APP = "Copiloto oncológico";
const principal = document.getElementById("contenido");
const estado = { sesion: null, info: { modo_demo: false }, destino: null, aviso: null, contador: 0, primera: true };

/* ---------------- Tema (automático / claro / oscuro) ---------------- */
const TEMAS = [["auto", "automático"], ["light", "claro"], ["dark", "oscuro"]];
function temaGuardado() {
  try { const t = window.localStorage.getItem("copiloto-tema"); return t === "light" || t === "dark" ? t : "auto"; } catch (e) { return "auto"; }
}
function aplicarTema(clave) {
  if (clave === "auto") document.documentElement.removeAttribute("data-theme"); else document.documentElement.setAttribute("data-theme", clave);
  try { if (clave === "auto") window.localStorage.removeItem("copiloto-tema"); else window.localStorage.setItem("copiloto-tema", clave); } catch (e) { /* sin almacenamiento */ }
  const nombre = TEMAS.find(([c]) => c === clave)[1];
  document.getElementById("btn-tema").textContent = `Tema: ${nombre}`;
  document.querySelectorAll("iframe.marco-tablero").forEach(sincronizarTemaDelMarco);
  return nombre;
}
function sincronizarTemaDelMarco(marco) {
  try {
    const raiz = marco.contentDocument && marco.contentDocument.documentElement;
    if (!raiz) return;
    const t = temaGuardado();
    if (t === "auto") raiz.removeAttribute("data-theme"); else raiz.setAttribute("data-theme", t);
  } catch (e) { /* marco de otro origen: no aplica */ }
}
document.getElementById("btn-tema").addEventListener("click", () => {
  const i = TEMAS.findIndex(([c]) => c === temaGuardado());
  const siguiente = TEMAS[(i + 1) % TEMAS.length][0];
  anunciar(`Tema ${aplicarTema(siguiente)}.`);
});
aplicarTema(temaGuardado());

/* ---------------- Cabecera según la sesión ---------------- */
function actualizarCabecera() {
  const s = estado.sesion;
  document.getElementById("nav-principal").hidden = !s;
  document.getElementById("usuario-barra").hidden = !s;
  document.getElementById("nav-metricas").hidden = !(s && s.ver_metricas);
  document.getElementById("nav-pacientes").hidden = !(s && (s.acceso_clinico || !s.ver_metricas));
  const quien = document.getElementById("quien");
  quien.replaceChildren();
  if (s) quien.append(s.usuario.nombre_completo, h("small", {}, s.usuario.rol_etiqueta));
  const actual = (window.location.hash || "").replace(/^#/, "");
  document.querySelectorAll(".nav-principal a").forEach((a) => {
    const destino = a.getAttribute("href").replace(/^#/, "");
    if (actual === destino || actual.startsWith(`${destino}/`) || actual.startsWith(`${destino}?`)) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
}

function inicio(s) { return s && !s.acceso_clinico && s.ver_metricas ? "#/metricas" : "#/pacientes"; }

/* ---------------- Rutas ---------------- */
function sinAcceso(ctx) {
  return { titulo: "Sin acceso a expedientes", nodo: h("div", {}, h("h1", {}, "Sin pantallas de expediente"),
    mensaje("info", null, ctx.sesion.mensaje_sin_acceso_clinico || "Tu rol no tiene acceso a expedientes."),
    ctx.sesion.ver_metricas ? h("p", {}, h("a", { href: "#/metricas" }, "Ir a las métricas de uso")) : null) };
}
const clinica = (vista) => (ctx) => (ctx.sesion.acceso_clinico ? vista(ctx) : sinAcceso(ctx));

const RUTAS = [
  { patron: /^\/ingresar$/, vista: vistaLogin, publica: true },
  { patron: /^\/pacientes$/, vista: clinica(vistaPacientes) },
  { patron: /^\/pacientes\/(\d+)(?:\/([a-z]+))?$/, vista: clinica(vistaExpediente), parametros: ["id", "seccion"] },
  { patron: /^\/metricas$/, vista: vistaMetricas },
];

function analizarHash() {
  const crudo = (window.location.hash || "").replace(/^#/, "") || "/";
  const [ruta, consulta = ""] = crudo.split("?");
  return { ruta, consulta: new URLSearchParams(consulta) };
}

async function navegar() {
  const mia = ++estado.contador;
  const { ruta, consulta } = analizarHash();
  if (ruta === "/") { window.location.replace(estado.sesion ? inicio(estado.sesion) : "#/ingresar"); return; }
  const definicion = RUTAS.find((r) => r.patron.test(ruta));
  if (!estado.sesion && !(definicion && definicion.publica)) {
    estado.destino = window.location.hash;
    window.location.replace("#/ingresar");
    return;
  }
  if (estado.sesion && definicion && definicion.publica) { window.location.replace(inicio(estado.sesion)); return; }
  actualizarCabecera();

  const ctx = { sesion: estado.sesion, info: estado.info, consulta, parametros: {}, aviso: estado.aviso, sincronizarTemaDelMarco,
    alIniciarSesion: async (s) => { estado.sesion = s; actualizarCabecera(); const d = estado.destino; estado.destino = null; window.location.hash = d && d !== "#/ingresar" ? d : inicio(s); } };
  estado.aviso = null;
  let resultado;
  if (!definicion) {
    resultado = { titulo: "Página no encontrada", nodo: h("div", {}, h("h1", {}, "Página no encontrada"), h("p", {}, h("a", { href: estado.sesion ? inicio(estado.sesion) : "#/ingresar" }, "Ir al inicio"))) };
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
  // El foco se mueve al título solo cuando la persona CAMBIA de pantalla. Al abrir o recargar la página queda al
  // principio del documento (el primer Tab llega al enlace «Saltar al contenido»); la única excepción es el
  // formulario de acceso, que pide el foco en su primer campo.
  if (!estado.primera || resultado.foco) {
    const titulo = resultado.foco || principal.querySelector("h1");
    if (titulo) { titulo.setAttribute("tabindex", "-1"); titulo.focus({ preventScroll: false }); }
  }
  estado.primera = false;
  anunciar(resultado.titulo);
  if (resultado.alMostrar) await resultado.alMostrar();
}

/* ---------------- Sesión ---------------- */
function irAIngresar(aviso) {
  estado.sesion = null;
  estado.aviso = aviso || null;
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
  actualizarCabecera();
  await navegar();
}
arrancar();
