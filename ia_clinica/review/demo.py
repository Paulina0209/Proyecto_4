"""Demo end-to-end de IA-03: borrador de IA-02 -> revisión -> aprobación.

Ejecútalo con (desde la raíz del repositorio):

    python -m ia_clinica.review.demo

Usa el modelo local ya configurado con Ollama (``OllamaLLMClient``) para
generar el borrador SOAP real que después se revisa y aprueba. Si Ollama
no está corriendo en esta máquina (``ollama serve`` + el modelo
descargado), el demo lo detecta y sigue funcionando con
``RuleBasedLLMClient`` para no bloquear la demostración del flujo de
revisión/aprobación de IA-03, que es independiente de qué generó el
borrador.

Se puede ajustar el modelo, la URL del servidor y el tiempo de espera sin
tocar código, con variables de entorno (útil para probar un modelo más
chico/rápido en una máquina sin GPU, o una URL distinta si
``http://127.0.0.1:11434`` no es la correcta en esa máquina):

    $env:OLLAMA_MODEL = "qwen2.5:7b-instruct-q4_K_M"
    $env:OLLAMA_TIMEOUT = "900"
    $env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
    python -m ia_clinica.review.demo
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from historia_clinica_mock.adapters import construir_contexto_clinico
from historia_clinica_mock.db import crear_conexion as crear_conexion_historia
from historia_clinica_mock.seed import sembrar_datos_sinteticos

from ia_clinica.notes.generator import ClinicalNoteGenerator
from ia_clinica.notes.llm_client import OllamaLLMClient, RuleBasedLLMClient
from ia_clinica.review import store
from ia_clinica.review.models import NotaYaAprobadaError
from ia_clinica.review.service import aprobar_nota, editar_seccion, iniciar_revision, obtener_revision


def _construir_generador() -> ClinicalNoteGenerator:
    kwargs = {}
    if os.environ.get("OLLAMA_MODEL"):
        kwargs["model"] = os.environ["OLLAMA_MODEL"]
    if os.environ.get("OLLAMA_TIMEOUT"):
        kwargs["timeout"] = int(os.environ["OLLAMA_TIMEOUT"])
    if os.environ.get("OLLAMA_BASE_URL"):
        kwargs["base_url"] = os.environ["OLLAMA_BASE_URL"]

    cliente = OllamaLLMClient(**kwargs)
    if cliente.esta_disponible():
        print("Usando OllamaLLMClient (modelo local real) para generar el borrador.")
        return ClinicalNoteGenerator(llm_client=cliente)

    print(f"Aviso: no se detectó un servidor Ollama en {kwargs.get('base_url', 'http://127.0.0.1:11434')}.")
    print("Se usa RuleBasedLLMClient como respaldo solo para poder demostrar IA-03 sin servidor local.")
    print("(Corre 'ollama serve' con el modelo descargado para usar el modelo real.)")
    return ClinicalNoteGenerator(llm_client=RuleBasedLLMClient())


def _mostrar(revision) -> None:
    print(f"  Estado: {revision.etiqueta_estado()}  (estado={revision.estado.value})")
    print(f"  ¿Es nota oficial?: {revision.es_nota_oficial()}")
    print(f"  Ediciones guardadas: {len(revision.historial_ediciones)}")
    print()


def main() -> None:
    conn_historia = crear_conexion_historia()
    ids = sembrar_datos_sinteticos(conn_historia)

    generador = _construir_generador()

    print("=" * 70)
    print("PASO 1: IA-02 genera el borrador (aún no hay revisión de IA-03)")
    print("=" * 70)
    contexto = construir_contexto_clinico(conn_historia, ids["consulta_maria_1"])
    borrador = generador.generate_draft(contexto, format_name="SOAP")
    print(borrador.to_text())

    # Usamos un archivo real (no ":memory:") para poder simular de verdad
    # "cerrar sesión": abrimos una conexión nueva más adelante apuntando
    # al mismo archivo, en vez de reutilizar el objeto Python en memoria.
    with tempfile.TemporaryDirectory() as tmp:
        ruta_db = str(Path(tmp) / "ia03_revisiones.db")

        conn_revision = store.crear_conexion(ruta_db)
        print("=" * 70)
        print("PASO 2: se inicia la revisión de IA-03 sobre ese borrador")
        print("=" * 70)
        revision = iniciar_revision(conn_revision, borrador)
        _mostrar(revision)

        print("=" * 70)
        print("PASO 3: el oncólogo edita manualmente la sección 'A' (AC1/AC2)")
        print("=" * 70)
        revision = editar_seccion(
            conn_revision,
            nota_id=revision.nota_id,
            seccion_key="A",
            nuevo_contenido="Impresión revisada por el oncólogo: progresión ósea confirmada por gammagrafía previa.",
            autor="dra. Ríos (oncóloga tratante)",
        )
        print("  Contenido actual de 'A':", revision.contenido_actual["A"])
        _mostrar(revision)

        conn_revision.close()  # <- "cierra sesión"

        print("=" * 70)
        print("PASO 4: se reabre una conexión NUEVA (simula volver a entrar) (AC3)")
        print("=" * 70)
        conn_revision = store.crear_conexion(ruta_db)
        revision = obtener_revision(conn_revision, borrador.consult_id)
        print("  La edición sigue guardada:", revision.contenido_actual["A"])
        _mostrar(revision)
        assert not revision.es_nota_oficial(), "una nota sin aprobar nunca debe leerse como oficial"

        print("=" * 70)
        print("PASO 5: aprobación explícita del médico autorizado (AC4)")
        print("=" * 70)
        revision = aprobar_nota(conn_revision, revision.nota_id, aprobado_por="dra. Ríos (oncóloga tratante)")
        _mostrar(revision)

        print("=" * 70)
        print("PASO 6: tras aprobarla, ya no se puede editar desde el flujo de borrador")
        print("=" * 70)
        try:
            editar_seccion(conn_revision, revision.nota_id, "A", "intento de cambio tardío", autor="alguien")
        except NotaYaAprobadaError as exc:
            print(f"  Rechazado correctamente: {exc}")

        conn_revision.close()

    conn_historia.close()


if __name__ == "__main__":
    main()
