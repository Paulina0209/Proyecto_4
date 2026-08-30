from __future__ import annotations

import base64
import json
import operator
import re
from typing import Annotated, TypedDict

import yaml
from langgraph.graph import StateGraph, END
from langgraph.types import Send


def _build_anthropic_client(api_key: str):
    """Cliente de Anthropic con mas reintentos que el default (2) sobre
    errores transitorios (529 overloaded, 500, timeouts) -- el SDK ya hace
    backoff exponencial solo, esto amplia el margen antes de que un pico de
    demanda tire abajo la corrida completa de un modulo."""
    import anthropic

    return anthropic.Anthropic(api_key=api_key, max_retries=6, timeout=120.0)




# ---------------------------------------------------------------------------
# 1. Estado del grafo
# ---------------------------------------------------------------------------

class GapReport(TypedDict):
    variable: str
    referenced_in_pathway: bool
    referenced_in_rule_files: list[str]


class ChangeItem(TypedDict):
    description: str
    action: str  # create | modify | deprecate | uncertain | no_change
    affected_files: list[str]
    source_excerpt: str
    requires_human_review: bool


class GraphState(TypedDict):
    module_id: str
    api_key: str
    model: str
    # modelo (mas barato, opcional) para el paso de clasificacion de
    # cambios; por defecto es igual a 'model' -- ver rule_agent.py
    detection_model: str

    # entrada, con la misma forma que recibe LLMClient.draft_rule_change
    current_rules_text: str
    new_document_text: str | None
    new_document_images: list[tuple[str, bytes]]

    # parseado de current_rules_text (nodo parse_context)
    current_files: dict[str, str]

    # nodo gap_analysis (determinista, sin LLM)
    gap_report: list[GapReport]

    # nodo detect_and_classify_changes (LLM, unica vez que se mandan las imagenes)
    changes: list[ChangeItem]
    files_to_propose: list[str]

    # fan-out: un nodo de generacion por archivo, con reintento interno
    proposals: Annotated[dict[str, str], operator.or_]
    validation_errors: Annotated[dict[str, str], operator.or_]

    # nodo generate_draft (determinista, arma el PROPOSED_CHANGES.md)
    draft_markdown: str


# ---------------------------------------------------------------------------
# 2. Parseo de current_rules_text -> dict por archivo
# ---------------------------------------------------------------------------
# load_module_rule_context() en rule_agent.py junta todo con:
#   "\n\n".join(f"--- {filename} ---\n{content}" for ...)
# Este parser deshace exactamente eso.

_SECTION_PATTERN = re.compile(r"^--- (.+?) ---\n(.*?)(?=\n--- |\Z)", re.DOTALL | re.MULTILINE)


def parse_context_node(state: GraphState) -> dict:
    current_files = {}
    for match in _SECTION_PATTERN.finditer(state["current_rules_text"]):
        filename = match.group(1).strip()
        content = match.group(2)
        current_files[filename] = content

    return {"current_files": current_files}


# ---------------------------------------------------------------------------
# 3. Nodo determinista: gap analysis
# ---------------------------------------------------------------------------
# variables.yaml y pathway.yaml SI son consistentes entre modulos (estan
# en ROOT_FILES en rule_agent.py); los nombres dentro de rules/ NO lo son
# (ver docstring de rule_agent.py), por eso se agrupan por prefijo
# "rules/" en vez de nombres fijos.

def gap_analysis_node(state: GraphState) -> dict:
    files = state["current_files"]

    if "variables.yaml" not in files or "pathway.yaml" not in files:
        # modulo sin esta estructura todavia (o parseo vacio) -- no
        # se puede hacer gap analysis, pero no debe romper el grafo.
        return {"gap_report": []}

    try:
        variables = yaml.safe_load(files["variables.yaml"]) or {}
        pathway = yaml.safe_load(files["pathway.yaml"]) or {}
    except yaml.YAMLError:
        return {"gap_report": []}

    defined_vars = set(variables.get("variables", {}).keys())
    pathway_fields = {
        node.get("field") for node in pathway.get("nodes", {}).values() if node.get("field")
    }

    rule_files = {path: content for path, content in files.items() if path.startswith("rules/")}

    report: list[GapReport] = []
    for var in sorted(defined_vars):
        referenced_in = [
            path for path, content in rule_files.items() if f"field: {var}" in content
        ]
        report.append(
            GapReport(
                variable=var,
                referenced_in_pathway=var in pathway_fields,
                referenced_in_rule_files=referenced_in,
            )
        )

    return {"gap_report": report}


