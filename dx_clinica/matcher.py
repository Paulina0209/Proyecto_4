"""Emparejamiento de hallazgos clínicos contra palabras clave, con negación.

Un emparejamiento ingenuo por subcadena tiene un problema serio para un
motor de diagnóstico diferencial: si el hallazgo dice "sin hallazgos de
progresión", buscar la palabra "progresión" como subcadena la encuentra
igual, aunque el texto diga exactamente lo contrario. Esto es
precisamente el riesgo de "utilización inadecuada de datos clínicos" que
señala el backlog de DX-02. Esta función evita ese caso concreto
detectando negaciones simples inmediatamente antes de la palabra clave.

No pretende ser un detector de negación clínico completo (algo como NegEx
sería lo apropiado para producción); es deliberadamente simple y
documentado como tal.
"""

from __future__ import annotations

from typing import Sequence

_NEGATION_MARKERS = (
    "sin ",
    "no ",
    "ausencia de",
    "se descarta",
    "descarta",
    "niega",
    "no se observa",
    "no evidencia de",
    "sin evidencia de",
)

#: Cuántos caracteres antes de la palabra clave se revisan en busca de una
#: negación. Suficiente para frases cortas tipo "sin hallazgos de X" sin
#: alcanzar a "contaminarse" con la oración anterior.
_VENTANA_NEGACION = 40


def _ocurrencia_esta_negada(texto_normalizado: str, indice_inicio: int) -> bool:
    inicio_ventana = max(0, indice_inicio - _VENTANA_NEGACION)
    ventana = texto_normalizado[inicio_ventana:indice_inicio]
    return any(marcador in ventana for marcador in _NEGATION_MARKERS)


def coincide_sin_negacion(texto: str, palabras_clave: Sequence[str]) -> bool:
    """True si alguna palabra clave aparece en ``texto`` sin estar negada justo antes.

    Si la misma palabra clave aparece más de una vez en el texto (poco
    común en oraciones cortas), basta con que una aparición no esté
    negada para considerar que el texto sí aporta al criterio.
    """

    texto_normalizado = texto.lower()
    for palabra in palabras_clave:
        palabra_normalizada = palabra.lower()
        indice = texto_normalizado.find(palabra_normalizada)
        while indice != -1:
            if not _ocurrencia_esta_negada(texto_normalizado, indice):
                return True
            indice = texto_normalizado.find(palabra_normalizada, indice + 1)
    return False
