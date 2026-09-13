"""construir_chequeo_interacciones() — historia de interacciones/
contraindicaciones farmacológicas (TX-03).

Reutiliza el mismo mecanismo de evaluación hipotética que tx_clinica usa
para TX-01/TX-02 (evaluate_rule_set_hypothetical), pero el contenido de
reglas NO vive en guidelines/ -- vive dentro de este mismo paquete, en
docs/rules_interacciones/<modulo_id>.yaml (uno por módulo). Decisión
explícita del usuario: no tocar guidelines/ para nada, aunque el
mecanismo (all/any/not, evaluate_rule_set_hypothetical) sea el mismo.

Esto hace que este módulo sea completamente autosuficiente: no necesita
que nadie le pase guidelines_root ni la lista cruda de reglas -- las
resuelve solo, a partir del modulo_guia.

No se modifica core/engine.py. El "evaluador" se recibe como parámetro
inyectable para poder testear este módulo de forma autocontenida (mismo
criterio que tx_clinica/tests/test_builder.py), y por defecto intenta
importar el real de core.engine cuando este paquete se pega en el repo.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from .interaction_mapping import mapear_medicacion_actual_a_variables
from .models import InteraccionDetectada, ResultadoChequeoInteracciones

try:  # pragma: no cover - depende del repo real
    from core.engine import evaluate_rule_set_hypothetical as _evaluador_real
except ImportError:  # pragma: no cover
    _evaluador_real = None

#: Dónde vive el contenido de interacciones -- DENTRO de este paquete,
#: no en guidelines/. Un archivo por módulo, nombrado <modulo_id>.yaml
#: (el mismo modulo_id que devuelve module_selector.seleccionar_modulo,
#: es decir, el nombre de carpeta real de guidelines/).
RUTA_REGLAS_INTERACCIONES = Path(__file__).resolve().parent / "docs" / "rules_interacciones"

#: Se devuelve en `disclaimer` cuando el módulo todavía no tiene un
#: archivo de reglas de interacciones cargado en RUTA_REGLAS_INTERACCIONES.
SIN_CONTENIDO_PARA_MODULO = "SIN_CONTENIDO_INTERACCIONES_PARA_ESTE_MODULO"

#: Se devuelve en `disclaimer` cuando modulo_guia es None (no se pudo
#: determinar ninguna guía aplicable en absoluto).
SIN_REGLAS_APLICABLES = "SIN_REGLAS_INTERACCION_APLICABLES"


def _leer_yaml(path: Path) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8-sig") as f:
        return yaml.safe_load(f)


def _campos_referenciados(conditions: dict) -> set[str]:
    """Recorre el árbol crudo de `conditions` de una regla y devuelve los
    nombres de campo que efectivamente revisa. Mismo enfoque que se usó
    para detectar el hueco de cobertura de comorbilidad en TX-01
    (capa 2), generalizado a cualquier condición anidada all/any/not.
    """
    campos: set[str] = set()
    if not isinstance(conditions, dict):
        return campos
    if "field" in conditions:
        campos.add(conditions["field"])
    for clave in ("all", "any"):
        for sub in conditions.get(clave, []) or []:
            campos |= _campos_referenciados(sub)
    if "not" in conditions and conditions["not"]:
        campos |= _campos_referenciados(conditions["not"])
    return campos


def construir_chequeo_interacciones(
    paciente_id: int,
    modulo_guia: Optional[str],
    regimen_propuesto_id: Optional[str],
    regimen_propuesto_drugs: list[str],
    medicacion_actual: list[str],
    base_facts: dict,
    evaluador_reglas: Optional[Callable] = None,
    conciliacion_medicamentos_estado: Optional[str] = None,
    ruta_reglas_interacciones: Optional[Path] = None,
) -> ResultadoChequeoInteracciones:
    """
    ruta_reglas_interacciones: override de RUTA_REGLAS_INTERACCIONES --
        SOLO para tests (apuntar a un directorio temporal). En uso real
        se omite y se usa la ruta fija dentro de este paquete.

    conciliacion_medicamentos_estado: 'no_realizada' | 'sin_medicacion_concomitante'
        | 'con_medicacion_registrada' | None. Viene de
        pacientes_clinica_extension.medicacion_actual.obtener_estado_conciliacion().
        Si es None o 'no_realizada', el resultado NUNCA puede marcar
        sin_interacciones_conocidas=True, sin importar si
        medicacion_actual llegó vacía -- una lista vacía por sí sola no
        prueba que se revisó, y "dato ausente nunca se interpreta como
        negativo" (ARCHITECTURE.md) aplica acá igual que en todo el resto
        del proyecto.
    evaluador_reglas: firma igual a evaluate_rule_set_hypothetical
        (rule_file, base_facts, fact_overrides) -> list[RuleEvaluation].
        Si no se pasa, usa el de core.engine si está disponible.
    """
    resultado = ResultadoChequeoInteracciones(
        paciente_id=paciente_id,
        modulo_guia=modulo_guia,
        regimen_evaluado=regimen_propuesto_id,
    )

    if modulo_guia is None:
        resultado.disclaimer = SIN_REGLAS_APLICABLES
        return resultado

    ruta_base = ruta_reglas_interacciones or RUTA_REGLAS_INTERACCIONES
    ruta_archivo = ruta_base / f"{modulo_guia}.yaml"

    if not ruta_archivo.exists():
        # El módulo es válido, pero todavía no tiene contenido de
        # interacciones cargado aquí -- no se inventa nada, se dice
        # explícitamente.
        resultado.disclaimer = SIN_CONTENIDO_PARA_MODULO
        return resultado

    payload = _leer_yaml(ruta_archivo) or {}
    reglas_interactions = payload.get("rules", []) or []

    evaluador = evaluador_reglas or _evaluador_real
    if evaluador is None:
        raise RuntimeError(
            "No hay evaluador de reglas disponible: pasa evaluador_reglas "
            "o instala este paquete dentro del repo real (core.engine)."
        )

    # Capa 0: ¿siquiera se revisó la medicación concomitante de este
    # paciente alguna vez? Si no, ninguna cantidad de "no encontré
    # interacciones" puede convertirse en sin_interacciones_conocidas=True.
    resultado.requiere_conciliacion_medicamentos = conciliacion_medicamentos_estado in (
        None,
        "no_realizada",
    )

    variables_medicacion, no_mapeados = mapear_medicacion_actual_a_variables(medicacion_actual)
    resultado.medicamentos_no_mapeados = no_mapeados

    overrides = {
        "prescribed_antineoplastic_drugs": regimen_propuesto_drugs,
        **variables_medicacion,
    }

    evaluaciones = evaluador(ruta_archivo, base_facts, overrides)

    for evaluacion in evaluaciones:
        # evaluacion.status es el string "applicable" / "not_applicable" /
        # "not_evaluable" del motor real (confirmado contra core/engine.py).
        if evaluacion.status != "applicable":
            continue
        conclusion = evaluacion.conclusion or {}
        resultado.interacciones.append(
            InteraccionDetectada(
                interaccion_id=conclusion.get("interaction_id", evaluacion.rule_id),
                regla_id=evaluacion.rule_id,
                severidad=conclusion.get("severity", "no_especificada"),
                audit_effect=conclusion.get("audit_effect", "informational"),
                descripcion=conclusion.get("description", ""),
                recomendacion=conclusion.get("recommendation", ""),
                fuente=conclusion.get("source", {}),
                medicamento_concomitante=conclusion.get("concomitant_drug", ""),
            )
        )

    # Capa 1: medicación activa sin traducción conocida -> no evaluado,
    # nunca "sin interacción".
    if resultado.medicamentos_no_mapeados:
        resultado.advertencia_cobertura_incompleta = True

    # Capa 2: variable de medicación mapeada que ninguna regla del
    # archivo referencia -> silencio de la regla no es una decisión.
    campos_cubiertos: set[str] = set()
    for regla in reglas_interactions:
        campos_cubiertos |= _campos_referenciados(regla.get("conditions", {}))
    variables_no_cubiertas = set(variables_medicacion) - campos_cubiertos
    if variables_no_cubiertas:
        resultado.advertencia_cobertura_incompleta = True

    resultado.sin_interacciones_conocidas = (
        not resultado.interacciones
        and not resultado.advertencia_cobertura_incompleta
        and not resultado.requiere_conciliacion_medicamentos
    )

    return resultado