# ---------------------------------------------------------------------------
# 4. Nodo LLM: detectar y clasificar cambios (unica vez que se envian imagenes)
# ---------------------------------------------------------------------------

_DETECT_SYSTEM_PROMPT = """Eres un analista clinico-computacional. Comparas la
representacion computable ACTUAL de una guia clinica (reglas YAML) contra un
documento oficial NUEVO (texto y/o imagenes de slides) y detectas cambios
clinicamente relevantes.

Ya tenes una tabla verificada de que variables existen y donde se usan --
no la reinventes, usala como base de verdad sobre el estado actual.

No inventes grados de evidencia que no esten en el documento nuevo. Ignora
cambios puramente administrativos o de formato sin impacto clinico.

Devolve SOLO un JSON (lista de objetos), sin texto adicional, con esta forma:
[
  {
    "description": "...",
    "action": "create | modify | deprecate | uncertain | no_change",
    "affected_files": ["rules/neoadjuvant.yaml", ...],
    "source_excerpt": "cita corta que respalda el cambio",
    "requires_human_review": true | false
  },
  ...
]

Un cambio queda con requires_human_review=true (y action="uncertain") cuando
la lectura del documento nuevo es ambigua o falta contexto clinico para
redactarlo con seguridad como regla -- ese cambio NO debe ir en
affected_files como create/modify, solo describirse."""


# Cuantas imagenes (slides) se mandan por llamada a la API. Si un
# documento tiene mas que esto, se detecta en varias tandas en vez de
# una sola llamada con max_tokens=16000 -- eso es lo que generaba el
# corte silencioso que caia en el except JSONDecodeError de mas abajo.
_MAX_IMAGES_PER_BATCH = 8


