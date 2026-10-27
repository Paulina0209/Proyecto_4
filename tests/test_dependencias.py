"""Todo paquete externo que el código importa está declarado (y con versión) en requirements.txt.

Así la imagen de Docker y cualquier instalación con ``pip install -r requirements.txt`` tienen todo lo necesario:
si alguien agrega una librería y no la declara, esta prueba falla antes de que falle en otra máquina.
"""
import ast
import re
import sys
import warnings
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
#: Módulo que se importa -> paquete que se instala (cuando no se llaman igual).
DISTRIBUCION = {"yaml": "PyYAML", "dotenv": "python-dotenv", "PIL": "Pillow", "pptx": "python-pptx",
                "langchain_core": "langchain-core", "langchain_openai": "langchain-openai", "langchain_ollama": "langchain-ollama"}
_IGNORAR = {".venv", "venv", "env", "site-packages", "__pycache__", ".claude", ".git"}


def _locales() -> set:
    nombres = {p.name for p in RAIZ.iterdir() if p.is_dir() and (p / "__init__.py").is_file()}
    return nombres | {p.stem for p in RAIZ.glob("*.py")}


def _importados() -> dict:
    locales, estandar = _locales(), set(sys.stdlib_module_names)
    encontrados = {}
    for archivo in RAIZ.rglob("*.py"):
        if _IGNORAR & set(archivo.relative_to(RAIZ).parts):
            continue
        try:
            with warnings.catch_warnings():  # avisos de sintaxis de otros archivos: no son de esta prueba
                warnings.simplefilter("ignore")
                arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Import):
                modulos = [a.name for a in nodo.names]
            elif isinstance(nodo, ast.ImportFrom) and nodo.module and nodo.level == 0:
                modulos = [nodo.module]
            else:
                continue
            for m in modulos:
                raiz = m.split(".")[0]
                if raiz not in estandar and raiz not in locales and raiz != "__future__":
                    encontrados.setdefault(raiz, archivo.relative_to(RAIZ).as_posix())
    return encontrados


def _declarados() -> dict:
    declarados = {}
    for linea in (RAIZ / "requirements.txt").read_text(encoding="utf-8").splitlines():
        linea = linea.split("#", 1)[0].strip()
        if linea:
            nombre = re.split(r"[=<>!~ ]", linea, maxsplit=1)[0]
            declarados[nombre.lower().replace("_", "-")] = linea
    return declarados


def test_todo_lo_que_se_importa_esta_en_requirements():
    declarados = _declarados()
    faltan = {modulo: donde for modulo, donde in _importados().items()
              if DISTRIBUCION.get(modulo, modulo).lower().replace("_", "-") not in declarados}
    assert not faltan, f"Importados pero no declarados en requirements.txt: {faltan}"


def test_las_dependencias_principales_tienen_version_fija():
    sueltas = [l for l in _declarados().values() if "==" not in l and ">=" not in l]
    assert not sueltas, f"Sin versión en requirements.txt: {sueltas}"
