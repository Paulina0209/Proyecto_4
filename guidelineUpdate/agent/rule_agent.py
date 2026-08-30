from abc import ABC, abstractmethod
from pathlib import Path
import datetime
import re
import shutil


from . import pptx_text

                                                          
GUIDELINES_ROOT = Path(__file__).resolve().parent.parent.parent / "guidelines"
                                                           
DOCS_GUIDELINES_ROOT = Path(__file__).resolve().parent.parent.parent / "docs" / "guidelines" / "esmo"
            
OUTPUT_ROOT = Path(__file__).resolve().parent.parent / "updates"
PROPOSED_RULES_DIRNAME = "proposed_rules"
                                                           
ROOT_FILES = ("metadata.yaml", "pathway.yaml", "regimens.yaml", "variables.yaml")
                    
DOC_FILES = ("clinical_matrix.md", "decision_tree.md")


def _resolve_dir(module_id, root):
    

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
    

    module_dir = _resolve_module_dir(module_id)

    if module_dir is None:
        return None

    parts = []

    for filename in ROOT_FILES:
        file_path = module_dir / filename
        if file_path.exists():
            parts.append(f"--- {filename} ---\n{file_path.read_text(encoding='utf-8')}")
               
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
    

    document_path = Path(document_path)

    if document_path.suffix.lower() == ".pptx":
        return pptx_text.extract_pptx_images(document_path)

    return []

class LLMClient(ABC):

    @abstractmethod
    def draft_rule_change(self, current_rules_text, new_document_text, module_id,
                           new_document_images=None):
        pass

class RuleBasedLLMClient(LLMClient):
    

    def draft_rule_change(self, current_rules_text, new_document_text, module_id,
                           new_document_images=None):
        return None

class LangGraphLLMClient(LLMClient):
    

    def __init__(self, api_key, model="claude-sonnet-5", detection_model=None):
        self.api_key = api_key
        self.model = model
        # Paso de deteccion/clasificacion de cambios: es una tarea de
        # clasificacion estructurada contra una tabla ya verificada, no la
        # redaccion final de la regla clinica -- si se quiere usar un modelo
        # mas economico (p.ej. "claude-haiku-4-5-20251001") solo para ese
        # paso, se puede pasar aca. Por defecto usa el mismo modelo que la
        # generacion (sin cambio de comportamiento si no se especifica).
        self.detection_model = detection_model or model
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
            "detection_model": self.detection_model,
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