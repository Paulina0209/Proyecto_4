"""
Agente que compara la representacion clinica ACTUAL de un modulo
(guidelines/<carpeta>/) contra un NUEVO documento oficial (pptx,
pdf o html, el formato que sea que haya llegado esta vez) y
propone que deberia cambiar -- solo eso, nunca reescribe
guidelines/ directamente.

No compara version-vieja-descargada vs version-nueva-descargada
(eso tiene un problema real: la version vieja no siempre esta
guardada, y cuando lo esta puede estar en un formato distinto al de
la version nueva, lo que ensucia el diff con ruido de formato en
vez de cambio clinico real). La unica version "anterior" confiable
es lo que ya esta implementado en guidelines/ -- eso es lo que hay
que actualizar, asi que es contra eso que se compara.

Sigue el mismo patron que ia_clinica/notes (LLMClient / RuleBasedLLMClient,
ver docs/ia_clinica_notas.md) en vez de inventar un mecanismo nuevo.

RuleBasedLLMClient es el default seguro y NO redacta YAML: a
diferencia de generar notas clinicas (donde no alucinar significa
"solo copiar fragmentos ya existentes"), proponer un cambio de
regla de tratamiento requiere interpretacion clinica real que un
clasificador por palabras clave no puede hacer sin riesgo de
inventar contenido. El stub deja las dos fuentes listas para que un
LLM real (o un medico) las compare -- no lo intenta el mismo.

LangGraphLLMClient (graph.py) es el unico backend real -- corre el
grafo por nodos (parse_context -> gap_analysis -> detect_and_
classify_changes -> generate_file_proposal por archivo, en
paralelo, con reintento interno -> generate_draft) en vez de una
sola llamada al API, para que un truncamiento a mitad de generacion
afecte solo al archivo YAML que se estaba escribiendo, no a toda la
propuesta. Se eliminó el backend de llamada unica (single_call) por
ese motivo.
"""

from abc import ABC, abstractmethod
from pathlib import Path
import datetime
import re
import shutil

from . import pptx_text


# agent/ -> guidelineUpdate/ -> <raiz del proyecto> -> guidelines/
GUIDELINES_ROOT = Path(__file__).resolve().parent.parent.parent / "guidelines"

# docs/guidelines/esmo/<carpeta_del_modulo>/ -- mismo patron de
# carpeta que guidelines/ (sin el prefijo "esmo_"), confirmado
# contra la estructura real de docs/guidelines/esmo/. Contiene
# clinical_matrix.md y decision_tree.md, el contexto narrativo con
# IDs de reglas y grados de evidencia que complementa el YAML crudo.
DOCS_GUIDELINES_ROOT = Path(__file__).resolve().parent.parent.parent / "docs" / "guidelines" / "esmo"

# updates/ vive dentro de guidelineUpdate/, al mismo nivel que
# scraper/ y agent/ (ver estructura de carpetas del proyecto). Debe
# coincidir exactamente con el OUTPUT_ROOT de download_content.py --
# ambos escriben bajo <module_id>/, uno en documents/ y este en
# proposed_rules/.
OUTPUT_ROOT = Path(__file__).resolve().parent.parent / "updates"
PROPOSED_RULES_DIRNAME = "proposed_rules"

# Archivos en la raiz del modulo (guidelines/<carpeta>/*.yaml).
ROOT_FILES = ("metadata.yaml", "pathway.yaml", "regimens.yaml", "variables.yaml")

# clinical_matrix.md y decision_tree.md, dentro de
# docs/guidelines/esmo/<carpeta>/ -- contexto narrativo, no
# reglas computables.
DOC_FILES = ("clinical_matrix.md", "decision_tree.md")


def _resolve_dir(module_id, root):
    """
    El nombre de la carpeta no coincide con el module_id -- pierde
    el prefijo "esmo_" (confirmado tanto en guidelines/ como en
    docs/guidelines/esmo/: esmo_breast_early_tnbc -> breast_early_tnbc,
    etc., sin excepciones). Se prueba primero sin el prefijo (el
    caso real), y el module_id tal cual como respaldo por si algun
    modulo futuro no sigue el patron.
    """

    candidates = [module_id]

    if module_id.startswith("esmo_"):
        candidates.insert(0, module_id[len("esmo_"):])

    for candidate in candidates:
        candidate_dir = root / candidate
        if candidate_dir.exists():
            return candidate_dir

    return None


def _resolve_module_dir(module_id):
    return _resolve_dir(module_id, GUIDELINES_ROOT)


def _resolve_docs_dir(module_id):
    return _resolve_dir(module_id, DOCS_GUIDELINES_ROOT)


