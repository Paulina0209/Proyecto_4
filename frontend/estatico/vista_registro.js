/* PAC-01: registrar un paciente nuevo. El oncólogo a cargo lo fija la pasarela: el de la sesión o, para admisiones,
   el oncólogo de su equipo que se elija aquí. */
import { h, anunciar } from "./dom.js";
import { api } from "./api.js";
import { campo, formulario, mensaje } from "./ui.js";

export async function vistaRegistroPaciente(ctx) {
  if (!ctx.sesion.puede_registrar_paciente) {
    return { titulo: "Registrar paciente", nodo: h("div", {}, h("h1", {}, "Registrar paciente"), mensaje("aviso", null, "Tu rol no registra pacientes.")) };
  }
  const volver = ctx.sesion.acceso_admision ? "#/admisiones" : "#/pacientes";
  const equipo = ctx.sesion.equipo || [];
  const elegido = ctx.consulta.get("equipo") || (equipo[0] ? String(equipo[0].id) : "");
  const campos = [
    ...(equipo.length > 1 ? [campo({ nombre: "equipo", etiqueta: "Oncólogo a cargo", tipo: "select", requerido: true,
      opciones: equipo.map((o) => [String(o.id), o.nombre]), valor: elegido })] : []),
    campo({ nombre: "nombre_completo", etiqueta: "Nombre completo", requerido: true, atributos: { autocomplete: "off" } }),
    campo({ nombre: "fecha_nacimiento", etiqueta: "Fecha de nacimiento", tipo: "date", requerido: true }),
    campo({ nombre: "sexo", etiqueta: "Sexo", tipo: "select", requerido: true, opciones: [["", "Elegir…"], ["femenino", "Femenino"], ["masculino", "Masculino"], ["otro", "Otro"]] }),
    campo({ nombre: "tipo_identificacion", etiqueta: "Tipo de identificación", tipo: "select", requerido: true,
      opciones: [["", "Elegir…"], ["cedula", "Cédula"], ["tarjeta_identidad", "Tarjeta de identidad"], ["pasaporte", "Pasaporte"], ["registro_civil", "Registro civil"], ["temporal", "Sin documento (temporal)"]] }),
    campo({ nombre: "numero_identificacion", etiqueta: "Número de identificación", ayuda: "Déjalo vacío con «Sin documento»: el sistema genera un identificador temporal." }),
    campo({ nombre: "telefono", etiqueta: "Teléfono", tipo: "tel", ayuda: "Registra al menos un teléfono o un correo." }),
    campo({ nombre: "email", etiqueta: "Correo", tipo: "email" }),
    campo({ nombre: "direccion", etiqueta: "Dirección" }),
    campo({ nombre: "motivo_consulta_inicial", etiqueta: "Motivo de la consulta inicial", tipo: "textarea" }),
    campo({ nombre: "personales", etiqueta: "Antecedentes personales", tipo: "textarea" }),
    campo({ nombre: "familiares", etiqueta: "Antecedentes familiares", tipo: "textarea" }),
  ];
  const nodo = h("div", {},
    h("p", { class: "migas" }, h("a", { href: volver }, ctx.sesion.acceso_admision ? "Admisiones" : "Pacientes"), " / Registrar paciente"),
    h("h1", {}, "Registrar paciente"),
    h("p", { class: "sub" }, "Los antecedentes y el motivo se pueden completar después. El sistema avisa si ya existe alguien con la misma identificación."),
    h("section", { class: "tarjeta" }, formulario({ columnas: true, campos, textoBoton: "Registrar paciente",
      secundario: h("a", { class: "btn sec", href: volver }, "Cancelar"),
      enviar: (v) => api(`/api/pacientes${(v.equipo || elegido) && equipo.length ? `?equipo=${v.equipo || elegido}` : ""}`, { metodo: "POST", cuerpo: {
        nombre_completo: v.nombre_completo, fecha_nacimiento: v.fecha_nacimiento || null, sexo: v.sexo || null,
        tipo_identificacion: v.tipo_identificacion || null, numero_identificacion: v.numero_identificacion || null,
        contacto: { telefono: v.telefono || null, email: v.email || null, direccion: v.direccion || null },
        antecedentes: { personales: v.personales || null, familiares: v.familiares || null },
        motivo_consulta_inicial: v.motivo_consulta_inicial || null } }),
      alExito: (p) => { anunciar(`${p.nombre_completo} quedó registrado.`);
        window.location.hash = ctx.sesion.acceso_admision ? `#/admisiones?q=${encodeURIComponent(p.numero_identificacion || p.nombre_completo)}` : `#/pacientes/${p.id}/consentimiento`; } })));
  return { titulo: "Registrar paciente", nodo };
}