def _build_shared_context_block(state: GraphState) -> dict:
    

    gap_summary = "\n".join(
        f"- {g['variable']}: en pathway={g['referenced_in_pathway']}, "
        f"usada en reglas={g['referenced_in_rule_files'] or 'NINGUNA'}"
        for g in state["gap_report"]
    ) or "(sin gap_report para este modulo)"

    new_text_block = state["new_document_text"] or (
        "(sin texto extraible -- el contenido esta en las imagenes que siguen)"
    )

    text = (
        f"--- Tabla de variables verificada (modulo {state['module_id']}) ---\n\n"
        + gap_summary
        + f"\n\n--- Representacion actual (modulo {state['module_id']}) ---\n\n"
        + state["current_rules_text"]
        + "\n\n--- Documento oficial nuevo (texto) ---\n\n"
        + new_text_block
    )

    # cache_control marca este bloque para prompt caching: si hay varias
    # tandas de imagenes, este texto (que puede ser grande) se paga completo
    # solo la primera vez (1.25x el precio base de input) y las siguientes
    # tandas leen del cache a 0.1x el precio base -- une ahorro real cuando
    # un modulo tiene mas de _MAX_IMAGES_PER_BATCH slides.
    return {"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}


def _call_detect_batch(
    client, state: GraphState, shared_block: dict, image_batch, batch_index: int, total_batches: int
) -> list[ChangeItem]:
    

    content = [shared_block]

    if image_batch:
        content.append(
            {
                "type": "text",
                "text": (
                    f"\n\n--- Tanda {batch_index}/{total_batches} de imagenes del documento "
                    "nuevo -- detecta cambios usando el contexto compartido de arriba mas "
                    "las imagenes que siguen en esta tanda (en orden) ---"
                ),
            }
        )
        for media_type, blob in image_batch:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64.b64encode(blob).decode("utf-8"),
                    },
                }
            )
        content.append(
            {
                "type": "text",
                "text": f"(las {len(image_batch)} imagenes de arriba son la tanda {batch_index}/{total_batches}, en orden)",
            }
        )

    response = client.messages.create(
        model=state["detection_model"],
        max_tokens=16000,
        # System tambien con cache_control: se repite identico en cada
        # tanda y en cada modulo procesado en la misma corrida -- es chico
        # (unos cientos de tokens) pero cachearlo es gratis.
        system=[
            {
                "type": "text",
                "text": _DETECT_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": content}],
    )
    raw = "".join(block.text for block in response.content if block.type == "text")

    if response.stop_reason == "max_tokens":
        return [
            {
                "description": (
                    f"Tanda {batch_index}/{total_batches}: la deteccion se corto por "
                    "limite de max_tokens (no es un error de formato JSON) -- puede "
                    "faltar informacion de esta tanda, revisar manualmente."
                ),
                "action": "uncertain",
                "affected_files": [],
                "source_excerpt": raw[:500],
                "requires_human_review": True,
            }
        ]

    return _parse_changes_json(raw)


def detect_and_classify_changes_node(state: GraphState) -> dict:
    client = _build_anthropic_client(state["api_key"])
    shared_block = _build_shared_context_block(state)
    images = state["new_document_images"]

    all_changes: list[ChangeItem] = []

    if not images:
        all_changes.extend(_call_detect_batch(client, state, shared_block, [], 1, 1))
    else:
        batches = [
            images[i : i + _MAX_IMAGES_PER_BATCH]
            for i in range(0, len(images), _MAX_IMAGES_PER_BATCH)
        ]
        total_batches = len(batches)
        for batch_index, image_batch in enumerate(batches, start=1):
            all_changes.extend(
                _call_detect_batch(client, state, shared_block, image_batch, batch_index, total_batches)
            )

    files_to_propose = sorted(
        {
            f
            for c in all_changes
            if c["action"] in ("create", "modify")
            for f in c["affected_files"]
        }
    )

    return {"changes": all_changes, "files_to_propose": files_to_propose}


def _parse_changes_json(raw: str) -> list[ChangeItem]:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        cleaned = cleaned.rsplit("```", 1)[0]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # el LLM no devolvio JSON limpio -- no se rompe el grafo, se
        # deja constancia para que el draft final lo muestre y un
        # humano decida si reintentar la deteccion.
        return [
            {
                "description": "No se pudo parsear la deteccion de cambios como JSON -- revisar manualmente.",
                "action": "uncertain",
                "affected_files": [],
                "source_excerpt": raw[:500],
                "requires_human_review": True,
            }
        ]


# ---------------------------------------------------------------------------
# 5. Fan-out: un nodo de generacion por archivo, con reintento interno
# ---------------------------------------------------------------------------

def route_to_file_proposals(state: GraphState) -> list[Send] | str:
    if not state["files_to_propose"]:
        return "validate_proposals"

    return [
        Send(
            "generate_file_proposal",
            {
                "module_id": state["module_id"],
                "api_key": state["api_key"],
                "model": state["model"],
                "target_file": f,
                "current_content": state["current_files"].get(f, "(archivo nuevo, no existe todavia)"),
                "relevant_changes": [c for c in state["changes"] if f in c["affected_files"]],
            },
        )
        for f in state["files_to_propose"]
    ]


class FileProposalState(TypedDict):
    module_id: str
    api_key: str
    model: str
    target_file: str
    current_content: str
    relevant_changes: list[ChangeItem]


_GENERATE_FILE_SYSTEM_PROMPT = """Redactas el contenido YAML completo y valido
de UN archivo de reglas clinicas computables, aplicando los cambios ya
detectados y clasificados que te pasan. Devolve UNICAMENTE el YAML completo
del archivo (nunca un diff ni un fragmento -- va a reemplazar al archivo
entero), sin explicacion, sin markdown fences. Conserva el resto del archivo
igual a como esta, modificando solo lo que los cambios indican. Segui la
misma convencion de IDs que ya usa el archivo (mismo prefijo, siguiente
numero disponible)."""


_YAML_FENCE_PATTERN = re.compile(r"^```(?:yaml)?\s*\n(.*?)\n?```\s*$", re.DOTALL)


def _strip_yaml_fence(raw):
    """
    El system prompt pide explicitamente 'sin markdown fences', pero el
    modelo a veces igual envuelve la respuesta en ```yaml ... ``` --
    esto lo detecta y lo saca antes de pasarlo a yaml.safe_load, en vez
    de contar ese caso como YAML invalido y gastar un reintento por algo
    que es puramente de formato.
    """

    match = _YAML_FENCE_PATTERN.match(raw.strip())
    return match.group(1) if match else raw


def generate_file_proposal_node(state: FileProposalState) -> dict:
    client = _build_anthropic_client(state["api_key"])

    user_text = (
        f"Archivo: {state['target_file']}\n\n"
        f"Cambios a aplicar:\n{json.dumps(state['relevant_changes'], ensure_ascii=False, indent=2)}\n\n"
        f"Contenido actual del archivo:\n{state['current_content']}"
    )

    last_error = None
    for attempt in range(1, 3):  # hasta 2 intentos
        response = client.messages.create(
            model=state["model"],
            max_tokens=8000,
            system=[
                {
                    "type": "text",
                    "text": _GENERATE_FILE_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_text}],
        )
        raw = "".join(block.text for block in response.content if block.type == "text").strip()
        raw = _strip_yaml_fence(raw)

        if response.stop_reason == "max_tokens":
            last_error = f"Intento {attempt}: se corto por limite de max_tokens."
            continue

        try:
            parsed = yaml.safe_load(raw)
        except yaml.YAMLError as e:
            last_error = f"Intento {attempt}: YAML invalido -- {e}"
            continue

        if not parsed or not ({"rules", "variables", "nodes"} & set(parsed.keys())):
            last_error = f"Intento {attempt}: YAML parseable pero con forma inesperada."
            continue

        return {"proposals": {state["target_file"]: raw if raw.endswith("\n") else raw + "\n"}}

    return {"validation_errors": {state["target_file"]: last_error or "fallo desconocido"}}

# ---------------------------------------------------------------------------
# 6. Nodo puente (el join de los Send en paralelo ya combino proposals/
#    validation_errors via los reducers operator.or_ del GraphState;
#    este nodo no necesita hacer nada mas, solo existe para que el grafo
#    tenga un punto unico donde converger antes de armar el draft)
# ---------------------------------------------------------------------------

def validate_proposals_node(state: GraphState) -> dict:
    return {}


# ---------------------------------------------------------------------------
# 7. Nodo determinista: arma el draft narrativo (PROPOSED_CHANGES.md)
# ---------------------------------------------------------------------------

def generate_draft_node(state: GraphState) -> dict:
    computable = [
        c for c in state["changes"] if c["action"] in ("create", "modify")
    ]
    needs_review = [c for c in state["changes"] if c.get("requires_human_review")]
    no_change = [c for c in state["changes"] if c["action"] == "no_change"]

    lines = [f"# Borrador de analisis comparativo -- `{state['module_id']}`\n"]

    if state["validation_errors"]:
        lines.append("## ATENCION: archivos con errores de generacion\n")
        for path, error in state["validation_errors"].items():
            lines.append(f"- `{path}`: {error}")
        lines.append("")

    lines.append("## Cambios ya redactados como regla computable\n")
    if computable:
        for c in computable:
            status = "OK" if any(f in state["proposals"] for f in c["affected_files"]) else "con errores, ver arriba"
            lines.append(f"- ({status}) {c['description']}")
            lines.append(f"  - Archivos: {', '.join(c['affected_files'])}")
            lines.append(f"  - Fuente: {c['source_excerpt']}\n")
    else:
        lines.append("(ninguno)\n")

    lines.append("## Cambios que requieren verificacion humana antes de convertirse en regla\n")
    if needs_review:
        for c in needs_review:
            lines.append(f"- {c['description']}")
            lines.append(f"  - Fuente: {c['source_excerpt']}\n")
    else:
        lines.append("(ninguno)\n")

    lines.append("## Sin cambios detectados\n")
    if no_change:
        for c in no_change:
            lines.append(f"- {c['description']}")
    else:
        lines.append("(no se registraron confirmaciones explicitas de 'sin cambio')")

    return {"draft_markdown": "\n".join(lines)}


# ---------------------------------------------------------------------------
# 8. Ensamblar el grafo
# ---------------------------------------------------------------------------

def build_graph():
    graph = StateGraph(GraphState)

    graph.add_node("parse_context", parse_context_node)
    graph.add_node("gap_analysis", gap_analysis_node)
    graph.add_node("detect_and_classify_changes", detect_and_classify_changes_node)
    graph.add_node("generate_file_proposal", generate_file_proposal_node)
    graph.add_node("validate_proposals", validate_proposals_node)
    graph.add_node("generate_draft", generate_draft_node)

    graph.set_entry_point("parse_context")
    graph.add_edge("parse_context", "gap_analysis")
    graph.add_edge("gap_analysis", "detect_and_classify_changes")
    graph.add_conditional_edges(
        "detect_and_classify_changes",
        route_to_file_proposals,
        ["generate_file_proposal", "validate_proposals"],
    )
    graph.add_edge("generate_file_proposal", "validate_proposals")
    graph.add_edge("validate_proposals", "generate_draft")
    graph.add_edge("generate_draft", END)

    return graph.compile()