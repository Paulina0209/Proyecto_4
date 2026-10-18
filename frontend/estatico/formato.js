const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

function partes(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  return m ? { a: Number(m[1]), m: Number(m[2]), d: Number(m[3]) } : null;
}

/* «5 mar 2026»; si no es una fecha, el texto tal cual (o un guion). */
export function fecha(iso) {
  const p = partes(iso);
  if (!p) return iso || "—";
  return `${p.d} ${MESES[p.m - 1]} ${p.a}`;
}

export function edad(iso, hoy = new Date()) {
  const p = partes(iso);
  if (!p) return null;
  let anios = hoy.getFullYear() - p.a;
  if (hoy.getMonth() + 1 < p.m || (hoy.getMonth() + 1 === p.m && hoy.getDate() < p.d)) anios -= 1;
  return anios;
}

export const ESTADOS_TRATAMIENTO = {
  en_tratamiento: { texto: "En tratamiento", tono: "info", icono: "reloj" },
  en_seguimiento: { texto: "En seguimiento", tono: "ok", icono: "ok" },
  suspendido: { texto: "Suspendido", tono: "aviso", icono: "pausa" },
  finalizado: { texto: "Finalizado", tono: "neutra", icono: "ok" },
};

export const SEVERIDADES = {
  critica: { texto: "Crítica", tono: "crit", icono: "alerta" },
  alta: { texto: "Alta", tono: "crit", icono: "alerta" },
  media: { texto: "Media", tono: "aviso", icono: "alerta" },
  baja: { texto: "Baja", tono: "info", icono: "info" },
};

export const TIPOS_ALERTA = {
  interaccion: "Interacción",
  estudio_pendiente: "Estudio pendiente",
  laboratorio_critico: "Laboratorio crítico",
  conflicto_laboratorio: "Conflicto de laboratorio",
  biomarcador_pendiente: "Biomarcador por confirmar",
};

export const RELEVANCIA_BIOMARCADOR = {
  accionable_confirmado: { texto: "Accionable (confirmado)", tono: "ok", icono: "ok" },
  pendiente_confirmacion: { texto: "Pendiente de confirmar", tono: "aviso", icono: "alerta" },
  informativo: { texto: "Informativo", tono: "neutra", icono: "info" },
  descartado: { texto: "Descartado", tono: "neutra", icono: "info" },
};

export const CAMPOS_FALTANTES = {
  diagnostico_principal: "diagnóstico principal",
  estadio: "estadio",
  tratamiento_mas_reciente: "tratamiento más reciente",
};

export const SEXOS = { femenino: "Femenino", masculino: "Masculino", otro: "Otro" };
