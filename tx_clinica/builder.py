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
    """Descubre qué YAML del módulo son rule-sets (tienen clave 'rules').

    Confirmado contra la estructura real del repo: las reglas viven en
    una subcarpeta ``rules/`` dentro de cada módulo (ej.
    ``guidelines/breast_early_tnbc/rules/adjuvant.yaml``), mientras que
    ``metadata.yaml``/``regimens.yaml``/``variables.yaml``/``pathway.yaml``
    están directo en la carpeta del módulo. Se busca ahí en vez de en la
    raíz del módulo.

    Se descubre por contenido (no se hardcodean nombres) porque cada
    módulo tiene un conjunto distinto de archivos de reglas
    (first_line.yaml/subsequent_line.yaml en unos, neoadjuvant.yaml/
    adjuvant.yaml/perioperative.yaml en otros, routing.yaml/
    sequencing.yaml en el módulo oncogene-addicted, localized.yaml/
    metastatic.yaml en uveal melanoma, etc.).

    Devuelve rutas relativas a module_folder (ej. "rules/adjuvant.yaml"),
    no solo el nombre de archivo, para que el resto del código
    (module_folder / archivo) siga funcionando sin más cambios.
    """
    rules_dir = module_folder / "rules"
    if not rules_dir.exists():
        return []

    archivos = []
    for path in sorted(rules_dir.glob("*.yaml")):
        payload = _leer_yaml(path)
        if isinstance(payload, dict) and isinstance(payload.get("rules"), list):
            archivos.append(f"rules/{path.name}")
    return archivos


# ---------------------------------------------------------------------
# Extractor tolerante de regímenes: normaliza los formatos de
# regimens.yaml vistos en las 9 guías reales sin interpretar la lógica
# de matching (esa es para auditoría; aquí solo se necesita saber qué
# fármacos y qué fase tiene el régimen, para poder inyectarlos como
# hipótesis).
# ---------------------------------------------------------------------

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
    """regimens.yaml es a veces una lista, a veces un dict keyed por id."""
    regimenes = payload.get("regimens", [])
    if isinstance(regimenes, dict):
        for regimen_id, regimen in regimenes.items():
            yield {**regimen, "id": regimen.get("id", regimen_id)}
    else:
        yield from regimenes


# ---------------------------------------------------------------------
# Evaluación hipotética de un régimen contra todo el rule-set del módulo
# ---------------------------------------------------------------------

#: Llaves de conclusion.* que nombran explícitamente uno o más régimenes
#: concretos. Algunas reglas de secuencia usan más de una (inducción +
#: mantenimiento) -- una regla puede referenciar varios régimenes
#: válidos a la vez, no solo uno.
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
    """Corre el régimen (vía overrides) contra TODOS los rule-sets del
    módulo y clasifica el mejor resultado encontrado. No decide todavía
    si hay que armar un RegimenCandidato -- eso lo hace quien llama, para
    poder reusar esta función tanto en la corrida normal como en la
    contrafactual de comorbilidad.
    """
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
    """Devuelve (variable, valor_real) de la PRIMERA variable de
    contraindicación de ICI presente en los facts reales del paciente
    con un valor que SÍ representa contraindicación. None si no hay
    ninguna."""
    todas = _comorbilidades_bloqueantes(facts_paciente)
    return todas[0] if todas else None


def _comorbilidades_bloqueantes(facts_paciente: dict[str, Any]) -> list[tuple[str, Any]]:
    """Todas las variables de contraindicación de ICI presentes en los
    facts reales con un valor que representa contraindicación (no solo
    la primera) -- necesario para el chequeo de "¿la regla que califica
    a este régimen revisó ESTA variable en particular?", porque un
    paciente puede tener varias comorbilidades activas y la regla puede
    cubrir solo algunas."""
    resultado = []
    for variable, valor_sin_contraindicacion in _VARIABLES_CONTRAINDICACION_ICI.items():
        valor_real = facts_paciente.get(variable)
        if valor_real is not None and valor_real != valor_sin_contraindicacion:
            resultado.append((variable, valor_real))
    return resultado


def _campos_de_condicion(condition: dict[str, Any]) -> set[str]:
    """Recorre recursivamente un árbol de condiciones (all/any/not/field)
    y devuelve todos los nombres de campo que la regla realmente revisa.
    Mismo árbol que evalúa core.engine, pero aquí solo se extraen los
    nombres de campo, no se evalúa nada."""
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
    árbol de condiciones crudo del YAML. Se usa para distinguir "la
    regla revisó esta comorbilidad y decidió que no importa" (nada que
    hacer) de "la regla nunca preguntó por esta comorbilidad en
    absoluto" (silencio, no una decisión -- amerita advertencia)."""
    payload = _leer_yaml(module_folder / archivo) or {}
    for regla in payload.get("rules", []):
        if regla.get("id") == rule_id:
            return _campos_de_condicion(regla.get("conditions") or {})
    return set()


