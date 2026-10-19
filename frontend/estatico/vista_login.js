import { h, idUnico } from "./dom.js";
import { api, ErrorApi } from "./api.js";
import { mensaje } from "./ui.js";

/* Pantalla de acceso. Errores: un resumen (role=alert, con foco) y el mensaje junto a cada campo (WCAG 3.3.1). */
export async function vistaLogin(ctx) {
  const idUsuario = idUnico("usuario"), idClave = idUnico("clave"), idErrU = idUnico("eu"), idErrC = idUnico("ec");
  const resumen = h("div", { tabindex: "-1" });
  const errU = h("p", { class: "error-campo", id: idErrU, hidden: true });
  const errC = h("p", { class: "error-campo", id: idErrC, hidden: true });
  const usuario = h("input", { id: idUsuario, name: "usuario", type: "text", autocomplete: "username", autocapitalize: "none", spellcheck: "false", required: true });
  const clave = h("input", { id: idClave, name: "contrasena", type: "password", autocomplete: "current-password", required: true });
  const enviar = h("button", { type: "submit", class: "btn" }, "Entrar");

  function limpiar() {
    resumen.replaceChildren();
    for (const [campo, err] of [[usuario, errU], [clave, errC]]) {
      campo.removeAttribute("aria-invalid"); campo.removeAttribute("aria-describedby"); err.hidden = true; err.textContent = "";
    }
  }
  function marcar(campo, err, id, texto) {
    err.textContent = texto; err.hidden = false; campo.setAttribute("aria-invalid", "true"); campo.setAttribute("aria-describedby", id);
  }

  const formulario = h("form", { novalidate: true, onsubmit: async (e) => {
    e.preventDefault();
    limpiar();
    enviar.disabled = true; enviar.setAttribute("aria-busy", "true");
    try {
      const sesion = await api("/api/sesion", { metodo: "POST", cuerpo: { usuario: usuario.value, contrasena: clave.value }, sinSesion: true });
      clave.value = "";
      await ctx.alIniciarSesion(sesion);
    } catch (err) {
      clave.value = "";
      if (!(err instanceof ErrorApi)) throw err;
      if (err.campos.usuario) marcar(usuario, errU, idErrU, err.campos.usuario);
      if (err.campos.contrasena) marcar(clave, errC, idErrC, err.campos.contrasena);
      resumen.replaceChildren(mensaje("error", err.estado === 423 ? "Cuenta bloqueada temporalmente" : "No pudimos iniciar tu sesión",
        ...(err.mensajes.length > 1 ? [h("ul", {}, err.mensajes.map((m) => h("li", {}, m)))] : [err.mensajes[0]])));
      resumen.focus();
      (err.campos.usuario ? usuario : err.campos.contrasena ? clave : usuario).focus();
      // El foco va al primer campo con problema; el resumen se anuncia solo por ser role=alert.
    } finally {
      enviar.disabled = false; enviar.removeAttribute("aria-busy");
    }
  } },
    h("div", { class: "campo" }, h("label", { for: idUsuario }, "Usuario"), usuario, errU),
    h("div", { class: "campo" }, h("label", { for: idClave }, "Contraseña"), clave, errC),
    h("div", { class: "acciones" }, enviar));

  const demo = ctx.info && ctx.info.modo_demo && ctx.info.demo
    ? h("details", { class: "tarjeta" }, h("summary", {}, "Usuarios de la demostración"),
        h("p", { class: "tenue" }, `Todos usan la contraseña ${ctx.info.demo.clave}. Los datos son inventados.`),
        h("ul", { class: "lista-limpia" }, ctx.info.demo.usuarios.map((u) => h("li", {}, h("strong", {}, u.usuario), ` — ${u.descripcion}`))))
    : null;

  const nodo = h("div", { class: "acceso" },
    h("h1", {}, "Iniciar sesión"),
    h("p", { class: "sub" }, "Ingresa con tu usuario institucional para ver tus pacientes."),
    ctx.aviso ? mensaje(ctx.aviso.tipo, null, ctx.aviso.texto) : null,
    resumen,
    h("div", { class: "tarjeta" }, formulario),
    demo);
  return { titulo: "Iniciar sesión", nodo, foco: usuario };
}
