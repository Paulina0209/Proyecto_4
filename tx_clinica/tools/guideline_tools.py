from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any, Optional

import yaml
from langchain_core.tools import tool

from tx_clinica.module_selector import MODULOS_FUERA_DE_ALCANCE
from tx_clinica.tools._paths import GUIDELINES_ROOT


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.casefold()
    # Unifica separadores (espacio, guión, guión bajo) para que
    # "NSCLC metastatic non-oncogene" (lenguaje natural) sí compare
    # igual que "nsclc_metastatic_non_oncogene" (nombre real de carpeta).
    for separador in ("-", "_"):
        texto = texto.replace(separador, " ")
    return " ".join(texto.split())


def _inferir_modulo_por_contexto(consulta: str, modulos_activos: list[Path]) -> Optional[Path]:
    """Identifica módulos por contexto clínico explícito.

    Esta capa resuelve la diferencia entre el lenguaje natural del oncólogo
    y los identificadores técnicos de las carpetas, sin sustituir las reglas
    clínicas definidas en los YAML.
    """
    texto = _normalizar(consulta)
    disponibles = {p.name: p for p in modulos_activos}

    es_mama = any(t in texto for t in (
        "cancer de mama", "cancer mamario", "carcinoma de mama",
        "breast cancer", "breast",
    ))
    es_tnbc = any(t in texto for t in (
        "triple negativo", "triple negative", "tnbc",
    ))

    if not (es_mama and es_tnbc):
        return None

    es_metastatico = any(t in texto for t in (
        "metastatico", "metastatica", "metastasis",
        "metastases", "metastatic",
    ))
    es_temprano = any(t in texto for t in (
        "enfermedad temprana", "enfermedad temprano",
        "cancer temprano", "cancer temprana",
        "temprano", "temprana", "early stage", "early",
    ))

    if es_metastatico and not es_temprano:
        return disponibles.get("breast_metastatic_tnbc")

    if es_temprano and not es_metastatico:
        return disponibles.get("breast_early_tnbc")

    return None


def _leer_yaml(path: Path) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8-sig") as f:
        return yaml.safe_load(f)


def _recolectar_campos_de_condiciones(condiciones: Any) -> set[str]:
    """Recorre recursivamente un bloque `conditions` (con anidamiento
    `all`/`any`/`not`, igual que engine.py) y devuelve el conjunto de
    nombres de `field` referenciados.

    CORREGIDO tras confirmar engine.py real: antes esta función no
    manejaba `not` (a diferencia de la equivalente en builder.py, que sí
    lo hacía) -- una regla de elegibilidad con una condición `not` perdía
    esa variable como "obligatoria_para_elegibilidad" en
    listar_variables_requeridas. `not` envuelve una única sub-condición
    (un dict), no una lista, tal como hace engine.py._evaluate_condition.
    """
    campos: set[str] = set()
    if isinstance(condiciones, dict):
        campo = condiciones.get("field")
        if campo:
            campos.add(campo)
        for clave in ("all", "any"):
            if clave in condiciones:
                campos |= _recolectar_campos_de_condiciones(condiciones[clave])
        if "not" in condiciones:
            campos |= _recolectar_campos_de_condiciones(condiciones["not"])
    elif isinstance(condiciones, list):
        for item in condiciones:
            campos |= _recolectar_campos_de_condiciones(item)
    return campos


def _campos_de_elegibilidad(carpeta: Path) -> set[str]:
    """Nombres de variables que aparecen en las condiciones de reglas
    `enter_module` de rules/eligibility.yaml -- es decir, las que GATEAN
    si el módulo aplica o no, a diferencia de las que solo afinan qué
    régimen se sugiere dentro del módulo. Si falta cualquiera de estas,
    seleccionar_modulo() puede fallar en encontrar el módulo correcto
    aunque el resto de los datos clínicos estén completos."""
    payload = _leer_yaml(carpeta / "rules" / "eligibility.yaml") or {}
    campos: set[str] = set()
    for regla in payload.get("rules", []):
        conclusion = regla.get("conclusion") or {}
        if conclusion.get("action") != "enter_module":
            continue
        campos |= _recolectar_campos_de_condiciones(regla.get("conditions") or {})
    return campos


