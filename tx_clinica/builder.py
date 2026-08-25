"""TX-01 — Construcción de recomendaciones de tratamiento (punto de entrada).

Decisión de diseño confirmada (Opción A): las reglas computables de
guidelines/ están escritas para auditar concordancia ("¿lo ya prescrito
es correcto?"), no para generar sugerencias desde cero — muchas exigen
prescribed_antineoplastic_drugs o prescribed_regimen_id ya poblados. En
vez de reescribir esas reglas ya validadas con casos sintéticos, este
módulo evalúa cada régimen conocido de regimens.yaml de forma
HIPOTÉTICA: "¿el rule-set respaldaría este régimen SI fuera el
prescrito, dado el estadio/biomarcadores reales de este paciente?",
usando core.engine.evaluate_rule_set_hypothetical.

Ningún régimen se inventa: solo se consideran los que ya existen en
regimens.yaml del módulo. Ninguna regla se reescribe.

--------------------------------------------------------------------
Formatos de regimens.yaml soportados (confirmado contra las 9 guías reales)
--------------------------------------------------------------------
regimens.yaml varía de estructura entre módulos:
  - lista de dicts con `includes: [...]`               (breast_early_tnbc,
                                                          breast_metastatic_tnbc,
                                                          uveal_melanoma)
  - dict keyed por regimen_id con `components: [...]`  (cutaneous_melanoma,
                                                          renal_cell_carcinoma_*)
  - dict keyed por regimen_id con
    `matching.all_of` / `matching.exact_antineoplastic_set` /
    `matching.one_of` / `matching.contains`             (nsclc_early_locally_advanced,
                                                          nsclc_metastatic_non_oncogene)
El extractor de abajo reconoce estas variantes por orden de prioridad. Si
un régimen no da match en NINGUNA forma conocida, se excluye del
resultado (con motivo registrado) en vez de adivinar su composición —
mismo principio que el resto del proyecto ante datos ambiguos.

--------------------------------------------------------------------
Clasificación de audit_effect (confirmado contra las 9 guías reales)
--------------------------------------------------------------------
Las reglas de guidelines/ usan varios valores de audit_effect, no solo
"supports_prescription". Un candidato hipotético puede toparse con
cualquiera de ellos al evaluar TODAS las reglas del módulo (no solo la
primera que matchee):
  - supports_prescription           -> régimen respaldado (positivo)
  - opposes_prescription            -> régimen explícitamente contraindicado
  - potential_deviation             -> igual de negativo que lo anterior,
                                        mismo tratamiento
  - requires_clinical_review        -> régimen posible pero necesita revisión
  - not_evaluable (como audit_effect de una regla, no solo como status
    del motor por dato faltante) -> el dato está presente pero la guía
                                     dice que ese valor no permite decidir
                                     (ej. HLA no testeado en uveal melanoma)
  - advisory / none / outside_scope -> no participan en la clasificación
    de un candidato de tratamiento; son ruido de continuidad/alcance de
    módulo, no una respuesta a "¿se sugiere este régimen?"

Si CUALQUIER regla negativa explícita (opposes_prescription o
potential_deviation) se dispara para un régimen, ese régimen NUNCA se
presenta como candidato positivo — se descarta del todo. Esto es
deliberadamente conservador: más vale omitir un régimen que presentarlo
como sugerencia cuando la propia guía dice lo contrario en otra de sus
reglas.

Alcance actualmente confirmado: la advertencia explícita de
"contraindicado con warning visible" para COMORBILIDADES (distinto de
las contraindicaciones explícitas de arriba, que sí vienen de reglas
propias) queda PENDIENTE para una iteración posterior — ver
README_TX01_TX02.md. Hoy, si una comorbilidad hace que una condición de
entrada de una regla positiva no se cumpla (sin que exista una regla de
exclusión separada para ese caso), el régimen simplemente no aparece
como candidato, sin aviso adicional. Es una limitación conocida y
documentada, no un comportamiento oculto.
"""

from __future__ import annotations

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


def _evaluar_regimen_hipotetico(
    module_folder: Path,
    archivos_regla: list[str],
    facts_paciente: dict[str, Any],
    regimen: dict[str, Any],
) -> Optional[RegimenCandidato]:
    """Evalúa un régimen hipotético contra TODOS los rule-sets del módulo.

    Revisa cada regla aplicable (no se detiene en la primera positiva),
    porque una regla de exclusión en otro archivo puede contradecir una
    regla positiva de otro. Cualquier audit_effect negativo explícito
    descarta el régimen por completo.
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

            # Si la regla nombra explícitamente un régimen concreto en su
            # conclusión, esa es la respuesta autoritativa -- si no
            # coincide con el régimen que estamos probando ahora, esta
            # regla NO es sobre este régimen (aunque sus demás
            # condiciones -- estadio, fase, elegibilidad -- sí se
            # cumplan). Evita atribuir candidatos falsos cuando la regla
            # no condiciona sobre fármacos en absoluto.
            regimenes_referenciados = _regimenes_referenciados_en_conclusion(conclusion)
            if regimenes_referenciados and regimen_id not in regimenes_referenciados:
                continue

            if audit_effect in _EFECTOS_NEGATIVOS_EXPLICITOS:
                # Contraindicación explícita en cualquier archivo del
                # módulo: el régimen se descarta por completo, sin
                # importar qué más haya dicho otra regla.
                return None
            if audit_effect in _EFECTOS_POSITIVOS and mejor_positivo is None:
                mejor_positivo = (evaluacion, archivo)
            elif audit_effect in _EFECTOS_REVISION and mejor_revision is None:
                mejor_revision = (evaluacion, archivo)
            elif audit_effect in _EFECTOS_NO_EVALUABLE and mejor_no_evaluable is None:
                mejor_no_evaluable = (evaluacion, archivo)

    elegido, archivo_elegido, audit_effect_final = None, None, None
    if mejor_positivo is not None:
        elegido, archivo_elegido = mejor_positivo
        audit_effect_final = "supports_prescription"
    elif mejor_revision is not None:
        elegido, archivo_elegido = mejor_revision
        audit_effect_final = "requires_clinical_review"
    elif mejor_no_evaluable is not None:
        elegido, archivo_elegido = mejor_no_evaluable
        audit_effect_final = "not_evaluable"
    else:
        return None

    evidencia = obtener_evidencia_regla(module_folder, archivo_elegido, elegido.rule_id)
    return RegimenCandidato(
        regimen_id=regimen_id,
        fase=str(fase or ""),
        farmacos=tuple(farmacos),
        rule_id_disparada=elegido.rule_id,
        archivo_regla=archivo_elegido,
        audit_effect=audit_effect_final,
        field_ids_usados=tuple(
            k for k in facts_paciente
            if k not in ("prescribed_antineoplastic_drugs", "prescribed_regimen_id", "treatment_phase", "treatment_line")
        ),
        evidencia=evidencia,
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
    # línea; luego las que requieren revisión; luego las no evaluables.
    # Dentro de cada grupo, se conserva el orden de regimens.yaml (que ya
    # refleja el orden clínico del módulo). Nunca se ordena por un score
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