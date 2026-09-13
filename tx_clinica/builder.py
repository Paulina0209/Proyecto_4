from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml

from core.engine import RuleEvaluation, evaluate_rule_set_hypothetical
from tx_clinica.evidence import obtener_evidencia_regla
from tx_clinica.models import RegimenCandidato, ResultadoRecomendacionTratamiento
from tx_clinica.module_selector import seleccionar_modulo

#: Llaves de metadata.yaml de módulo que no son archivos de rule-set y
#: deben excluirse al descubrir qué YAML del módulo contienen reglas.
_ARCHIVOS_NO_RULESET = {"metadata.yaml", "regimens.yaml", "variables.yaml", "pathway.yaml"}

#: Clasificación de audit_effect, confirmada contra las 9 guías reales.
_EFECTOS_POSITIVOS = {"supports_prescription"}
_EFECTOS_NEGATIVOS_EXPLICITOS = {"opposes_prescription", "potential_deviation"}
_EFECTOS_REVISION = {"requires_clinical_review"}
_EFECTOS_NO_EVALUABLE = {"not_evaluable"}
# advisory, none, outside_scope: deliberadamente no clasificados; no
# participan en si un régimen es o no un candidato de tratamiento.

#: Variables que, en al menos un módulo real, representan contraindicación
#: de inmunoterapia (ICI) por comorbilidad/toxicidad -- confirmadas contra
#: las 9 guías reales. El valor es el que representa "SIN contraindicación"
#: para esa variable (las escalas no son uniformes: unas son yes/no, otras
#: excessive/not_excessive, otra tiene 5 valores categóricos).
_VARIABLES_CONTRAINDICACION_ICI: dict[str, str] = {
    "major_comorbidity_precluding_ici": "no",
    "immunotherapy_contraindication": "no",
    "immune_checkpoint_inhibitor_contraindication": "no",
    "immune_checkpoint_inhibitor_toxicity_risk": "not_excessive",
    "ici_suitability": "eligible",
}


@dataclass(frozen=True)
class _ResultadoEvaluacion:
    """Resultado interno de probar un régimen contra un rule-set completo."""

    tipo: str  # "positivo" | "revision" | "no_evaluable" | "negativo" | "ninguno"
    evaluacion: Optional[RuleEvaluation] = None
    archivo: Optional[str] = None


def _leer_yaml(path: Path) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8-sig") as f:
        return yaml.safe_load(f)


def _archivos_rule_set(module_folder: Path) -> list[str]:
    """Descubre qué YAML del módulo son rule-sets (tienen clave 'rules')."""
    rules_dir = module_folder / "rules"
    if not rules_dir.exists():
        return []

    archivos = []
    for path in sorted(rules_dir.glob("*.yaml")):
        payload = _leer_yaml(path)
        if isinstance(payload, dict) and isinstance(payload.get("rules"), list):
            archivos.append(f"rules/{path.name}")
    return archivos


_LLAVES_FARMACOS_CONOCIDAS: tuple[Any, ...] = (
    "includes",
    "components",
    "components_or_class_members",
    ("matching", "exact_antineoplastic_set"),
    ("matching", "all_of"),
    ("matching", "contains"),
)
_LLAVES_FASE_CONOCIDAS = ("phase", "treatment_phase")


def _extraer_farmacos(regimen: dict[str, Any]) -> Optional[list[str]]:
    for llave in _LLAVES_FARMACOS_CONOCIDAS:
        if isinstance(llave, tuple):
            valor = (regimen.get(llave[0]) or {}).get(llave[1])
        else:
            valor = regimen.get(llave)
        if valor:
            return list(valor)
    return None


def _extraer_fase(regimen: dict[str, Any]) -> Optional[str]:
    for llave in _LLAVES_FASE_CONOCIDAS:
        if regimen.get(llave):
            return regimen[llave]
    return None


def _iterar_regimenes(payload: dict[str, Any]):
    regimenes = payload.get("regimens", [])
    if isinstance(regimenes, dict):
        for regimen_id, regimen in regimenes.items():
            yield {**regimen, "id": regimen.get("id", regimen_id)}
    else:
        yield from regimenes


_LLAVES_REGIMEN_EN_CONCLUSION = (
    "regimen_id",
    "sequence_regimen_id",
    "regimen_class_id",
    "induction_regimen_id",
    "maintenance_regimen_id",
    "post_surgery_regimen_id",
)