def _variables_de_modulo(carpeta: Path) -> str:
    variables_payload = _leer_yaml(carpeta / "variables.yaml") or {}
    variables = variables_payload.get("variables", {})
    campos_elegibilidad = _campos_de_elegibilidad(carpeta)

    resumen = {}
    for nombre, definicion in variables.items():
        if not isinstance(definicion, dict):
            continue
        entrada: dict[str, Any] = {"tipo": definicion.get("type")}
        if "allowed_values" in definicion:
            entrada["valores_permitidos"] = definicion["allowed_values"]
        # obligatoria_para_elegibilidad=true: si falta este campo, el
        # módulo puede no ser seleccionado del todo (sin_guia_aplicable),
        # no solo perder un candidato de régimen. Se debe preguntar
        # SIEMPRE antes de llamar a la tool de recomendación.
        entrada["obligatoria_para_elegibilidad"] = nombre in campos_elegibilidad
        resumen[nombre] = entrada

    return json.dumps(
        {
            "necesita_desambiguacion": False,
            "modulo": carpeta.name,
            "variables_disponibles": resumen,
            "nota": (
                "Las variables con obligatoria_para_elegibilidad=true determinan "
                "si este módulo de guía aplica al caso. Si falta alguna, "
                "PREGÚNTALA explícitamente antes de llamar a "
                "obtener_recomendaciones_tratamiento_con_datos -- si falta, el "
                "motor puede responder sin_guia_aplicable=true aunque el resto "
                "de los datos estén completos."
            ),
        },
        ensure_ascii=False,
    )


