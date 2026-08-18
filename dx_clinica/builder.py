"""Construcción del resultado de diagnóstico diferencial (punto de entrada de DX-02)."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Sequence

from historia_clinica_mock.repository import HallazgoClinico, Paciente

from dx_clinica.evidence import evidencia_por_diagnostico_principal, obtener_evidencia
from dx_clinica.knowledge_base import CATALOGO_DIAGNOSTICO_DIFERENCIAL, PerfilDiagnostico
from dx_clinica.matcher import coincide_sin_negacion
from dx_clinica.models import (
    SIN_SUSTENTO_SUFICIENTE,
    CriterioEvaluado,
    DiagnosticoDiferencialCandidato,
    ResultadoDiagnosticoDiferencial,
)


def _evaluar_perfil(perfil: PerfilDiagnostico, hallazgos: Sequence[HallazgoClinico]):
    criterios_sustentados = []
    criterios_sin_sustento = []

    for criterio in perfil.criterios:
        hallazgos_ids = tuple(
            hallazgo.id for hallazgo in hallazgos if coincide_sin_negacion(hallazgo.texto, criterio.palabras_clave)
        )
        if hallazgos_ids:
            criterios_sustentados.append(
                CriterioEvaluado(id=criterio.id, descripcion=criterio.descripcion, hallazgos_ids=hallazgos_ids)
            )
        else:
            criterios_sin_sustento.append(criterio.descripcion)

    return criterios_sustentados, criterios_sin_sustento


def _resolver_evidencia(perfil: PerfilDiagnostico, paciente: Optional[Paciente]):
    if perfil.evidencia_dinamica:
        diagnostico = paciente.diagnostico_principal if paciente else None
        return evidencia_por_diagnostico_principal(diagnostico)
    if perfil.evidencia_module_folder:
        return obtener_evidencia(perfil.evidencia_module_folder)
    return None


def construir_diagnosticos_diferenciales(
    paciente: Optional[Paciente],
    hallazgos: List[HallazgoClinico],
    catalogo: Sequence[PerfilDiagnostico] = CATALOGO_DIAGNOSTICO_DIFERENCIAL,
    ahora: Optional[datetime] = None,
) -> ResultadoDiagnosticoDiferencial:
    """Genera la lista priorizada de diagnósticos diferenciales para un paciente.

    Un perfil del catálogo solo se incluye en el resultado si al menos uno
    de sus criterios está sustentado por un hallazgo real (nunca se
    incluye una alternativa "en blanco"). La prioridad es el número de
    criterios sustentados (orden explicable), nunca un porcentaje ni una
    probabilidad calculada.
    """

    candidatos_evaluados = []

    for perfil in catalogo:
        criterios_sustentados, criterios_sin_sustento = _evaluar_perfil(perfil, hallazgos)
        if not criterios_sustentados:
            # Sin ningún criterio sustentado por un hallazgo real: esta
            # alternativa no se incluye. No se "rellena" con un criterio
            # inventado ni se incluye "por si acaso".
            continue
        evidencia = _resolver_evidencia(perfil, paciente)
        candidatos_evaluados.append((perfil, criterios_sustentados, criterios_sin_sustento, evidencia))

    # Orden explicable: más criterios sustentados primero; en empate,
    # perfiles con menos criterios totales quedan primero (una alternativa
    # que cumple 1 de 1 criterio es más específica que una que cumple 1 de 3).
    candidatos_evaluados.sort(
        key=lambda item: (-len(item[1]), len(item[1]) + len(item[2]))
    )

    candidatos = tuple(
        DiagnosticoDiferencialCandidato(
            perfil_id=perfil.id,
            nombre=perfil.nombre,
            orden=indice + 1,
            criterios_sustentados=tuple(criterios_sustentados),
            criterios_sin_sustento=tuple(criterios_sin_sustento),
            evidencia=evidencia,
        )
        for indice, (perfil, criterios_sustentados, criterios_sin_sustento, evidencia) in enumerate(candidatos_evaluados)
    )

    advertencia = None if candidatos else SIN_SUSTENTO_SUFICIENTE

    return ResultadoDiagnosticoDiferencial(
        paciente_id=paciente.id if paciente else -1,
        generado_en=ahora or datetime.now(),
        candidatos=candidatos,
        advertencia_sin_sustento=advertencia,
    )