def load_module_rule_context(module_id):
    """
    Junta el contenido de los archivos de reglas de un modulo (raiz
    + rules/, mas clinical_matrix.md/decision_tree.md si existen en
    docs/) -- este es el lado "representacion actual" de la
    comparacion. Devuelve None si no se encontro la carpeta del
    modulo bajo ninguno de los nombres candidatos.
    """

    module_dir = _resolve_module_dir(module_id)

    if module_dir is None:
        return None

    parts = []

    for filename in ROOT_FILES:
        file_path = module_dir / filename
        if file_path.exists():
            parts.append(f"--- {filename} ---\n{file_path.read_text(encoding='utf-8')}")

    # Los nombres de archivo dentro de rules/ NO son consistentes
    # entre modulos (ej. breast_early_tnbc usa neoadjuvant.yaml/
    # perioperative.yaml, breast_metastatic_tnbc usa first_line.yaml/
    # subsequent_line.yaml, cutaneous_melanoma usa
    # unresectable_metastatic.yaml) -- se lee lo que exista en vez
    # de una lista fija.
    rules_dir = module_dir / "rules"
    if rules_dir.exists():
        for file_path in sorted(rules_dir.glob("*.yaml")):
            parts.append(f"--- rules/{file_path.name} ---\n{file_path.read_text(encoding='utf-8')}")

    docs_dir = _resolve_docs_dir(module_id)
    if docs_dir:
        for filename in DOC_FILES:
            file_path = docs_dir / filename
            if file_path.exists():
                parts.append(f"--- docs/{filename} ---\n{file_path.read_text(encoding='utf-8')}")

    return "\n\n".join(parts) if parts else None


def _copy_current_module_files(module_dir, destination_dir):
    """
    Copia tal cual los archivos actuales del modulo (raiz + rules/)
    a destination_dir -- el punto de partida del folder de
    propuesta, para que el resultado sea diffable 1:1 contra
    guidelines/<carpeta>/ incluso en los archivos que la propuesta
    no toca (en vez de que el revisor tenga que adivinar si un
    archivo ausente significa "sin cambios" o "no se genero").
    """

    destination_dir.mkdir(parents=True, exist_ok=True)

    for filename in ROOT_FILES:
        source = module_dir / filename
        if source.exists():
            shutil.copy2(source, destination_dir / filename)

    rules_source_dir = module_dir / "rules"
    if rules_source_dir.exists():
        rules_dest_dir = destination_dir / "rules"
        rules_dest_dir.mkdir(exist_ok=True)
        for source in sorted(rules_source_dir.glob("*.yaml")):
            shutil.copy2(source, rules_dest_dir / source.name)


def write_proposed_rule_folder(module_id, proposed_files, review_notes, output_root=None):
    """
    Crea una carpeta de propuesta bajo
    updates/<module_id>/proposed_rules/<fecha>/, con el mismo
    formato y encarpetado que guidelines/<carpeta>/ (raiz +
    rules/*.yaml) -- NUNCA dentro de guidelines/ mismo, ver el
    principio en el docstring del modulo.

    Parte de una copia exacta del modulo actual (via
    _copy_current_module_files) y le aplica encima los archivos que
    el LLM propuso en proposed_files ({ruta_relativa: contenido}),
    de forma que el resultado sea diffable 1:1 contra
    guidelines/<carpeta>/ y solo se destaque lo que realmente
    cambia o se agrega. review_notes (el borrador narrativo) se
    guarda aparte como PROPOSED_CHANGES.md en la misma carpeta.

    Devuelve la carpeta final (Path), o None si no se encontro el
    modulo en guidelines/ o si no hay absolutamente nada que
    escribir (ni proposed_files ni review_notes). Si proposed_files
    vino vacio pero review_notes tiene contenido (p.ej. el borrador
    concluyo que no hay cambios computables, o que todo requiere
    verificacion humana), igual se crea la carpeta con
    PROPOSED_CHANGES.md -- para que la razon que dio el modelo
    quede persistida y no se pierda en el print de consola.
    """

    module_dir = _resolve_module_dir(module_id)
    if module_dir is None:
        print(f"  No se encontro guidelines/ para {module_id} -- no se creo carpeta de propuesta.")
        return None

    if not proposed_files and not review_notes:
        print("  El borrador no incluyo archivos YAML propuestos ni notas -- no se creo carpeta de propuesta.")
        return None

    root = Path(output_root) if output_root else OUTPUT_ROOT
    date_stamp = datetime.date.today().isoformat()
    destination_dir = root / module_id / PROPOSED_RULES_DIRNAME / date_stamp

    if proposed_files:
        _copy_current_module_files(module_dir, destination_dir)
        for relative_path, content in proposed_files.items():
            target_path = destination_dir / relative_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(content, encoding="utf-8")
    else:
        destination_dir.mkdir(parents=True, exist_ok=True)
        print("  El borrador no incluyo archivos YAML propuestos -- se guardan solo las notas de revision.")

    if review_notes:
        (destination_dir / "PROPOSED_CHANGES.md").write_text(review_notes, encoding="utf-8")

    return destination_dir


def _html_file_to_text(path):
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"</(li|p|h[1-6])>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _pdf_file_to_text(path):
    try:
        import pdfplumber
    except ImportError:
        print(
            "  pdfplumber no esta instalado (pip install pdfplumber) "
            "-- no se pudo extraer texto del PDF."
        )
        return None

    try:
        with pdfplumber.open(path) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
    except Exception as error:
        print(f"  ERROR al leer el PDF: {error}")
        return None

    text = "\n".join(pages).strip()
    return text or None


