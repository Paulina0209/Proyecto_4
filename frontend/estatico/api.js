/* Cliente de la pasarela. La sesión viaja en una cookie HttpOnly: este código nunca ve ni guarda la contraseña. */
export class ErrorApi extends Error {
  constructor(estado, mensajes, campos) {
    super(mensajes[0] || "Ocurrió un error.");
    this.estado = estado;
    this.mensajes = mensajes;
    this.campos = campos || {};
  }
}

/* Entiende los formatos de error del sistema: {detail: "texto"}, {detail: {errores: [...]}}, {errores: [...]}. */
function leerError(estado, cuerpo) {
  const errores = (cuerpo && (cuerpo.errores || (cuerpo.detail && cuerpo.detail.errores))) || null;
  if (Array.isArray(errores) && errores.length) {
    const campos = {};
    const mensajes = errores.map((e) => {
      if (e.campo) campos[e.campo] = e.mensaje;
      return e.mensaje;
    });
    return new ErrorApi(estado, mensajes, campos);
  }
  const detalle = cuerpo && cuerpo.detail;
  if (typeof detalle === "string") return new ErrorApi(estado, [detalle]);
  if (cuerpo && typeof cuerpo.mensaje === "string") return new ErrorApi(estado, [cuerpo.mensaje]);
  const texto = estado >= 500 ? "El servidor tuvo un problema. Inténtalo de nuevo en unos minutos." : "No se pudo completar la acción.";
  return new ErrorApi(estado, [texto]);
}

export async function api(ruta, { metodo = "GET", cuerpo, consulta, sinSesion = false } = {}) {
  let url = ruta;
  if (consulta) {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(consulta)) if (v !== undefined && v !== null && v !== "") p.set(k, v);
    const texto = p.toString();
    if (texto) url += (url.includes("?") ? "&" : "?") + texto;
  }
  const cabeceras = { Accept: "application/json" };
  if (metodo !== "GET") cabeceras["X-Copiloto-Solicitud"] = "1";
  if (cuerpo !== undefined) cabeceras["Content-Type"] = "application/json";
  let respuesta;
  try {
    respuesta = await fetch(url, { method: metodo, headers: cabeceras, credentials: "same-origin", body: cuerpo === undefined ? undefined : JSON.stringify(cuerpo) });
  } catch (e) {
    throw new ErrorApi(0, ["No se pudo conectar con el servidor. Revisa tu conexión e inténtalo de nuevo."]);
  }
  if (respuesta.status === 204) return null;
  let datos = null;
  try { datos = await respuesta.json(); } catch (e) { datos = null; }
  if (!respuesta.ok) {
    if (respuesta.status === 401 && !sinSesion) document.dispatchEvent(new CustomEvent("sesion-terminada"));
    throw leerError(respuesta.status, datos);
  }
  return datos;
}

/* Descarga un archivo con la sesión actual (el navegador no puede enlazarlo directo si falla: así el error se muestra). */
export async function descargar(ruta) {
  let respuesta;
  try {
    respuesta = await fetch(ruta, { credentials: "same-origin" });
  } catch (e) {
    throw new ErrorApi(0, ["No se pudo conectar con el servidor."]);
  }
  if (!respuesta.ok) {
    let datos = null;
    try { datos = await respuesta.json(); } catch (e) { datos = null; }
    throw leerError(respuesta.status, datos);
  }
  const disposicion = respuesta.headers.get("content-disposition") || "";
  const m = /filename="?([^";]+)"?/.exec(disposicion);
  const blob = await respuesta.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = m ? m[1] : "descarga";
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 2000);
}