def _comorbilidad_no_evaluada_por_regla(
    facts_paciente: dict[str, Any], campos_regla: set[str]
) -> Optional[tuple[str, Any]]:
    """De todas las comorbilidades bloqueantes del paciente, la primera
    que la regla ganadora NUNCA menciona en sus condiciones -- es decir,
    una contraindicación real que nadie verificó, no una que la regla ya
    revisó y descartó."""
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
    return RegimenCandidato(
        regimen_id=regimen_id,
        fase=str(fase or ""),
        farmacos=tuple(farmacos),
        rule_id_disparada=resultado.evaluacion.rule_id,
        archivo_regla=resultado.archivo,
        audit_effect=audit_effect_final,
        field_ids_usados=tuple(
            k for k in facts_paciente
            if k not in ("prescribed_antineoplastic_drugs", "prescribed_regimen_id", "treatment_phase", "treatment_line")
        ),
        evidencia=evidencia,
        advertencia_comorbilidad=advertencia_comorbilidad,
    )


def _evaluar_regimen_hipotetico(
    module_folder: Path,
    archivos_regla: list[str],
    facts_paciente: dict[str, Any],
    regimen: dict[str, Any],
) -> Optional[RegimenCandidato]:
    """Evalúa un régimen hipotético contra TODOS los rule-sets del módulo.

    Si el régimen no calificaría por una comorbilidad de contraindicación
    de ICI (y no por una contraindicación explícita de otra regla),
    reintenta contrafactualmente sin esa comorbilidad -- ver docstring
    del módulo, sección "Advertencia de comorbilidad".
    """
    farmacos = _extraer_farmacos(regimen)
    if farmacos is None:
        # Formato de regimen no reconocido: se excluye, no se adivina.
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
        # Antes de darlo por bueno como primera línea sin más: ¿la regla
        # que lo respalda revisó TODAS las comorbilidades bloqueantes
        # que el paciente tiene? Si el paciente tiene una contraindicación
        # de ICI que esta regla en particular nunca menciona en sus
        # condiciones, el silencio de la regla sobre esa variable no es
        # una decisión clínica -- es que nadie la verificó. Se degrada
        # con advertencia en vez de presentarlo como primera línea sin
        # reservas (caso real confirmado: ESMO-NSCLC-M-FL-001 no revisa
        # major_comorbidity_precluding_ici, solo immunotherapy_contraindication).
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

    # resultado.tipo == "ninguno": el régimen no calificó con los facts
    # reales. Antes de descartarlo, revisar si la causa es una
    # comorbilidad de contraindicación de ICI -- si sin ella SÍ
    # calificaría como primera línea, se presenta con advertencia en vez
    # de desaparecer en silencio (criterio de aceptación #2 de TX-01).
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
        # Ni siquiera sin la comorbilidad calificaría -- no es un caso de
        # "comorbilidad bloqueó primera línea", es que el régimen
        # genuinamente no aplica por otras razones. No se fuerza nada.
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


def construir_recomendaciones_tratamiento(
    patient_id: int,
    facts_paciente: dict[str, Any],
    guidelines_root: Path,
    ahora: Optional[datetime] = None,
) -> ResultadoRecomendacionTratamiento:
    """Genera las opciones de tratamiento sugeridas para un paciente.

    facts_paciente debe seguir el vocabulario de variables.yaml del
    módulo aplicable (estadio, biomarcadores, ECOG, etc.) — construido
    por quien llama (ver tx_clinica/patient_facts.py) a partir de
    historia_clinica_mock.
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

    # Orden explicable: primero las que sí se respaldan como primera
    # línea; luego las que requieren revisión (incluye las de
    # comorbilidad); luego las no evaluables. Dentro de cada grupo, se
    # conserva el orden de regimens.yaml. Nunca se ordena por un score
    # inventado.
    orden_prioridad = {"supports_prescription": 0, "requires_clinical_review": 1, "not_evaluable": 2}
    candidatos.sort(key=lambda c: orden_prioridad.get(c.audit_effect, 3))

    return ResultadoRecomendacionTratamiento(
        patient_id=patient_id,
        module_id=module_folder_name,
        generado_en=ahora or datetime.now(),
        candidatos=tuple(candidatos),
        sin_guia_aplicable=False,
    )