def _regimenes_referenciados_en_conclusion(conclusion: dict[str, Any]) -> set[str]:
    referenciados = set()
    for llave in _LLAVES_REGIMEN_EN_CONCLUSION:
        valor = conclusion.get(llave)
        if valor:
            referenciados.add(valor)
    return referenciados


def _evaluaciones_para_archivo(
    module_folder: Path, archivo: str, facts_paciente: dict[str, Any], overrides: dict[str, Any]
) -> list[RuleEvaluation]:
    return evaluate_rule_set_hypothetical(module_folder / archivo, facts_paciente, overrides)


def _buscar_mejor_evaluacion(
    module_folder: Path,
    archivos_regla: list[str],
    facts_paciente: dict[str, Any],
    overrides: dict[str, Any],
    regimen_id: str,
) -> _ResultadoEvaluacion:
    mejor_positivo: Optional[tuple[RuleEvaluation, str]] = None
    mejor_revision: Optional[tuple[RuleEvaluation, str]] = None
    mejor_no_evaluable: Optional[tuple[RuleEvaluation, str]] = None

    for archivo in archivos_regla:
        evaluaciones = _evaluaciones_para_archivo(module_folder, archivo, facts_paciente, overrides)
        for evaluacion in evaluaciones:
            if evaluacion.status != "applicable":
                continue
            conclusion = evaluacion.conclusion or {}
            audit_effect = conclusion.get("audit_effect")

            regimenes_referenciados = _regimenes_referenciados_en_conclusion(conclusion)
            if regimenes_referenciados and regimen_id not in regimenes_referenciados:
                continue

            if audit_effect in _EFECTOS_NEGATIVOS_EXPLICITOS:
                return _ResultadoEvaluacion(tipo="negativo")
            if audit_effect in _EFECTOS_POSITIVOS and mejor_positivo is None:
                mejor_positivo = (evaluacion, archivo)
            elif audit_effect in _EFECTOS_REVISION and mejor_revision is None:
                mejor_revision = (evaluacion, archivo)
            elif audit_effect in _EFECTOS_NO_EVALUABLE and mejor_no_evaluable is None:
                mejor_no_evaluable = (evaluacion, archivo)

    if mejor_positivo is not None:
        evaluacion, archivo = mejor_positivo
        return _ResultadoEvaluacion(tipo="positivo", evaluacion=evaluacion, archivo=archivo)
    if mejor_revision is not None:
        evaluacion, archivo = mejor_revision
        return _ResultadoEvaluacion(tipo="revision", evaluacion=evaluacion, archivo=archivo)
    if mejor_no_evaluable is not None:
        evaluacion, archivo = mejor_no_evaluable
        return _ResultadoEvaluacion(tipo="no_evaluable", evaluacion=evaluacion, archivo=archivo)
    return _ResultadoEvaluacion(tipo="ninguno")


def _detectar_comorbilidad_bloqueante(facts_paciente: dict[str, Any]) -> Optional[tuple[str, Any]]:
    todas = _comorbilidades_bloqueantes(facts_paciente)
    return todas[0] if todas else None


def _comorbilidades_bloqueantes(facts_paciente: dict[str, Any]) -> list[tuple[str, Any]]:
    resultado = []
    for variable, valor_sin_contraindicacion in _VARIABLES_CONTRAINDICACION_ICI.items():
        valor_real = facts_paciente.get(variable)
        if valor_real is not None and valor_real != valor_sin_contraindicacion:
            resultado.append((variable, valor_real))
    return resultado


def _campos_de_condicion(condition: dict[str, Any]) -> set[str]:
    campos: set[str] = set()
    if "all" in condition:
        for hijo in condition["all"]:
            campos |= _campos_de_condicion(hijo)
    elif "any" in condition:
        for hijo in condition["any"]:
            campos |= _campos_de_condicion(hijo)
    elif "not" in condition:
        campos |= _campos_de_condicion(condition["not"])
    elif "field" in condition:
        campos.add(condition["field"])
    return campos