def _resumen_evidencia_modulo(carpeta: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    """Resumen de evidencia a nivel de módulo -- no decide nada por el
    oncólogo, solo le da contexto real (cuántas reglas hay, con qué
    respaldo) para que él elija entre módulos ambiguos con más
    información que solo el nombre."""
    source = metadata.get("source") or {}
    validation = metadata.get("validation") or {}

    total_reglas = 0
    reglas_con_soporte_positivo = 0
    niveles_evidencia_presentes: set[str] = set()

    rules_dir = carpeta / "rules"
    if rules_dir.exists():
        for archivo in sorted(rules_dir.glob("*.yaml")):
            payload = _leer_yaml(archivo) or {}
            for regla in payload.get("rules", []):
                total_reglas += 1
                conclusion = regla.get("conclusion") or {}
                if conclusion.get("audit_effect") == "supports_prescription":
                    reglas_con_soporte_positivo += 1
                nivel = ((regla.get("evidence") or {}).get("native") or {}).get("evidence_level")
                if nivel:
                    niveles_evidencia_presentes.add(str(nivel))

    return {
        "organizacion": metadata.get("organization"),
        "titulo_fuente": source.get("title"),
        "anio_publicacion": source.get("publication_year"),
        "doi": source.get("doi"),
        "estado_validacion_clinica": validation.get("clinical_validation_status"),
        "total_reglas_en_el_modulo": total_reglas,
        "reglas_con_recomendacion_positiva": reglas_con_soporte_positivo,
        "niveles_de_evidencia_presentes": sorted(niveles_evidencia_presentes),
    }


@tool
def listar_variables_requeridas(cancer_type_o_modulo: str) -> str:
    """Devuelve, en JSON, la lista de variables clínicas (nombre y
    valores permitidos) que un módulo de guía necesita para poder
    evaluar tratamiento. Usa esta tool SIEMPRE que el oncólogo pida una
    recomendación de tratamiento sin haber dado datos clínicos
    suficientes todavía, o pregunte explícitamente qué información
    necesitas -- nunca inventes ni asumas qué campos pedir, esta tool te
    da los reales.

    cancer_type_o_modulo puede ser el tipo de cáncer en lenguaje natural
    o, preferentemente, la DESCRIPCIÓN CLÍNICA COMPLETA del caso. El
    oncólogo no necesita conocer el nombre técnico de la carpeta del módulo.
    También acepta el nombre EXACTO de la carpeta del módulo si ya se conoce
    (ej. 'nsclc_metastatic_non_oncogene').

    IMPORTANTE: si varios módulos de guía coinciden con lo que
    escribiste (ej. 'NSCLC' coincide con 3 módulos distintos: temprano,
    metastásico sin oncogén, y metastásico con oncogén conductor), esta
    tool NO elige uno por ti -- te devuelve
    necesita_desambiguacion=true con la lista de módulos posibles y su
    alcance clínico. En ese caso, pregúntale al oncólogo cuál aplica
    (o vuelve a llamar esta tool con el nombre EXACTO de carpeta del
    módulo correcto una vez lo sepas) -- nunca asumas cuál es el
    correcto ni mezcles variables de un módulo con otro."""
    consulta = _normalizar(cancer_type_o_modulo)

    if not GUIDELINES_ROOT.exists():
        return json.dumps({"error": "No se encontró la carpeta guidelines/."})

    modulos_activos = [
        p for p in sorted(GUIDELINES_ROOT.iterdir())
        if p.is_dir() and p.name not in MODULOS_FUERA_DE_ALCANCE
    ]

    # Coincidencia EXACTA de nombre de carpeta: nunca es ambigua, se usa
    # directo aunque el texto también matchee otros módulos por substring.
    coincidencia_exacta = next((p for p in modulos_activos if _normalizar(p.name) == consulta), None)
    if coincidencia_exacta is not None:
        return _variables_de_modulo(coincidencia_exacta)

    candidatos = []
    for carpeta in modulos_activos:
        if consulta in _normalizar(carpeta.name) or _normalizar(carpeta.name) in consulta:
            candidatos.append(carpeta)
            continue
        metadata = _leer_yaml(carpeta / "metadata.yaml") or {}
        texto_metadata = _normalizar(
            str(metadata.get("name", "")) + " " + str(metadata.get("clinical_scope", ""))
        )
        if consulta and consulta in texto_metadata:
            candidatos.append(carpeta)

    if not candidatos:
        # Si el argumento es una descripción clínica completa, intentar
        # identificar el módulo por contexto explícito.
        modulo_inferido = _inferir_modulo_por_contexto(
            cancer_type_o_modulo,
            modulos_activos,
        )
        if modulo_inferido is not None:
            return _variables_de_modulo(modulo_inferido)

        return json.dumps({
            "error": f"No se encontró ningún módulo de guía que coincida con '{cancer_type_o_modulo}'.",
            "modulos_disponibles": [p.name for p in modulos_activos],
        }, ensure_ascii=False)

    if len(candidatos) > 1:
        # Ambigüedad real: varios módulos coinciden (ej. "NSCLC" matchea
        # temprano/metastásico-sin-oncogén/metastásico-con-oncogén). No
        # se adivina cuál -- se listan todos con su alcance clínico Y un
        # resumen de evidencia (organización, año, validación, cantidad
        # de reglas positivas) para que el ONCÓLOGO decida cuál aplica,
        # o vuelva a llamar esta tool con el nombre exacto de carpeta
        # una vez lo sepa.
        opciones = []
        for carpeta in candidatos:
            metadata = _leer_yaml(carpeta / "metadata.yaml") or {}
            opciones.append({
                "modulo": carpeta.name,
                "nombre": metadata.get("name"),
                "alcance_clinico": metadata.get("clinical_scope"),
                "evidencia_del_modulo": _resumen_evidencia_modulo(carpeta, metadata),
            })
        return json.dumps({
            "necesita_desambiguacion": True,
            "modulos_posibles": opciones,
        }, ensure_ascii=False)

    return _variables_de_modulo(candidatos[0])
