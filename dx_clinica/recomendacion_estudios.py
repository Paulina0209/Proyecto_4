"""Recomendación de estudios necesarios según la sospecha diagnóstica (DX-01).

Como oncólogo, quiero que el sistema recomiende únicamente los estudios
necesarios según el caso, para evitar exámenes redundantes o costosos.

Este módulo **no** decide qué estudios pedir a partir de conocimiento
general ni de un modelo estadístico: cada estudio sugerido proviene de
``catalogo_estudios`` (una tabla curada, explícita) y siempre viene
acompañado de su justificación clínica. Antes de sugerir un estudio,
se cruza contra los hallazgos ya registrados en el expediente
(``historia_clinica_mock``, vía ``obtener_hallazgos_de_paciente`` de
DX-02) para no repetir un estudio equivalente que ya exista y siga
siendo reciente — evitando exactamente el "sobre-pedido" que describe la
historia de usuario.

Diseño deliberado, en línea con el resto de la épica DX:

    - Nunca se sugiere un estudio sin justificación explícita (no existe
      ningún camino en este módulo para producir un ``EstudioSugerido``
      sin ``justificacion``).
    - La prioridad es un orden explicable curado en el catálogo (entero
      1 = más prioritario), nunca una probabilidad ni un puntaje
      calculado.
    - Si la sospecha diagnóstica de entrada no coincide con ningún perfil
      del catálogo, no se inventa una lista genérica de estudios: se
      devuelve un resultado vacío con una advertencia explícita.
    - Un estudio "ya existente" solo se considera redundante si además es
      **reciente** (dentro de ``ventana_dias_estudio_reciente``): un
      resultado antiguo no descarta la necesidad clínica de repetirlo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Sequence, Tuple

from historia_clinica_mock.repository import HallazgoClinico

from dx_clinica.catalogo_estudios import (
    CATALOGO_ESTUDIOS_POR_SOSPECHA,
    EstudioCatalogado,
    PerfilSospechaDiagnostica,
)
from dx_clinica.matcher import coincide_sin_negacion

#: Aviso fijo que acompaña todo resultado. Mismo principio que DX-02/DX-03:
#: esto es apoyo a la decisión clínica, no una orden médica automática.
DISCLAIMER = (
    "Esta es una sugerencia de apoyo a la decisión clínica sobre qué "
    "estudios podrían ser relevantes; no constituye una orden médica "
    "automática. La decisión de solicitar (o no) cada estudio es siempre "
    "del oncólogo tratante."
)

#: Texto fijo usado cuando la sospecha diagnóstica no coincide con ningún
#: perfil del catálogo. Nunca se sugiere una lista genérica de estudios
#: "por si acaso" para una sospecha no reconocida.
SOSPECHA_NO_RECONOCIDA = (
    "La sospecha diagnóstica indicada no coincide con ningún perfil del "
    "catálogo de estudios disponible; no se sugiere ningún estudio para "
    "evitar una recomendación genérica sin justificación clínica específica."
)

#: Ventana de recencia por defecto (días) para considerar que un estudio
#: ya registrado sigue siendo válido y no debe repetirse.
VENTANA_DIAS_ESTUDIO_RECIENTE_POR_DEFECTO = 90


@dataclass(frozen=True)
class EstudioSugerido:
    """Un estudio sugerido, con su justificación y posición en la lista priorizada."""

    orden: int  # posición 1-based en la lista final (después de filtrar redundantes)
    id: str
    nombre: str
    tipo: str
    justificacion: str


@dataclass(frozen=True)
class EstudioOmitidoPorRedundante:
    """Un estudio del catálogo que NO se sugirió por ya existir uno equivalente reciente."""

    id: str
    nombre: str
    motivo: str
    hallazgo_existente_id: str
    fecha_hallazgo_existente: str


@dataclass(frozen=True)
class ResultadoRecomendacionEstudios:
    """Resultado completo devuelto al oncólogo para un paciente y una sospecha diagnóstica."""

    paciente_id: int
    sospecha_diagnostica: str
    generado_en: datetime
    estudios_sugeridos: Tuple[EstudioSugerido, ...]
    estudios_omitidos_por_redundantes: Tuple[EstudioOmitidoPorRedundante, ...] = ()
    advertencia_sospecha_no_reconocida: Optional[str] = None

    es_apoyo_a_decision_clinica: bool = field(default=True, init=False)
    disclaimer: str = field(default=DISCLAIMER, init=False)

    def esta_vacio(self) -> bool:
        return len(self.estudios_sugeridos) == 0


def _perfiles_coincidentes(
    sospecha_diagnostica: str, catalogo: Sequence[PerfilSospechaDiagnostica]
) -> List[PerfilSospechaDiagnostica]:
    return [
        perfil
        for perfil in catalogo
        if coincide_sin_negacion(sospecha_diagnostica, perfil.palabras_clave)
    ]


def _ya_existe_equivalente_reciente(
    estudio: EstudioCatalogado,
    hallazgos: Sequence[HallazgoClinico],
    fecha_limite: str,
) -> Optional[HallazgoClinico]:
    """Devuelve el hallazgo que hace redundante a ``estudio``, o ``None`` si no hay ninguno.

    Solo se consideran hallazgos del mismo ``tipo``/``origen`` (un
    laboratorio nunca puede volver redundante una imagen) cuyo texto
    mencione alguna de las palabras clave de equivalencia del estudio, y
    cuya fecha esté dentro de la ventana de recencia (``fecha >= fecha_limite``,
    comparación válida porque las fechas están en formato ISO ``AAAA-MM-DD``).
    """

    for hallazgo in hallazgos:
        if hallazgo.origen != estudio.tipo:
            continue
        if hallazgo.fecha < fecha_limite:
            continue
        if coincide_sin_negacion(hallazgo.texto, estudio.palabras_clave_equivalencia):
            return hallazgo
    return None


def recomendar_estudios(
    paciente_id: int,
    sospecha_diagnostica: str,
    hallazgos: Sequence[HallazgoClinico],
    catalogo: Sequence[PerfilSospechaDiagnostica] = CATALOGO_ESTUDIOS_POR_SOSPECHA,
    ventana_dias_estudio_reciente: int = VENTANA_DIAS_ESTUDIO_RECIENTE_POR_DEFECTO,
    ahora: Optional[datetime] = None,
) -> ResultadoRecomendacionEstudios:
    """Genera la lista priorizada de estudios sugeridos para ``sospecha_diagnostica``.

    ``hallazgos`` debe cubrir todo el expediente del paciente (mismo
    alcance que usa DX-02, típicamente obtenido con
    ``historia_clinica_mock.adapters.obtener_hallazgos_de_paciente``): se
    necesita el historial completo, no solo el de una consulta puntual,
    para poder detectar estudios ya existentes en cualquier momento
    reciente del expediente.
    """

    ahora = ahora or datetime.now()
    fecha_limite = (ahora - timedelta(days=ventana_dias_estudio_reciente)).strftime("%Y-%m-%d")

    perfiles = _perfiles_coincidentes(sospecha_diagnostica, catalogo)
    if not perfiles:
        return ResultadoRecomendacionEstudios(
            paciente_id=paciente_id,
            sospecha_diagnostica=sospecha_diagnostica,
            generado_en=ahora,
            estudios_sugeridos=(),
            estudios_omitidos_por_redundantes=(),
            advertencia_sospecha_no_reconocida=SOSPECHA_NO_RECONOCIDA,
        )

    # Combina los estudios de todos los perfiles que coincidan (una
    # sospecha puede activar más de un perfil a la vez), sin duplicar un
    # mismo estudio si dos perfiles lo comparten.
    estudios_por_id = {}
    for perfil in perfiles:
        for estudio in perfil.estudios:
            estudios_por_id.setdefault(estudio.id, estudio)

    sugeridos: List[EstudioSugerido] = []
    omitidos: List[EstudioOmitidoPorRedundante] = []

    for estudio in sorted(estudios_por_id.values(), key=lambda e: e.prioridad):
        hallazgo_redundante = _ya_existe_equivalente_reciente(estudio, hallazgos, fecha_limite)
        if hallazgo_redundante is not None:
            omitidos.append(
                EstudioOmitidoPorRedundante(
                    id=estudio.id,
                    nombre=estudio.nombre,
                    motivo=(
                        f"Ya existe un estudio equivalente reciente en el expediente "
                        f"(registrado el {hallazgo_redundante.fecha}); no se vuelve a "
                        "sugerir para evitar un examen redundante."
                    ),
                    hallazgo_existente_id=hallazgo_redundante.id,
                    fecha_hallazgo_existente=hallazgo_redundante.fecha,
                )
            )
        else:
            sugeridos.append(
                EstudioSugerido(
                    orden=len(sugeridos) + 1,
                    id=estudio.id,
                    nombre=estudio.nombre,
                    tipo=estudio.tipo,
                    justificacion=estudio.justificacion,
                )
            )

    return ResultadoRecomendacionEstudios(
        paciente_id=paciente_id,
        sospecha_diagnostica=sospecha_diagnostica,
        generado_en=ahora,
        estudios_sugeridos=tuple(sugeridos),
        estudios_omitidos_por_redundantes=tuple(omitidos),
    )