def _campos_referenciados_por_regla(module_folder: Path, archivo: str, rule_id: str) -> set[str]:
    """Qué variables revisa realmente una regla concreta, leyendo el
    árbol de condiciones crudo del YAML. Se usa tanto para el chequeo de
    cobertura de comorbilidad como (ahora, tras la revisión) para poblar
    field_ids_usados con precisión -- ver nota en _construir_candidato."""
    payload = _leer_yaml(module_folder / archivo) or {}
    for regla in payload.get("rules", []):
        if regla.get("id") == rule_id:
            return _campos_de_condicion(regla.get("conditions") or {})
    return set()


def _comorbilidad_no_evaluada_por_regla(
    facts_paciente: dict[str, Any], campos_regla: set[str]
) -> Optional[tuple[str, Any]]:
    for variable, valor_real in _comorbilidades_bloqueantes(facts_paciente):
        if variable not in campos_regla:
            return variable, valor_real
    return None


def _construir_candidato(
    module_folder: Path,
    regimen_id: str,
    fase: Optional[str],
    farmacos: list[str],
    facts_paciente: dict[str, Any],
    resultado: _ResultadoEvaluacion,
    audit_effect_final: str,
    advertencia_comorbilidad: Optional[str] = None,
) -> RegimenCandidato:
    evidencia = obtener_evidencia_regla(module_folder, resultado.archivo, resultado.evaluacion.rule_id)

    # CORREGIDO (revisión previa al refactor): antes field_ids_usados era
    # "todos los facts del paciente salvo 4 llaves fijas" -- en la
    # práctica, casi todo el diccionario. Ahora es exactamente el
    # conjunto de campos que la regla GANADORA evaluó en su árbol de
    # conditions, leído del YAML crudo (mismo mecanismo que ya existía
    # para el chequeo de cobertura de comorbilidad, solo que antes no se
    # reutilizaba aquí). Esto es lo que explainability_adapter.py usa
    # para decidir qué datos del paciente mostrarle al oncólogo como "en
    # qué se basó la recomendación" -- con el valor viejo, mostraba
    # prácticamente todos los datos clínicos del paciente como
    # "considerados", no solo los que la regla realmente miró.
    campos_regla = _campos_referenciados_por_regla(module_folder, resultado.archivo, resultado.evaluacion.rule_id)
    field_ids_usados = tuple(k for k in facts_paciente if k in campos_regla)

    return RegimenCandidato(
        regimen_id=regimen_id,
        fase=str(fase or ""),
        farmacos=tuple(farmacos),
        rule_id_disparada=resultado.evaluacion.rule_id,
        archivo_regla=resultado.archivo,
        audit_effect=audit_effect_final,
        field_ids_usados=field_ids_usados,
        evidencia=evidencia,
        advertencia_comorbilidad=advertencia_comorbilidad,
    )


def _evaluar_regimen_hipotetico(
    module_folder: Path,
    archivos_regla: list[str],
    facts_paciente: dict[str, Any],
    regimen: dict[str, Any],
) -> Optional[RegimenCandidato]:
    farmacos = _extraer_farmacos(regimen)
    if farmacos is None:
        return None

    regimen_id = regimen.get("id")
    fase = _extraer_fase(regimen)

    overrides: dict[str, Any] = {
        "prescribed_antineoplastic_drugs": farmacos,
        "prescribed_regimen_id": regimen_id,
    }
    if fase is not None:
        overrides["treatment_phase"] = fase
    if "treatment_line" in regimen:
        overrides["treatment_line"] = regimen["treatment_line"]

    resultado = _buscar_mejor_evaluacion(module_folder, archivos_regla, facts_paciente, overrides, regimen_id)

    if resultado.tipo == "negativo":
        return None
    if resultado.tipo == "positivo":
        campos_regla = _campos_referenciados_por_regla(module_folder, resultado.archivo, resultado.evaluacion.rule_id)
        comorbilidad_ignorada = _comorbilidad_no_evaluada_por_regla(facts_paciente, campos_regla)
        if comorbilidad_ignorada is not None:
            variable, valor_real = comorbilidad_ignorada
            advertencia = (
                f"El paciente tiene {variable}={valor_real!r} (comorbilidad que contraindica "
                f"inmunoterapia), pero la regla {resultado.evaluacion.rule_id} que respalda este "
                f"régimen no evalúa esa variable en sus condiciones -- nadie la verificó. "
                f"Requiere revisión clínica antes de presentarse como primera línea."
            )
            return _construir_candidato(
                module_folder, regimen_id, fase, farmacos, facts_paciente,
                resultado, "requires_clinical_review", advertencia_comorbilidad=advertencia,
            )
        return _construir_candidato(module_folder, regimen_id, fase, farmacos, facts_paciente, resultado, "supports_prescription")
    if resultado.tipo == "revision":
        return _construir_candidato(module_folder, regimen_id, fase, farmacos, facts_paciente, resultado, "requires_clinical_review")
    if resultado.tipo == "no_evaluable":
        return _construir_candidato(module_folder, regimen_id, fase, farmacos, facts_paciente, resultado, "not_evaluable")

    comorbilidad = _detectar_comorbilidad_bloqueante(facts_paciente)
    if comorbilidad is None:
        return None

    variable, valor_real = comorbilidad
    valor_sin_contraindicacion = _VARIABLES_CONTRAINDICACION_ICI[variable]
    facts_sin_comorbilidad = {**facts_paciente, variable: valor_sin_contraindicacion}

    resultado_contrafactual = _buscar_mejor_evaluacion(
        module_folder, archivos_regla, facts_sin_comorbilidad, overrides, regimen_id
    )
    if resultado_contrafactual.tipo != "positivo":
        return None

    advertencia = (
        f"Este régimen calificaría como primera línea, pero el paciente tiene "
        f"{variable}={valor_real!r}, lo que contraindica inmunoterapia según la guía. "
        f"Requiere revisión clínica antes de presentarse como primera línea."
    )
    return _construir_candidato(
        module_folder, regimen_id, fase, farmacos, facts_paciente,
        resultado_contrafactual, "requires_clinical_review", advertencia_comorbilidad=advertencia,
    )


