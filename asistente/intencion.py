"""Intención de la pregunta y paciente al que se refiere (primer nodo del grafo).

Reglas deterministas, en español clínico: no hace falta un modelo para saber si
el médico pide un dato, un diagnóstico diferencial o las opciones de tratamiento,
y así esta decisión es explicable y no puede "alucinar".

    dato            "¿cuál es el CEA?", "¿tiene EGFR?"  (por defecto, si hay paciente)
    resumen         "resúmeme el caso", "¿cómo está?"
    diagnostico     "¿qué diagnóstico diferencial…?", "¿podría ser progresión?"
    estadificacion  "¿en qué estadio está?", "TNM"
    tratamiento     "opciones de tratamiento", "¿qué esquema…?", "interacciones"
    faltantes       "¿qué falta para decidir?"
    evidencia       "¿qué dice la guía ESMO…?"  (no necesita paciente)
    saludo          "hola", "gracias"
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

INTENCIONES = ("dato", "resumen", "diagnostico", "estadificacion", "tratamiento", "faltantes", "evidencia", "saludo")

ETIQUETAS = {
    "dato": "Buscar un dato del expediente", "resumen": "Resumir el caso", "diagnostico": "Apoyo al diagnóstico",
    "estadificacion": "Estadificación", "tratamiento": "Opciones de tratamiento", "faltantes": "Información faltante",
    "evidencia": "Evidencia de las guías", "saludo": "Conversación",
}

_REGLAS = (
    ("saludo", r"^(hola|buen(os|as)\s+(dias|tardes|noches)|gracias|muchas gracias|ok|listo|perfecto)\W*$"),
    ("faltantes", r"\b(que|cuales)\s+(datos?\s+)?falta|informacion faltante|falta(n)?\s+para\s+decidir|incomplet"),
    ("estadificacion", r"\bestadi(o|ficacion|ficar|ar)\b|\btnm\b|\bajcc\b|\bcategoria\s+[tnm]\b"),
    ("tratamiento", r"\btratamiento|terapia|esquema|regimen|quimio|inmunoterapia|primera linea|segunda linea|interaccion|"
                    r"que (le )?(doy|damos|indico|recomiendas)|opciones terapeuticas|farmaco|medicamento"),
    ("diagnostico", r"diagnostic|diferencial|\bdx\b|sospecha|podria (ser|tener)|que (puede|podria) tener|estudios? (debo|deberia|pedir|solicitar)"),
    ("resumen", r"\bresum|\bcaso\b|junta|panorama|como (esta|va|sigue)|historia clinica|contexto del paciente"),
    ("evidencia", r"\bguia|evidencia|esmo|nccn|recomendacion de la|publicacion|nivel de evidencia"),
)


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c)).casefold()
    return re.sub(r"\s+", " ", texto).strip()


def detectar_intencion(pregunta: str) -> str:
    t = normalizar(pregunta)
    for intencion, patron in _REGLAS:
        if re.search(patron, t):
            return intencion
    return "dato"


def necesita_paciente(intencion: str) -> bool:
    return intencion not in ("evidencia", "saludo")


@dataclass(frozen=True)
class MencionPaciente:
    """Lo que la pregunta dice del paciente: un id de cBioPortal, un documento o un nombre."""

    texto: Optional[str]


_ID_CBIO = re.compile(r"\bP-\d{7}\b", re.IGNORECASE)
_DOCUMENTO = re.compile(r"\b\d{6,10}\b")
_NOMBRE = re.compile(r"(?:paciente|senora|senor|sra\.?|sr\.?)\s+([a-z][a-z]+(?:\s+[a-z][a-z]+){0,3})", re.IGNORECASE)


def mencion_de_paciente(pregunta: str) -> MencionPaciente:
    m = _ID_CBIO.search(pregunta or "")
    if m:
        return MencionPaciente(m.group(0).upper())
    m = _DOCUMENTO.search(pregunta or "")
    if m:
        return MencionPaciente(m.group(0))
    t = normalizar(pregunta)
    m = _NOMBRE.search(t)
    if m:
        palabras = [p for p in m.group(1).split() if p not in {"la", "el", "los", "las", "del", "este", "esta", "mi", "su"}]
        if palabras and not set(palabras) <= {"paciente", "caso"}:
            return MencionPaciente(" ".join(palabras))
    return MencionPaciente(None)
