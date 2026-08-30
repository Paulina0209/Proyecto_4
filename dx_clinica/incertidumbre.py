"""DX-03 — Manejo de la incertidumbre diagnóstica.

Como oncólogo, quiero que el sistema identifique cuándo la información
clínica disponible es insuficiente para establecer una priorización
confiable de diagnósticos diferenciales, para poder reconocer la
incertidumbre y decidir qué información adicional considerar.

Este módulo analiza el ``ResultadoDiagnosticoDiferencial`` que ya produce
DX-02 (``dx_clinica.builder``) — no lo modifica ni le agrega candidatos
"a la fuerza": ``analizar_incertidumbre`` es una capa de lectura que
decide si la priorización que ya existe merece mostrarse acompañada de
una advertencia explícita de incertidumbre, y por qué.

Regla de negocio no negociable (ver backlog, historia DX-03): el sistema
debe expresar incertidumbre cuando la información disponible es
insuficiente, y nunca debe rellenar datos faltantes mediante inferencias
presentadas como hechos.

## Los tres tipos de incertidumbre que se distinguen

La nota técnica de DX-03 pide distinguir entre información faltante,
información contradictoria, e incertidumbre inherente al caso. Este
módulo los detecta así (documentado explícitamente porque cada uno usa
una señal distinta del resultado de DX-02):

1. ``INFORMACION_FALTANTE``: la(s) alternativa(s) en el primer lugar
   tienen criterios de su propio perfil que ningún hallazgo del
   expediente sustenta todavía (``criterios_sin_sustento``). Es el caso
   más directo: hay un hueco conocido y nombrable en los datos.

2. ``AMBIGUEDAD_ENTRE_ALTERNATIVAS``: dos o más alternativas quedan
   empatadas en el primer lugar (mismo número de criterios sustentados
   *y* mismo número total de criterios del perfil). Con la evidencia
   actual, el sistema no tiene forma de decidir cuál de esas alternativas
   priorizar por encima de la otra — la interpretación de "información
   contradictoria" que usa este módulo es precisamente esta: la
   evidencia disponible sustenta igual de bien a más de una alternativa,
   sin ningún hallazgo que las distinga. **Límite de alcance explícito:**
   este módulo no detecta contradicciones literales entre valores
   clínicos (por ejemplo, dos resultados de laboratorio incompatibles
   entre sí para la misma prueba) — eso requeriría un modelo de datos
   clínicos más rico del que dispone `historia_clinica_mock` hoy. Lo que
   sí se detecta, de forma honesta y verificable, es este empate de
   evidencia entre alternativas.

3. ``INCERTIDUMBRE_INHERENTE_AL_CASO``: la alternativa en el primer
   lugar pertenece a un perfil diagnóstico con muy pocos criterios
   definidos en total (``minimo_criterios_perfil_confiable``). Aquí el
   problema no es que falte un dato puntual por registrar — es que el
   perfil mismo es demasiado poco específico para sostener una
   conclusión con confianza, sin importar qué tan completo esté el
   expediente. Pedir "más información" no reduce este tipo de
   incertidumbre; por eso se distingue de ``INFORMACION_FALTANTE``.

Cuando no hay ningún candidato sustentado (``resultado.esta_vacio()``),
se reporta como ``INFORMACION_FALTANTE`` puro: no hay evidencia de
ningún tipo todavía, así que en principio más información sí podría
cambiar la situación.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Tuple

from dx_clinica.knowledge_base import CATALOGO_DIAGNOSTICO_DIFERENCIAL
from dx_clinica.models import ResultadoDiagnosticoDiferencial

#: Aviso fijo que acompaña toda sugerencia de información adicional (nota
#: técnica de DX-03: "deben presentarse como elementos que podrían aportar
#: al razonamiento diagnóstico y no como órdenes clínicas automáticas").
DISCLAIMER_SUGERENCIAS = (
    "Estas son posibles líneas de indagación clínica a considerar, no "
    "órdenes automáticas ni instrucciones de estudios a solicitar; qué "
    "información adicional buscar (y si buscarla) sigue siendo decisión "
    "del oncólogo tratante."
)

_MENSAJE_SIN_INCERTIDUMBRE = (
    "No se detectó ninguno de los criterios de incertidumbre definidos para esta "
    "priorización (sin empates en el primer lugar, sin criterios pendientes en la "
    "alternativa principal, y con un perfil suficientemente específico). Esto no "
    "es una garantía de certeza diagnóstica: sigue siendo apoyo a la decisión "
    "clínica, nunca un diagnóstico definitivo."
)


class TipoIncertidumbre(str, enum.Enum):
    INFORMACION_FALTANTE = "INFORMACION_FALTANTE"
    AMBIGUEDAD_ENTRE_ALTERNATIVAS = "AMBIGUEDAD_ENTRE_ALTERNATIVAS"
    INCERTIDUMBRE_INHERENTE_AL_CASO = "INCERTIDUMBRE_INHERENTE_AL_CASO"


@dataclass(frozen=True)
class AnalisisIncertidumbre:
    """Resultado del análisis de incertidumbre sobre un ``ResultadoDiagnosticoDiferencial``.

    No contiene ninguna lista de candidatos propia: nunca reemplaza ni
    reordena ``resultado.candidatos`` de DX-02 (criterio de aceptación:
    "no fuerza una priorización artificial"). Es, a propósito,
    exclusivamente informativo.
    """

    hay_incertidumbre: bool
    tipos: Tuple[TipoIncertidumbre, ...]
    mensaje: str
    informacion_adicional_sugerida: Tuple[str, ...]
    perfiles_ambiguos: Tuple[str, ...]  # perfil_ids empatados en el primer lugar (vacío si no aplica)
    disclaimer_sugerencias: str = DISCLAIMER_SUGERENCIAS


def analizar_incertidumbre(
    resultado: ResultadoDiagnosticoDiferencial,
    minimo_criterios_perfil_confiable: int = 2,
) -> AnalisisIncertidumbre:
    """Analiza si la priorización de ``resultado`` merece una advertencia de incertidumbre.

    ``minimo_criterios_perfil_confiable`` es el número mínimo de
    criterios que debe definir un perfil para considerarlo lo
    suficientemente específico como para no marcarlo, por sí solo, como
    "incertidumbre inherente al caso" incluso si todos sus criterios
    están sustentados.
    """

    if resultado.esta_vacio():
        return AnalisisIncertidumbre(
            hay_incertidumbre=True,
            tipos=(TipoIncertidumbre.INFORMACION_FALTANTE,),
            mensaje=(
                "Existe incertidumbre: "
                + (resultado.advertencia_sin_sustento or "no hay información suficiente para sustentar ninguna alternativa.")
            ),
            informacion_adicional_sugerida=_sugerencias_catalogo_completo(),
            perfiles_ambiguos=(),
        )

    top = resultado.candidatos[0]
    puntaje_top = (len(top.criterios_sustentados), len(top.criterios_sustentados) + len(top.criterios_sin_sustento))

    empatados = [
        c
        for c in resultado.candidatos
        if (len(c.criterios_sustentados), len(c.criterios_sustentados) + len(c.criterios_sin_sustento)) == puntaje_top
    ]

    tipos = []
    partes_mensaje = []
    sugerencias: list = []
    perfiles_ambiguos: Tuple[str, ...] = ()

    if len(empatados) > 1:
        tipos.append(TipoIncertidumbre.AMBIGUEDAD_ENTRE_ALTERNATIVAS)
        perfiles_ambiguos = tuple(c.perfil_id for c in empatados)
        nombres = ", ".join(c.nombre for c in empatados)
        partes_mensaje.append(
            f"la evidencia disponible sustenta por igual a {len(empatados)} alternativas "
            f"({nombres}), sin ningún hallazgo que permita priorizar una sobre otra todavía"
        )
        for candidato in empatados:
            sugerencias.extend(candidato.criterios_sin_sustento)
    else:
        if top.criterios_sin_sustento:
            tipos.append(TipoIncertidumbre.INFORMACION_FALTANTE)
            partes_mensaje.append(
                f"la alternativa principal ({top.nombre}) todavía tiene criterios propios sin "
                "sustento en el expediente"
            )
            sugerencias.extend(top.criterios_sin_sustento)

    total_criterios_top = len(top.criterios_sustentados) + len(top.criterios_sin_sustento)
    if total_criterios_top < minimo_criterios_perfil_confiable:
        tipos.append(TipoIncertidumbre.INCERTIDUMBRE_INHERENTE_AL_CASO)
        partes_mensaje.append(
            f"el perfil de la alternativa principal ({top.nombre}) se define con muy pocos "
            f"criterios ({total_criterios_top}), así que incluso un sustento completo aporta "
            "poca especificidad diagnóstica por sí solo — esto no se resuelve solo con más "
            "información del mismo tipo"
        )

    if not tipos:
        return AnalisisIncertidumbre(
            hay_incertidumbre=False,
            tipos=(),
            mensaje=_MENSAJE_SIN_INCERTIDUMBRE,
            informacion_adicional_sugerida=(),
            perfiles_ambiguos=(),
        )

    mensaje = "Existe incertidumbre en esta priorización: " + "; y ".join(partes_mensaje) + "."

    # Se deduplica preservando orden, sin perder ninguna sugerencia distinta.
    sugerencias_unicas = tuple(dict.fromkeys(sugerencias))

    return AnalisisIncertidumbre(
        hay_incertidumbre=True,
        tipos=tuple(tipos),
        mensaje=mensaje,
        informacion_adicional_sugerida=sugerencias_unicas,
        perfiles_ambiguos=perfiles_ambiguos,
    )


def _sugerencias_catalogo_completo() -> Tuple[str, ...]:
    """Cuando no hay ningún candidato sustentado, no hay un "top" del cual

    listar criterios pendientes: se listan, en cambio, los criterios de
    todo el catálogo disponible, para ser honesto sobre qué tipo de
    información sabe usar el sistema — no se inventa una lista más
    específica de lo que realmente se puede justificar.
    """

    vistos: dict = {}
    for perfil in CATALOGO_DIAGNOSTICO_DIFERENCIAL:
        for criterio in perfil.criterios:
            vistos.setdefault(criterio.descripcion, None)
    return tuple(vistos.keys())
