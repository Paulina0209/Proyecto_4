"""NFR-01 — Tiempos de las funciones de IA contra sus objetivos.

    python -m operacion.rendimiento                 # sobre una copia de la base real
    python -m operacion.rendimiento --repeticiones 5

Mide, sobre un paciente real de cBioPortal (P-0016350) en una COPIA del
expediente:

    - IA-01: preguntas en lenguaje natural            objetivo < 2 s
    - IA-02: borrador de nota SOAP (GPT con presupuesto) objetivo < 10 s
    - IA-04: resumen para junta (GPT con presupuesto)   objetivo < 10 s

Con ``OPENAI_API_KEY`` las notas y resúmenes los redacta GPT; si el modelo no
responde dentro del presupuesto, ``operacion.presupuesto`` entrega el borrador
por reglas y el resultado dice cuántas veces pasó.
"""

from __future__ import annotations

import argparse
import contextlib
import shutil
import sqlite3
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from operacion.latencia import OBJETIVO_CONSULTA_S, OBJETIVO_NOTA_S, PERCENTIL_OBJETIVO, percentil

RAIZ = Path(__file__).resolve().parent.parent
PACIENTE = "P-0016350"
PREGUNTAS = ("¿Cuál es el EGFR?", "¿Cuál es el CEA más reciente?", "¿Tiene mutación de KRAS?")
NOTA_CONSULTA = (
    "Paciente con adenocarcinoma de pulmón EGFR L858R en osimertinib. Refiere tos seca leve, sin disnea. "
    "ECOG 1. TAC reciente con crecimiento de la lesión del lóbulo inferior derecho. "
    "Plan: biopsia líquida para mecanismos de resistencia y control en dos semanas."
)


@dataclass(frozen=True)
class MedicionOperacion:
    nombre: str
    repeticiones: int
    p50_ms: float
    p95_ms: float
    max_ms: float
    objetivo_ms: float
    detalle: str = ""

    @property
    def cumple(self) -> bool:
        return self.p95_ms <= self.objetivo_ms

    def a_dict(self) -> dict:
        return asdict(self) | {"cumple": self.cumple}

    def a_texto(self) -> str:
        return (
            f"  {'✔' if self.cumple else '✘'} {self.nombre:<34} p50 {self.p50_ms:>7.0f} ms · p{PERCENTIL_OBJETIVO} "
            f"{self.p95_ms:>7.0f} ms · máx {self.max_ms:>7.0f} ms (objetivo {self.objetivo_ms / 1000:.0f} s)"
            + (f"  {self.detalle}" if self.detalle else "")
        )


def medir(nombre: str, funcion: Callable[[], object], repeticiones: int, objetivo_s: float, detalle: Callable[[], str] = lambda: "") -> MedicionOperacion:
    tiempos: List[float] = []
    for _ in range(repeticiones):
        inicio = time.perf_counter()
        funcion()
        tiempos.append((time.perf_counter() - inicio) * 1000)
    return MedicionOperacion(
        nombre, repeticiones, round(percentil(tiempos, 50), 1), round(percentil(tiempos, PERCENTIL_OBJETIVO), 1),
        round(max(tiempos), 1), objetivo_s * 1000, detalle(),
    )