def obtener_farmacos_de_regimen(module_folder: Path, regimen_id: str) -> Optional[list[str]]:
    """Devuelve la lista de fármacos de un régimen conocido de
    regimens.yaml, o None si el régimen no existe en ese módulo o su
    formato no se reconoce. Usado por tools/interaction_tools.py (TX-03)
    para saber qué fármacos chequear contra la medicación concomitante,
    sin duplicar el extractor tolerante de regimens.yaml."""
    payload = _leer_yaml(module_folder / "regimens.yaml") or {}
    for regimen in _iterar_regimenes(payload):
        if regimen.get("id") == regimen_id:
            return _extraer_farmacos(regimen)
    return None


def construir_recomendaciones_tratamiento(
    patient_id: Optional[int],
    facts_paciente: dict[str, Any],
    guidelines_root: Path,
    ahora: Optional[datetime] = None,
) -> ResultadoRecomendacionTratamiento:
    """Genera las opciones de tratamiento sugeridas para un paciente.

    Nota (post-refactor): esta función sigue resolviendo el módulo con
    seleccionar_modulo (sin distinguir "no aplica" de "falta un dato"),
    sin cambios de comportamiento respecto a la versión anterior. Esa
    distinción (Fase 1 de la recomendación) vive un nivel más arriba, en
    tx_clinica.tools.recommendation_tools, usando
    module_selector.seleccionar_modulo_con_diagnostico ANTES de llegar
    hasta aquí -- para cuando esta función se invoca, ya se confirmó que
    hay un módulo resuelto con los datos disponibles.
    """
    module_folder_name = seleccionar_modulo(facts_paciente, guidelines_root)
    if module_folder_name is None:
        return ResultadoRecomendacionTratamiento(
            patient_id=patient_id,
            module_id=None,
            generado_en=ahora or datetime.now(),
            candidatos=(),
            sin_guia_aplicable=True,
        )

    module_folder = guidelines_root / module_folder_name
    regimens_payload = _leer_yaml(module_folder / "regimens.yaml") or {}
    archivos_regla = _archivos_rule_set(module_folder)

    candidatos = []
    for regimen in _iterar_regimenes(regimens_payload):
        candidato = _evaluar_regimen_hipotetico(module_folder, archivos_regla, facts_paciente, regimen)
        if candidato is not None:
            candidatos.append(candidato)

    orden_prioridad = {"supports_prescription": 0, "requires_clinical_review": 1, "not_evaluable": 2}
    candidatos.sort(key=lambda c: orden_prioridad.get(c.audit_effect, 3))

    return ResultadoRecomendacionTratamiento(
        patient_id=patient_id,
        module_id=module_folder_name,
        generado_en=ahora or datetime.now(),
        candidatos=tuple(candidatos),
        sin_guia_aplicable=False,
    )
