"""NFR-04 — Minimización de datos en el contexto que se envía a la IA.

AC: cuando se construye el contexto para el componente de IA, solo se usa la
información estrictamente necesaria y autorizada para la operación.

*Autorizada* lo resuelve SEC-03 (``privacidad.consentimiento_ia``).
*Necesaria* se resuelve aquí: ninguna función de IA del copiloto necesita
saber quién es el paciente para razonar sobre su caso, así que los
identificadores directos no salen hacia el modelo:

    - ``quitar_identificadores``: saca de un registro estructurado las claves
      que identifican a la persona (nombre, documento, contacto, fecha de
      nacimiento). El paciente se referencia por su id interno.
    - ``seudonimizar_texto``: en texto libre (notas dictadas, antecedentes
      importados) reemplaza el nombre y el documento del propio paciente, y
      correos y teléfonos de cualquiera, por marcadores.

La reidentificación queda del lado del copiloto: el id interno solo tiene
sentido dentro de la base de la institución.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Optional

#: Claves que identifican directamente a una persona.
CLAVES_IDENTIFICADORAS = frozenset(
    {
        "nombre",
        "nombre_completo",
        "identificacion",
        "numero_identificacion",
        "tipo_identificacion",
        "documento",
        "fecha_nacimiento",
        "telefono",
        "email",
        "correo",
        "direccion",
        "contacto",
    }
)

MARCADOR_PACIENTE = "[PACIENTE]"
MARCADOR_DOCUMENTO = "[DOCUMENTO]"
MARCADOR_CORREO = "[CORREO]"
MARCADOR_TELEFONO = "[TELÉFONO]"

_CORREO = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Teléfonos: +57 300 123 4567, (604) 444-5566, 3001234567. Se exige un prefijo
# "+", paréntesis o al menos 10 dígitos para no confundir valores de laboratorio.
_TELEFONO = re.compile(r"(?:\+\d{1,3}[\s.-]?)?(?:\(\d{1,4}\)[\s.-]?)?\d{3}[\s.-]?\d{3}[\s.-]?\d{4}\b")
#: Palabras de un nombre que no se reemplazan solas (conectores).
_CONECTORES = frozenset({"de", "del", "la", "las", "los", "y", "e", "van", "von", "da", "dos"})
_SUFIJO_SINTETICO = re.compile(r"\s*\(.*?\)\s*$")


def quitar_identificadores(registro: Mapping[str, Any]) -> dict:
    """Copia de ``registro`` (recursiva) sin las claves identificadoras."""
    return {
        clave: _limpiar(valor)
        for clave, valor in registro.items()
        if clave.casefold() not in CLAVES_IDENTIFICADORAS
    }


def _limpiar(valor: Any) -> Any:
    if isinstance(valor, Mapping):
        return quitar_identificadores(valor)
    if isinstance(valor, (list, tuple)):
        return type(valor)(_limpiar(v) for v in valor)
    return valor


def seudonimizar_texto(
    texto: str,
    *,
    nombre: Optional[str] = None,
    identificaciones: Iterable[str] = (),
) -> str:
    """Reemplaza en ``texto`` el nombre y los documentos del paciente, y correos y teléfonos."""
    if not texto:
        return texto
    resultado = _CORREO.sub(MARCADOR_CORREO, texto)

    for identificacion in sorted({i.strip() for i in identificaciones if i and i.strip()}, key=len, reverse=True):
        # El id de cBioPortal (CBIO:estudio:P-0000036) también aparece solo como P-0000036.
        for variante in {identificacion, identificacion.rsplit(":", 1)[-1]}:
            if len(variante) >= 4:
                resultado = re.sub(rf"(?<![\w-]){re.escape(variante)}(?![\w-])", MARCADOR_DOCUMENTO, resultado, flags=re.IGNORECASE)

    resultado = _TELEFONO.sub(MARCADOR_TELEFONO, resultado)

    if nombre:
        nombre = _SUFIJO_SINTETICO.sub("", nombre).strip()
        partes = [p for p in re.split(r"\s+", nombre) if len(p) > 2 and p.casefold() not in _CONECTORES]
        # Primero el nombre completo, después cada palabra (nombre o apellido sueltos).
        for fragmento in [nombre, *sorted(partes, key=len, reverse=True)]:
            if fragmento:
                resultado = re.sub(rf"(?<!\w){re.escape(fragmento)}(?!\w)", MARCADOR_PACIENTE, resultado, flags=re.IGNORECASE)
        resultado = re.sub(rf"{re.escape(MARCADOR_PACIENTE)}(?:\s+{re.escape(MARCADOR_PACIENTE)})+", MARCADOR_PACIENTE, resultado)
    return resultado