def load_new_document_text(document_path):
    """
    Lee el documento nuevo (el que descargo download_content.py) y
    devuelve su texto, sin importar si es .pptx, .pdf o .html --
    este es el lado "fuente nueva" de la comparacion. Devuelve None
    si el formato no se reconoce o si la extraccion fallo (el
    llamador decide que hacer -- normalmente, avisar que hace falta
    revision manual del documento original).
    """

    document_path = Path(document_path)
    suffix = document_path.suffix.lower()

    if suffix == ".pptx":
        return pptx_text.extract_pptx_text(document_path)

    if suffix in (".html", ".htm"):
        return _html_file_to_text(document_path)

    if suffix == ".pdf":
        return _pdf_file_to_text(document_path)

    print(f"  Formato no reconocido para {document_path.name} -- no se pudo leer.")
    return None


def load_new_document_images(document_path):
    """
    Devuelve las imagenes del documento nuevo como lista de
    (media_type, blob), una por slide en orden -- el fallback
    multimodal para cuando load_new_document_text() no encuentra
    texto util (caso deck ESMO: slides que son puro imagen de
    fondo, sin ningun shape de texto).

    Por ahora solo soportado para .pptx (unico formato donde se
    confirmo el problema); para los demas formatos devuelve lista
    vacia, ya que load_new_document_text() ya extrae texto real de
    esos casos.
    """

    document_path = Path(document_path)

    if document_path.suffix.lower() == ".pptx":
        return pptx_text.extract_pptx_images(document_path)

    return []


class LLMClient(ABC):

    @abstractmethod
    def draft_rule_change(self, current_rules_text, new_document_text, module_id,
                           new_document_images=None):
        """
        current_rules_text: lo que devuelve load_module_rule_context()
        -- la representacion computable actual del modulo.
        new_document_text: lo que devuelve load_new_document_text()
        -- el texto del documento oficial nuevo, sin importar el
        formato original. Puede ser None si el documento no tenia
        texto extraible (p.ej. deck de solo-imagenes).
        new_document_images: lista opcional de (media_type, blob)
        de load_new_document_images() -- se usa cuando el
        contenido clinico esta pegado como imagen (diagramas,
        arboles de decision) en vez de texto real. Puede venir
        junto con texto (p.ej. algunas slides con texto y otras
        solo imagen) o sola cuando new_document_text es None.

        Devuelve {"draft": str, "proposed_files": dict, "confidence": str,
        "notes": str}, o None si no hay nada util que proponer
        todavia. proposed_files es {ruta_relativa: contenido} para
        los cambios que ya se pueden redactar como regla computable
        (ver write_proposed_rule_folder) -- puede venir vacio {} si
        todo lo detectado requiere verificacion humana antes de
        redactarse.
        """


class RuleBasedLLMClient(LLMClient):
    """
    Implementacion de referencia sin proveedor externo. Nunca
    redacta una propuesta -- siempre devuelve None, para que el
    documento de revision diga claramente "sin propuesta automatica
    todavia" en vez de mostrar algo fabricado por palabras clave
    disfrazado de analisis real.
    """

    def draft_rule_change(self, current_rules_text, new_document_text, module_id,
                           new_document_images=None):
        return None


class LangGraphLLMClient(LLMClient):
    """
    Corre el grafo de graph.py (parse_context -> gap_analysis ->
    detect_and_classify_changes -> generate_file_proposal por
    archivo, en paralelo, con reintento interno -> generate_draft).

    No se importa graph.py a nivel de modulo -- el import queda
    adentro de draft_rule_change() (lazy, solo la primera vez) para
    no forzar la dependencia de langgraph al importar rule_agent.py
    si esta clase nunca llega a instanciarse.
    """

    def __init__(self, api_key, model="claude-sonnet-5"):
        self.api_key = api_key
        self.model = model
        self._app = None

    def draft_rule_change(self, current_rules_text, new_document_text, module_id,
                           new_document_images=None):

        if not current_rules_text:
            raise ValueError(
                f"current_rules_text vacio para el modulo {module_id} -- "
                "no se encontro la carpeta del modulo en guidelines/."
            )
        if not new_document_text and not new_document_images:
            raise ValueError(
                "No hay texto ni imagenes del documento nuevo -- "
                "nada que comparar. Revisar load_new_document_text() / "
                "load_new_document_images() para este archivo."
            )

        if self._app is None:
            from .graph import build_graph
            self._app = build_graph()

        result = self._app.invoke({
            "module_id": module_id,
            "api_key": self.api_key,
            "model": self.model,
            "current_rules_text": current_rules_text,
            "new_document_text": new_document_text,
            "new_document_images": new_document_images or [],
        })

        notes = "Generado por LangGraphLLMClient -- no aplicar sin revision."
        if result.get("validation_errors"):
            notes += (
                " ATENCION: algunos archivos no pasaron validacion tras "
                "reintento y quedaron fuera de proposed_files -- ver detalle "
                "en el draft: " + str(result["validation_errors"])
            )

        return {
            "draft": result.get("draft_markdown", ""),
            "proposed_files": result.get("proposals", {}),
            "confidence": "requiere_revision_medica",
            "notes": notes,
        }