def medir_funciones_ia(conn: sqlite3.Connection, paciente_id: int, consulta_id: int, repeticiones: int = 3) -> List[MedicionOperacion]:
    from clinical_query import NaturalLanguageClinicalQueryService, SQLiteClinicalRepository
    from core import llm_config
    from expediente.adapters import construir_contexto_clinico, construir_contexto_resumen_caso
    from ia_clinica.notes.generator import ClinicalNoteGenerator
    from ia_clinica.notes.llm_client import RuleBasedLLMClient
    from ia_clinica.summary.generator import CaseSummaryGenerator
    from ia_clinica.summary.llm_client import RuleBasedSummaryLLMClient
    from operacion.presupuesto import LLMConPresupuesto, cliente_openai_para_presupuesto

    resultados = []
    servicio = NaturalLanguageClinicalQueryService(SQLiteClinicalRepository(conn))
    for pregunta in PREGUNTAS:
        resultados.append(medir(f"IA-01 «{pregunta}»", lambda p=pregunta: servicio.ask(str(paciente_id), p),
                                repeticiones * 3, OBJETIVO_CONSULTA_S))

    con_modelo = bool(llm_config.obtener_api_key())
    for nombre, generar, respaldo in (
        ("IA-02 nota SOAP", lambda c: ClinicalNoteGenerator(llm_client=c).generate_draft(
            construir_contexto_clinico(conn, consulta_id), format_name="SOAP"), RuleBasedLLMClient()),
        ("IA-04 resumen para junta", lambda c: CaseSummaryGenerator(llm_client=c).generate_summary(
            construir_contexto_resumen_caso(conn, paciente_id)), RuleBasedSummaryLLMClient()),
    ):
        principal = cliente_openai_para_presupuesto() if con_modelo else respaldo
        cliente = LLMConPresupuesto(principal, respaldo)
        usos: List[str] = []

        def una_vez(generar=generar, cliente=cliente, usos=usos):
            generar(cliente)
            usos.append(cliente.ultimo_uso.proveedor)

        def detalle(usos=usos):
            if not con_modelo:
                return "(sin OPENAI_API_KEY: reglas)"
            return f"GPT {usos.count('modelo')}, respaldo por reglas {usos.count('respaldo')}"

        resultados.append(medir(nombre, una_vez, repeticiones, OBJETIVO_NOTA_S, detalle))
    return resultados


@contextlib.contextmanager
def copia_del_expediente() -> sqlite3.Connection:
    """Copia de la base real con el paciente de la medición listo: consentimiento (SEC-03) y una consulta."""
    from historia_clinica.db import crear_conexion

    origen = RAIZ / "data" / "copiloto.db"
    if not origen.is_file():
        raise SystemExit("Falta la base real. Prepárela una vez con: python demo.py --solo pac")
    with tempfile.TemporaryDirectory(prefix="copiloto_rendimiento_", ignore_cleanup_errors=True) as carpeta:
        destino = Path(carpeta) / "copiloto.db"
        shutil.copyfile(origen, destino)
        conn = crear_conexion(str(destino))
        try:
            yield conn
        finally:
            conn.close()


def preparar_paciente(conn: sqlite3.Connection) -> tuple[int, int]:
    from expediente.registro import registrar_consulta
    from privacidad.consentimiento_ia import activar_consentimiento_ia, estado_consentimiento_ia, registrar_consentimiento_ia

    fila = conn.execute("SELECT id FROM pacientes WHERE identificacion LIKE ?", (f"%{PACIENTE}",)).fetchone()
    if fila is None:
        raise SystemExit(f"{PACIENTE} no está en el expediente. Corra una vez: python demo.py --solo pac")
    paciente_id = fila[0]
    activar_consentimiento_ia(conn, 1)
    if not estado_consentimiento_ia(conn, paciente_id).ia_habilitada:
        registrar_consentimiento_ia(conn, 1, paciente_id, medio="escrito", soporte=f"consentimiento-{PACIENTE}.pdf")
    return paciente_id, registrar_consulta(conn, paciente_id, "Control", NOTA_CONSULTA)


def main(argv: Optional[Sequence[str]] = None) -> int:
    for flujo in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError):
            flujo.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="python -m operacion.rendimiento", description="Tiempos de las funciones de IA (NFR-01).")
    p.add_argument("--repeticiones", type=int, default=3, help="Notas y resúmenes por medir (las preguntas, el triple).")
    args = p.parse_args(argv)

    with copia_del_expediente() as conn:
        paciente_id, consulta_id = preparar_paciente(conn)
        print(f"  Paciente real {PACIENTE} (id {paciente_id}) en una copia del expediente")
        resultados = medir_funciones_ia(conn, paciente_id, consulta_id, args.repeticiones)
    for r in resultados:
        print(r.a_texto())
    return 0 if all(r.cumple for r in resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
