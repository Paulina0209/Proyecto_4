"""Demo unificada del copiloto clínico sobre la base de datos real (cBioPortal).

    python demo.py                  # todas las secciones, con pausa entre cada una
    python demo.py --sin-pausa      # de corrido
    python demo.py --lista          # qué secciones hay
    python demo.py --solo tx ia     # solo algunas secciones
    python demo.py --sin-red        # sin OpenAI ni cBioPortal (requiere la base ya preparada)

Usa solo pacientes reales desidentificados de MSK-CHORD (cBioPortal):

    1. Prepara la base real si falta: el índice del estudio (13.159 pacientes
       de mama y pulmón) en ``data/copiloto.db`` y ``patients/db/pacientes.db``,
       y el detalle de los pacientes de la demo. La primera vez necesita
       internet (~20 s); después se reutiliza.
    2. Trabaja sobre una COPIA de esas bases en una carpeta temporal: lo que
       la demo registra (un paciente nuevo, notas, decisiones) no queda en
       la base real.

cBioPortal no trae notas de consulta ni las variables que requieren juicio
clínico (T/N/M, entorno de la enfermedad, línea de tratamiento…). En la demo
esas las registra el oncólogo, como en la práctica, y se muestran
etiquetadas como tales.

Las secciones con IA usan el modelo GPT del ``.env`` (docs/llm_openai.md).
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

RAIZ = Path(__file__).resolve().parent
ANCHO = 78
SALIDA = Path(tempfile.gettempdir()) / "copiloto_demo"
ESTUDIO = "msk_chord_2024"
ONCOLOGO_ID = 1
USUARIO_ID = 10
AUTOR = "dra. Gómez (oncóloga tratante)"

#: Pacientes reales de MSK-CHORD elegidos para la demo (vivos, con historial
#: coherente con su diagnóstico).
PACIENTES_DEMO = {
    "pulmon": ("P-0012063", "adenocarcinoma de pulmón metastásico, sin mutación impulsora en el panel"),
    "egfr": ("P-0016350", "adenocarcinoma de pulmón metastásico con EGFR L858R, en osimertinib"),
    "mama": ("P-0008538", "carcinoma de mama estadio IV tratado con quimioterapia"),
}


@dataclass
class Contexto:
    """Estado compartido entre secciones (bases de la copia e ids)."""

    ruta_expediente: Path
    ruta_pacientes: Path
    sin_red: bool
    ids_exp: Dict[str, int] = field(default_factory=dict)
    ids_pac: Dict[str, int] = field(default_factory=dict)
    _conn: Optional[sqlite3.Connection] = None

    @property
    def conn(self) -> sqlite3.Connection:
        """Conexión al expediente (copia de la base real)."""
        if self._conn is None:
            from historia_clinica.db import conectar_expediente

            self._conn = conectar_expediente(self.ruta_expediente)
        return self._conn

    def paciente(self, clave: str):
        from expediente.repository import obtener_paciente

        return obtener_paciente(self.conn, self.ids_exp[clave])

    def etiqueta(self, clave: str) -> str:
        return f"{PACIENTES_DEMO[clave][0]} ({PACIENTES_DEMO[clave][1]})"


# ---------------------------------------------------------------------------
# Presentación
# ---------------------------------------------------------------------------


def titulo(texto: str) -> None:
    print("\n" + "█" * ANCHO)
    print(f"  {texto}")
    print("█" * ANCHO)


def subtitulo(texto: str) -> None:
    print("\n" + "─" * ANCHO)
    print(texto)
    print("─" * ANCHO)


def nota(texto: str) -> None:
    print(f"  ⓘ {texto}")


def oncologo(texto: str) -> None:
    print(f"  ✎ El oncólogo registra: {texto}")


def _usar_ia(ctx: Contexto) -> bool:
    from core import llm_config

    return not ctx.sin_red and bool(llm_config.obtener_api_key())


def _descripcion_modelo(ctx: Contexto) -> str:
    from core import llm_config

    if ctx.sin_red:
        return "desactivado (--sin-red): se usa el cliente por reglas"
    if not llm_config.obtener_api_key():
        return "sin OPENAI_API_KEY en el .env: se usa el cliente por reglas"
    return llm_config.obtener_modelo()


def _cliente_llm(ctx: Contexto, respaldo):
    """OpenAILLMClient si hay llave y red; si no, el cliente por reglas."""
    if _usar_ia(ctx):
        from ia_clinica.notes.llm_client import OpenAILLMClient

        cliente = OpenAILLMClient()
        if cliente.esta_disponible():
            print(f"  Modelo: {cliente.model}")
            return cliente
        nota(f"No se pudo usar el modelo {cliente.model}; se usa el cliente por reglas.")
    else:
        nota(f"IA: {_descripcion_modelo(ctx)}.")
    return respaldo


# ---------------------------------------------------------------------------
# Preparación de la base real
# ---------------------------------------------------------------------------


def preparar_bd_real(sin_red: bool) -> Contexto:
    from cbioportal import ClienteCBioPortal, identificacion_cbioportal, importar_indice
    from cbioportal.importador import TIPOS_POR_DEFECTO
    from cbioportal.indice import CargadorDetalle, detalle_cargado
    from historia_clinica.db import conectar_expediente, crear_conexion, ruta_expediente
    from patients import db as db_pacientes

    ruta_exp, ruta_pac = ruta_expediente(), Path(db_pacientes.RUTA_DB)
    conn_exp = conectar_expediente(ruta_exp)
    conn_pac = db_pacientes.conectar(ruta_pac)
    db_pacientes.inicializar(conn_pac)
    try:
        total = conn_pac.execute("SELECT COUNT(*) FROM pacientes WHERE tipo_identificacion = 'externo'").fetchone()[0]
        if total == 0:
            if sin_red:
                raise SystemExit("La base real está vacía y --sin-red impide traerla de cBioPortal. "
                                 "Corre una vez `python demo.py` con internet.")
            print("  Preparando la base real: índice de MSK-CHORD (mama y pulmón) desde cBioPortal...", flush=True)
            inicio = time.monotonic()
            r = importar_indice(conn_exp, conn_pac, ClienteCBioPortal(), ESTUDIO, ONCOLOGO_ID, date.today(),
                                TIPOS_POR_DEFECTO, None)
            print(f"  {r.pacientes} pacientes en {time.monotonic() - inicio:.0f} s.")

        cargador = CargadorDetalle(lambda: crear_conexion(str(ruta_exp)))
        for clave, (paciente, _) in PACIENTES_DEMO.items():
            identificacion = identificacion_cbioportal(ESTUDIO, paciente)
            fila = conn_pac.execute("SELECT id FROM pacientes WHERE numero_identificacion = ?", (identificacion,)).fetchone()
            if fila is None:
                raise SystemExit(f"{paciente} no está en el índice de {ESTUDIO}.")
            if not detalle_cargado(conn_exp, identificacion):
                if sin_red:
                    raise SystemExit(f"Falta el detalle de {paciente} y --sin-red impide traerlo.")
                print(f"  Trayendo el detalle de {paciente} de cBioPortal...", flush=True)
                cargador.asegurar_detalle(conn_pac, fila[0])
    finally:
        conn_exp.close()
        conn_pac.close()

    carpeta = SALIDA / "bd"
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True)
    copia_exp, copia_pac = carpeta / "copiloto.db", carpeta / "pacientes.db"
    shutil.copyfile(ruta_exp, copia_exp)
    shutil.copyfile(ruta_pac, copia_pac)
    # Todo lo que abra "la base real" desde aquí (API, agente de TX) usa la copia.
    os.environ["COPILOTO_EXPEDIENTE_DB"] = str(copia_exp)

    ctx = Contexto(copia_exp, copia_pac, sin_red)
    for clave, (paciente, _) in PACIENTES_DEMO.items():
        identificacion = identificacion_cbioportal(ESTUDIO, paciente)
        ctx.ids_exp[clave] = ctx.conn.execute(
            "SELECT id FROM pacientes WHERE identificacion = ?", (identificacion,)).fetchone()[0]
        with contextlib.closing(sqlite3.connect(copia_pac)) as c:
            ctx.ids_pac[clave] = c.execute(
                "SELECT id FROM pacientes WHERE numero_identificacion = ?", (identificacion,)).fetchone()[0]
    return ctx


# ---------------------------------------------------------------------------
# 1. SEC-01 — Acceso seguro
# ---------------------------------------------------------------------------


def seccion_seguridad(ctx: Contexto) -> None:
    from seguridad import demo

    demo.main()


# ---------------------------------------------------------------------------
# 2. PAC-01/02/03 — Pacientes (API HTTP real)
# ---------------------------------------------------------------------------


def seccion_pacientes(ctx: Contexto) -> None:
    from fastapi.testclient import TestClient

    import patients.api as api

    api.DB_PATH = str(ctx.ruta_pacientes)
    api.CARGADOR_DETALLE = None  # se crea al arrancar, sobre la copia del expediente

    with TestClient(api.app) as cliente:
        subtitulo("PAC-02 — Búsqueda sobre los pacientes reales")
        for filtros in ({"diagnostico": "adenocarcinoma"}, {"diagnostico": "ductal"},
                        {"nombre": PACIENTES_DEMO["pulmon"][0]}, {"diagnostico": "sarcoma"}):
            inicio = time.monotonic()
            res = cliente.get("/pacientes/buscar", params={"oncologo_id": ONCOLOGO_ID, **filtros}).json()
            chips = " · ".join(f"{k}={v}" for k, v in filtros.items())
            print(f"\n  Filtros: {chips} -> {res['total']} resultado(s) en {(time.monotonic() - inicio) * 1000:.0f} ms")
            if res["total"] == 0:
                print(f"  ⓘ {res['mensaje']}")
            for p in res["items"][:3]:
                print(f"   · [{p['id']}] {p['nombre_completo']:<44} {', '.join(p['diagnosticos']) or '—'}")

        subtitulo("PAC-01 — Registro de un paciente nuevo")
        nuevo = {
            "nombre_completo": "Lucía Fernández", "fecha_nacimiento": "1979-08-21", "sexo": "femenino",
            "tipo_identificacion": "cedula", "numero_identificacion": "43210987",
            "contacto": {"telefono": "3104445566"}, "oncologo_id": ONCOLOGO_ID,
            "motivo_consulta_inicial": "Nódulo en mama izquierda",
        }
        r = cliente.post("/pacientes", json=nuevo)
        print(f"  POST /pacientes -> {r.status_code}: id {r.json()['id']}, {r.json()['nombre_completo']}")
        r = cliente.post("/pacientes", json=nuevo)
        print(f"  Mismo documento otra vez -> {r.status_code}: {r.json()['detail']['mensaje']}")
        r = cliente.post("/pacientes", json={**nuevo, "numero_identificacion": "12ab", "nombre_completo": ""})
        print(f"  Datos inválidos -> {r.status_code}:")
        for error in r.json()["detail"]["errores"]:
            print(f"   ✘ {error['campo']}: {error['mensaje']}")

        subtitulo(f"PAC-03 — Dashboard 360 de {ctx.etiqueta('mama')}")
        id_pac = ctx.ids_pac["mama"]
        cliente.get(f"/pacientes/{id_pac}", params={"oncologo_id": ONCOLOGO_ID, "usuario_id": USUARIO_ID})
        _mostrar_360(cliente.get(f"/pacientes/{id_pac}/resumen-360", params={"oncologo_id": ONCOLOGO_ID}).json())

        r = cliente.get(f"/pacientes/{id_pac}", params={"oncologo_id": 2})
        print(f"\n  Otro oncólogo pide este paciente -> {r.status_code} (solo ve sus propios pacientes)")

        if not ctx.sin_red:
            subtitulo("HC-01 — Detalle bajo demanda: abrir un paciente del índice que nunca se ha abierto")
            with contextlib.closing(sqlite3.connect(ctx.ruta_pacientes)) as c:
                fila = c.execute(
                    "SELECT id, nombre_completo FROM pacientes WHERE numero_identificacion = ?",
                    (f"CBIO:{ESTUDIO}:P-0014135",)).fetchone()
            inicio = time.monotonic()
            r360 = cliente.get(f"/pacientes/{fila[0]}/resumen-360", params={"oncologo_id": ONCOLOGO_ID}).json()
            print(f"  {fila[1]}: detalle traído de cBioPortal en {time.monotonic() - inicio:.1f} s")
            _mostrar_360(r360, breve=True)


def _mostrar_360(r360: dict, breve: bool = False) -> None:
    print(f"  {r360['nombre']} — {r360['diagnostico_principal']} (estadio {r360['estadio'] or 'no registrado'})")
    tx = r360["tratamiento_mas_reciente"]
    if tx:
        print(f"  Tratamiento más reciente: {tx['regimen']} ({tx['estado']}, desde {tx['fecha_inicio']})")
    for a in r360["alertas_activas"][:3]:
        print(f"   ! [{a['severidad']}] {a['descripcion']}")
    for etiqueta, clave in (("Laboratorio", "labs_recientes"), ("Imagen", "imagenes_recientes")):
        for item in r360[clave][: (1 if breve else 2)]:
            print(f"   {etiqueta}: {item['fecha']} — {(item.get('titulo') or '')} {item['resumen'][:110]}".rstrip())
    if r360["informacion_incompleta"]:
        print(f"  Campos faltantes: {', '.join(r360['campos_faltantes'])}")


# ---------------------------------------------------------------------------
# 3. HC-01 / HC-05 — Historia clínica real
# ---------------------------------------------------------------------------


def seccion_historia_clinica(ctx: Contexto) -> None:
    from historia_clinica.informacion_faltante import evaluar_informacion_faltante
    from historia_clinica.integracion_externa import antecedentes_externos_de_paciente, listar_sincronizaciones

    subtitulo(f"HC-01 — Historia importada de cBioPortal: {ctx.etiqueta('egfr')}")
    pid = ctx.ids_exp["egfr"]
    for s in listar_sincronizaciones(ctx.conn, pid):
        print(f"  Sincronización: {s.fuente} [{s.formato}] {s.estado}: {s.registros_importados} registros ({s.fecha[:10]})")
    for a in antecedentes_externos_de_paciente(ctx.conn, pid)[:8]:
        print(f"   · {a.fecha or '—'} {a.descripcion[:100]}")

    for clave in ("mama", "pulmon"):
        subtitulo(f"HC-05 — ¿Qué falta para decidir? {ctx.etiqueta(clave)}")
        ev = evaluar_informacion_faltante(ctx.conn, ctx.ids_exp[clave])
        print(f"  Estado: {ev.estado.value}")
        for item in ev.faltantes:
            print(f"   ✘ {item.descripcion} — {item.motivo}")
        for item_id, fuente in ev.presentes:
            print(f"   ✔ {item_id} (respaldo: {fuente})")
    nota("Nada que requiera juicio clínico se deriva de cBioPortal: queda faltante para que lo registre el oncólogo.")


# ---------------------------------------------------------------------------
# 4. IA-01 … IA-06 — Asistente de IA
# ---------------------------------------------------------------------------

NOTA_CONSULTA_PULMON = (
    "Paciente refiere tos persistente y disnea de moderados esfuerzos desde hace tres semanas. "
    "Niega fiebre. Examen físico: murmullo vesicular disminuido en base derecha, sin adenopatías "
    "supraclaviculares palpables. Impresión diagnóstica: sospecha de progresión de enfermedad "
    "pulmonar metastásica. Plan: se solicita TAC de tórax con contraste y control en dos semanas."
)


def seccion_ia(ctx: Contexto) -> None:
    import demo_ia01
    from clinical_query import NaturalLanguageClinicalQueryService, SQLiteClinicalRepository
    from expediente.adapters import construir_contexto_clinico, construir_contexto_resumen_caso
    from expediente.registro import registrar_consulta
    from ia_clinica.explainability import PatientRecommendationService
    from ia_clinica.notes.generator import ClinicalNoteGenerator
    from ia_clinica.notes.llm_client import RuleBasedLLMClient
    from ia_clinica.review import store
    from ia_clinica.review.models import NotaYaAprobadaError
    from ia_clinica.review.service import aprobar_nota, editar_seccion, iniciar_revision
    from ia_clinica.summary.generator import CaseSummaryGenerator
    from ia_clinica.summary.llm_client import RuleBasedSummaryLLMClient

    subtitulo("IA-01 / IA-06 — Preguntas en lenguaje natural sobre el paciente activo")
    servicio = NaturalLanguageClinicalQueryService(SQLiteClinicalRepository(ctx.conn))
    for clave, pregunta in (
        ("mama", "¿Cuál es el CEA más reciente?"),
        ("mama", "¿Cuál es el CA 15-3?"),
        ("pulmon", "¿Tiene mutación de KRAS?"),
        ("egfr", "¿Cuál es el EGFR?"),
        ("pulmon", "¿Cuál es el HER2 y el CEA?"),
        ("pulmon", f"¿Cuál es el EGFR de {PACIENTES_DEMO['egfr'][0]}?"),
        ("pulmon", "¿Cuál es la hemoglobina?"),
    ):
        print(f"\n  Oncólogo ({PACIENTES_DEMO[clave][0]}) > {pregunta}")
        respuesta = servicio.ask(str(ctx.ids_exp[clave]), pregunta)
        print(f"  Asistente > {respuesta.answer}")
        if respuesta.needs_clarification:
            nota("Ambigua: pide aclaración en vez de adivinar (IA-06).")

    subtitulo(f"IA-05 — Recomendaciones explicables: {ctx.etiqueta('egfr')}")
    demo_ia01.mostrar_recomendaciones(ctx.conn, ctx.paciente("egfr"), PatientRecommendationService())

    subtitulo(f"IA-02 + IA-03 — Nota SOAP de la consulta de hoy: {ctx.etiqueta('pulmon')}")
    consulta_id = registrar_consulta(ctx.conn, ctx.ids_exp["pulmon"], "Control", NOTA_CONSULTA_PULMON)
    oncologo(f"nota de la consulta #{consulta_id}:\n    «{NOTA_CONSULTA_PULMON}»")
    generador = ClinicalNoteGenerator(llm_client=_cliente_llm(ctx, RuleBasedLLMClient()))
    borrador = generador.generate_draft(construir_contexto_clinico(ctx.conn, consulta_id), format_name="SOAP")
    print(borrador.to_text())

    conn_rev = store.crear_conexion(str(SALIDA / "bd" / "revisiones.db"))
    revision = iniciar_revision(conn_rev, borrador)
    print(f"  IA-03: estado {revision.etiqueta_estado()}")
    revision = editar_seccion(conn_rev, nota_id=revision.nota_id, seccion_key="P",
                              nuevo_contenido="TAC de tórax con contraste; control en dos semanas con resultado.",
                              autor=AUTOR)
    print(f"  El oncólogo corrige el plan -> ediciones guardadas: {len(revision.historial_ediciones)}; "
          f"¿oficial?: {revision.es_nota_oficial()}")
    revision = aprobar_nota(conn_rev, revision.nota_id, aprobado_por=AUTOR)
    print(f"  Aprobada -> {revision.etiqueta_estado()}; ¿oficial?: {revision.es_nota_oficial()}")
    try:
        editar_seccion(conn_rev, revision.nota_id, "P", "cambio tardío", autor="otro usuario")
    except NotaYaAprobadaError as exc:
        print(f"  Intento de editarla después -> rechazado: {exc}")
    conn_rev.close()

    subtitulo(f"IA-04 — Resumen para junta médica: {ctx.etiqueta('mama')}")
    generador = CaseSummaryGenerator(llm_client=_cliente_llm(ctx, RuleBasedSummaryLLMClient()))
    resumen = generador.generate_summary(construir_contexto_resumen_caso(ctx.conn, ctx.ids_exp["mama"]))
    print(resumen.to_text())


# ---------------------------------------------------------------------------
# 5. DX-01/02/03 — Diagnóstico
# ---------------------------------------------------------------------------


def seccion_diagnostico(ctx: Contexto) -> None:
    from dx_clinica.builder import construir_diagnosticos_diferenciales
    from dx_clinica.incertidumbre import analizar_incertidumbre
    from dx_clinica.juicio_clinico import (
        inicializar_esquema,
        obtener_decision_diagnostica_vigente,
        registrar_juicio_clinico,
    )
    from dx_clinica.recomendacion_estudios import recomendar_estudios
    from expediente.adapters import obtener_hallazgos_de_paciente

    clave = "egfr"
    paciente, hallazgos = ctx.paciente(clave), obtener_hallazgos_de_paciente(ctx.conn, ctx.ids_exp[clave])
    print(f"  Paciente: {ctx.etiqueta(clave)} — {len(hallazgos)} hallazgos en el expediente")

    subtitulo("DX-01 — Estudios sugeridos ante sospecha de progresión")
    r = recomendar_estudios(paciente_id=paciente.id, sospecha_diagnostica="Sospecha de progresión de enfermedad pulmonar metastásica",
                            hallazgos=hallazgos, ahora=datetime.now())
    for e in r.estudios_sugeridos:
        print(f"   #{e.orden} [{e.tipo}] {e.nombre} — {e.justificacion}")
    for o in r.estudios_omitidos_por_redundantes:
        print(f"   (no se repite) {o.nombre}: {o.motivo}")

    subtitulo("DX-02 — Diagnóstico diferencial")
    resultado = construir_diagnosticos_diferenciales(paciente, hallazgos)
    print(f"  *** {resultado.disclaimer} ***")
    if resultado.esta_vacio():
        print(f"  (sin candidatos) {resultado.advertencia_sin_sustento}")
    for c in resultado.candidatos:
        print(f"\n  #{c.orden} — {c.nombre} ({c.resumen_sustento})")
        for criterio in c.criterios_sustentados:
            textos = [h.texto[:120] for h in hallazgos if h.id in criterio.hallazgos_ids][:2]
            print(f"     [sustentado] {criterio.descripcion}")
            for t in textos:
                print(f"        ← {t}")
        for descripcion in c.criterios_sin_sustento:
            print(f"     [sin dato]   {descripcion}")

    subtitulo("DX-03 — Incertidumbre y juicio clínico")
    analisis = analizar_incertidumbre(resultado)
    print(f"  ¿Incertidumbre?: {analisis.hay_incertidumbre} ({', '.join(t.value for t in analisis.tipos) or '—'})")
    print(f"  {analisis.mensaje}")
    for s in analisis.informacion_adicional_sugerida:
        print(f"   - {s}")
    inicializar_esquema(ctx.conn)
    registrar_juicio_clinico(ctx.conn, paciente_id=paciente.id, autor=AUTOR, resultado_sistema=resultado,
                             diagnostico_registrado="Progresión radiológica bajo osimertinib; se solicita rebiopsia "
                                                    "para evaluar mecanismos de resistencia.")
    vigente = obtener_decision_diagnostica_vigente(ctx.conn, paciente.id, resultado)
    print(f"  Decisión vigente: fuente={vigente.fuente!r} -> {vigente.contenido}")


# ---------------------------------------------------------------------------
# 6. EST-01/02/03 — Estadificación
# ---------------------------------------------------------------------------


def seccion_estadificacion(ctx: Contexto) -> None:
    from estadificacion.builder import proponer_estadificacion
    from estadificacion.confirmacion import confirmar_estadificacion, inicializar_esquema, obtener_estadificacion_vigente
    from estadificacion.incompleta import analizar_estadificacion_incompleta
    from expediente.registro import registrar_datos_clinicos

    clave = "pulmon"
    pid = ctx.ids_exp[clave]
    print(f"  Paciente: {ctx.etiqueta(clave)}")

    def proponer():
        propuesta = proponer_estadificacion(ctx.conn, pid)
        analisis = analizar_estadificacion_incompleta(propuesta)
        print(f"  Sistema: {propuesta.sistema_id} {propuesta.sistema_nombre} (v{propuesta.sistema_version})")
        for c in propuesta.componentes:
            print(f"   {c.codigo} = {c.valor} (fuente: {', '.join(c.fuente_ids)})")
        print(f"  EST-01: {propuesta.fundamento_global}")
        print(f"  EST-03: {analisis.mensaje}")
        return propuesta

    subtitulo("EST-01/EST-03 — Con lo que trae cBioPortal (sin T/N/M)")
    proponer()

    subtitulo("El oncólogo documenta M1 (el registro de tumores dice 'Distant metastases')")
    registrar_datos_clinicos(ctx.conn, pid, {"clinical_m_status": "cM1"})
    oncologo("clinical_m_status = cM1")
    propuesta = proponer()

    subtitulo("EST-02 — Confirmación del médico")
    inicializar_esquema(ctx.conn)
    c = confirmar_estadificacion(ctx.conn, pid, estadio_confirmado="IV", autor=AUTOR, propuesta_sistema=propuesta)
    vigente = obtener_estadificacion_vigente(ctx.conn, pid, propuesta)
    print(f"  Confirmado: {c.estadio_confirmado} (sugerencia del sistema: {c.estadio_sugerido_por_sistema}; "
          f"difiere: {c.difiere_de_sugerencia}) -> vigente {vigente.estadio} ({vigente.fuente})")


# ---------------------------------------------------------------------------
# 7. TX-01 … TX-04 — Tratamiento
# ---------------------------------------------------------------------------


def seccion_tratamiento(ctx: Contexto) -> None:
    from clinical_decision.registro import registrar_decision_tratamiento
    from expediente.registro import registrar_datos_clinicos
    from patients.medicacion_actual import registrar_conciliacion
    from tx_clinica.tools._db import conn_lock, obtener_conexion
    from tx_clinica.tools._interaction_shared import resolver_chequeo_interacciones
    from tx_clinica.tools.interaction_tools import chequear_interacciones_tratamiento
    from tx_clinica.tools.recommendation_tools import obtener_recomendaciones_tratamiento_por_id

    conn_tx = obtener_conexion()  # misma copia del expediente
    clave = "pulmon"
    pid = ctx.ids_exp[clave]
    print(f"  Paciente: {ctx.etiqueta(clave)}")

    def recomendar() -> dict:
        r = json.loads(obtener_recomendaciones_tratamiento_por_id.invoke({"patient_id": pid}))
        if r.get("requiere_mas_datos"):
            print(f"  → {r['mensaje']}")
            for modulo, variables in r["variables_faltantes_por_modulo"].items():
                print(f"     {modulo}: {', '.join(variables)}")
        elif r.get("sin_guia_aplicable"):
            print(f"  → {r['mensaje']}")
        else:
            print(f"  → Guía aplicada: {r['module_id']}")
            if r.get("variables_faltantes_para_candidatos"):
                print(f"  → {r['mensaje']}")
                print(f"     Variables: {', '.join(r['variables_faltantes_para_candidatos'])}")
            for i, c in enumerate(r["candidatos"], 1):
                fase = f" ({c['fase']})" if c["fase"] else ""
                print(f"   {i}. {c['regimen_id']}{fase}: {' + '.join(c['farmacos'])} [{c['audit_effect']}]")
                print(f"      regla {c['rule_id_disparada']} — {' '.join((c['evidencia'] or '').split())}")
        return r

    def registrar(datos: dict, porque: str) -> None:
        with conn_lock:
            registrar_datos_clinicos(conn_tx, pid, datos)
        oncologo(f"{', '.join(f'{k}={v}' for k, v in datos.items())}  ({porque})")

    subtitulo("TX-01 — Paso 1: solo con los datos de cBioPortal")
    recomendar()
    registrar({"disease_setting": "metastatic", "molecular_pathway_status": "non_oncogene_addicted"},
              "estadio IV; panel sin alteraciones en EGFR/ALK/ROS1/RET/MET/BRAF/KRAS")
    subtitulo("TX-01 — Paso 2")
    recomendar()
    registrar({"treatment_line": 1, "immunotherapy_contraindication": "no", "major_comorbidity_precluding_ici": "no",
               "prior_ici": "no"}, "sin tratamiento sistémico previo en el historial; sin contraindicación")
    subtitulo("TX-01 + TX-02 — Paso 3: opciones según la guía, con nivel de evidencia")
    r = recomendar()
    nota("PD-L1 TPS no está en cBioPortal (solo positivo/negativo): las opciones que dependen del TPS no se evalúan.")

    if r.get("candidatos"):
        regimen = r["candidatos"][0]["regimen_id"]
        subtitulo(f"TX-03 — Interacciones para {regimen}")
        chequeo = json.loads(chequear_interacciones_tratamiento.invoke({"patient_id": pid, "regimen_id": regimen}))
        print(f"  ¿Requiere conciliar medicación?: {chequeo.get('requiere_conciliacion_medicamentos')}; "
              f"¿sin interacciones conocidas?: {chequeo.get('sin_interacciones_conocidas')}")
        nota("La medicación concomitante no viene de cBioPortal: sin conciliar, el sistema NO afirma 'sin interacciones'.")
        with conn_lock:
            registrar_conciliacion(conn_tx, pid, [], ONCOLOGO_ID)
        oncologo("conciliación de medicamentos: sin medicación concomitante")
        chequeo = json.loads(chequear_interacciones_tratamiento.invoke({"patient_id": pid, "regimen_id": regimen}))
        print(f"  ¿Requiere conciliar medicación?: {chequeo.get('requiere_conciliacion_medicamentos')}; "
              f"¿sin interacciones conocidas?: {chequeo.get('sin_interacciones_conocidas')}")
        if chequeo.get("advertencia_cobertura_incompleta"):
            nota("El catálogo de interacciones no cubre todo el régimen: se advierte en vez de dar garantías.")

        subtitulo("TX-04 — Registrar la decisión del oncólogo")
        candidatos = [c["regimen_id"] for c in r["candidatos"]]
        resolucion = resolver_chequeo_interacciones(pid, regimen)
        with conn_lock:
            res = registrar_decision_tratamiento(
                conn_tx, paciente_id=pid, oncologo_id=ONCOLOGO_ID, tipo_decision="accept",
                recomendacion_ia_snapshot={"modulo": r["module_id"], "candidatos": candidatos},
                regimenes_candidatos_ids=candidatos, regimen_sugerido_id=regimen,
                chequeo_interacciones=resolucion.chequeo)
        print(f"  El oncólogo acepta {regimen} -> registrada: {res.exito}. {res.motivo_rechazo or ''}".rstrip())

    subtitulo(f"TX-01 — Caso con driver: {ctx.etiqueta('egfr')}")
    pid_egfr = ctx.ids_exp["egfr"]
    with conn_lock:
        registrar_datos_clinicos(conn_tx, pid_egfr, {"disease_setting": "metastatic", "molecular_pathway_status": "oncogene_addicted"})
    oncologo("disease_setting=metastatic, molecular_pathway_status=oncogene_addicted (EGFR L858R)")
    r = json.loads(obtener_recomendaciones_tratamiento_por_id.invoke({"patient_id": pid_egfr}))
    print(f"  → {r.get('mensaje')}")
    nota("El módulo de adicción oncogénica solo audita concordancia: el sistema no inventa una sugerencia genérica.")

    subtitulo("Agente conversacional de tratamiento (GPT + herramientas + aprobación humana)")
    _agente_tratamiento(ctx, pid)


def _agente_tratamiento(ctx: Contexto, paciente_id: int) -> None:
    from core import llm_config

    if not _usar_ia(ctx):
        nota(f"Omitido: {_descripcion_modelo(ctx)}.")
        return
    if not os.environ.get("LANGFUSE_PUBLIC_KEY"):
        os.environ.setdefault("LANGFUSE_TRACING_ENABLED", "false")

    from tx_clinica.agent import construir_agente
    from tx_clinica.conversacion import enviar_mensaje

    pregunta = (f"Resume las opciones de primera línea del paciente {paciente_id} y qué dato clínico "
                "falta para evaluar las demás opciones de la guía.")
    print(f"  Modelo: {llm_config.obtener_modelo()}")
    print(f"  Oncólogo > {pregunta}")
    with contextlib.redirect_stderr(io.StringIO()):
        agente = construir_agente()
        respuesta = enviar_mensaje(agente, pregunta, f"demo-unificada-{datetime.now():%H%M%S}", ONCOLOGO_ID)
    herramientas = [tc["name"] for m in respuesta.mensajes for tc in (getattr(m, "tool_calls", None) or [])]
    print(f"  (herramientas usadas: {', '.join(dict.fromkeys(herramientas)) or 'ninguna'})")
    print(f"  Agente > {respuesta.mensajes[-1].text}")
    nota("Si el agente intenta registrar una decisión (TX-04), la ejecución se pausa hasta que el médico apruebe.")


# ---------------------------------------------------------------------------
# 8. EV-01 / CFG-01 — Evidencia y guías institucionales
# ---------------------------------------------------------------------------


def seccion_evidencia(ctx: Contexto) -> None:
    import demo_ia01
    from configuracion.guias_institucionales import (
        ProtocoloInterno,
        buscar_evidencia_institucional,
        configurar_guias,
        crear_conexion,
        obtener_configuracion_vigente,
    )
    from evidencia_clinica import EvidenceSearchService
    from seguridad.models import Rol, Usuario

    servicio = EvidenceSearchService()
    subtitulo(f"EV-01 — Evidencia para {ctx.etiqueta('pulmon')}")
    demo_ia01.mostrar_evidencia(ctx.conn, ctx.paciente("pulmon"), servicio)
    subtitulo("EV-01 — Búsqueda libre sin coincidencias")
    demo_ia01.mostrar_evidencia(ctx.conn, ctx.paciente("pulmon"), servicio, "glioblastoma pediátrico")

    subtitulo("CFG-01 — Guías clínicas institucionales")
    cfg = crear_conexion()
    vigente = obtener_configuracion_vigente(cfg)
    print(f"  Sin configurar: {', '.join(vigente.organizaciones)} (por defecto), {len(vigente.modulos_habilitados)} módulos")
    admin = Usuario(id=1, nombre_usuario="adm.clinico", rol=Rol.ADMINISTRADOR_CLINICO, activo=True)
    r = configurar_guias(cfg, admin, ["NCCN", "ESMO"], "Acta del comité de oncología 2026-09",
                         protocolo_interno=ProtocoloInterno("Protocolo de pulmón v2", "DOC-ONC-021"))
    print(f"  El administrador clínico configura NCCN > ESMO -> versión {obtener_configuracion_vigente(cfg).version}")
    for adv in r.advertencias:
        print(f"   ⚠ {adv}")
    oncologa = Usuario(id=2, nombre_usuario="dra.gomez", rol=Rol.ONCOLOGO, activo=True)
    r = configurar_guias(cfg, oncologa, ["ESMO"], "Prefiero ESMO")
    print(f"  Una oncóloga intenta cambiarla -> aceptado: {r.exito}. {r.motivo_rechazo or ''}".rstrip())
    resultados = buscar_evidencia_institucional(cfg, "non-small-cell lung cancer metastatic")
    print(f"  Evidencia filtrada por la configuración institucional: {len(resultados)} resultado(s)")
    for res in resultados[:3]:
        print(f"   · {res.document.organization} — {res.document.title.strip()}")
    cfg.close()


# ---------------------------------------------------------------------------
# 9. DOC-02 / DOC-01 — Documentos
# ---------------------------------------------------------------------------


def seccion_documentos(ctx: Contexto) -> None:
    from documentos_clinicos.adaptadores import (
        expediente_completo_a_documento_exportable,
        resumen_caso_a_documento_exportable,
    )
    from documentos_clinicos.carga_documentos import (
        FormatoNoSoportadoError,
        cargar_documento_clinico,
        crear_conexion,
        listar_documentos_de_paciente,
    )
    from documentos_clinicos.pdf_export import exportar_a_pdf
    from expediente.adapters import construir_contexto_resumen_caso
    from ia_clinica.summary.generator import CaseSummaryGenerator
    from ia_clinica.summary.llm_client import RuleBasedSummaryLLMClient

    clave = "mama"
    pid = ctx.ids_exp[clave]
    carpeta = SALIDA / "pdf"
    carpeta.mkdir(parents=True, exist_ok=True)

    subtitulo(f"DOC-02 — Exportar a PDF: {ctx.etiqueta(clave)}")
    resumen = CaseSummaryGenerator(llm_client=RuleBasedSummaryLLMClient()).generate_summary(
        construir_contexto_resumen_caso(ctx.conn, pid))
    ruta_resumen = carpeta / f"resumen_{PACIENTES_DEMO[clave][0]}.pdf"
    r1 = exportar_a_pdf(resumen_caso_a_documento_exportable(resumen), str(ruta_resumen))
    r2 = exportar_a_pdf(expediente_completo_a_documento_exportable(ctx.conn, pid),
                        str(carpeta / f"expediente_{PACIENTES_DEMO[clave][0]}.pdf"))
    for r in (r1, r2):
        print(f"  PDF generado: {r.ruta} ({r.bytes_escritos} bytes)")

    subtitulo("DOC-01 — Cargar documentos al expediente")
    conn_docs = crear_conexion(str(SALIDA / "bd" / "documentos.db"))
    doc = cargar_documento_clinico(conn=conn_docs, conn_historia=ctx.conn, paciente_id=pid,
                                   nombre_archivo=ruta_resumen.name, contenido=ruta_resumen.read_bytes(),
                                   cargado_por="dra.gomez", directorio_almacenamiento=SALIDA / "documentos")
    print(f"  Cargado: {doc.nombre_archivo_original} -> tipo {doc.tipo_documento}, id {doc.id}")
    try:
        cargar_documento_clinico(conn=conn_docs, conn_historia=ctx.conn, paciente_id=pid,
                                 nombre_archivo="notas.txt", contenido=b"texto plano",
                                 cargado_por="dra.gomez", directorio_almacenamiento=SALIDA / "documentos")
    except FormatoNoSoportadoError as exc:
        print(f"  notas.txt -> rechazado: {exc}")
    print(f"  Documentos del paciente: {len(listar_documentos_de_paciente(conn_docs, pid))}")
    conn_docs.close()


# ---------------------------------------------------------------------------
# 10. AUD-01/02 — Auditoría de lo que hizo la demo
# ---------------------------------------------------------------------------


def seccion_auditoria(ctx: Contexto) -> None:
    from auditoria.registro_acceso import inicializar_schema as inicializar_auditoria
    from auditoria.registro_acceso import obtener_eventos_de_paciente
    from auditoria.trazabilidad_ia import obtener_trazabilidad_ia_paciente
    from clinical_decision.registro import inicializar_schema as inicializar_tx
    from dx_clinica.juicio_clinico import inicializar_esquema as inicializar_dx
    from estadificacion.confirmacion import inicializar_esquema as inicializar_est

    subtitulo(f"AUD-01 — Accesos registrados al expediente de {ctx.etiqueta('mama')}")
    with contextlib.closing(sqlite3.connect(ctx.ruta_pacientes)) as conn_pac:
        conn_pac.row_factory = sqlite3.Row
        inicializar_auditoria(conn_pac)
        eventos = obtener_eventos_de_paciente(conn_pac, ctx.ids_pac["mama"])
    for e in eventos:
        print(f"  [{e.fecha[:19]}] usuario={e.usuario_id} acción={e.accion.value} {e.detalle or ''}".rstrip())
    if not eventos:
        nota("Sin accesos: corre también la sección 'pac'.")

    subtitulo("AUD-02 — Sugerencias de la IA frente a decisiones del médico (DX + EST + TX)")
    for inicializar in (inicializar_dx, inicializar_est, inicializar_tx):
        inicializar(ctx.conn)
    registros = [
        r for clave in ("egfr", "pulmon")
        for r in obtener_trazabilidad_ia_paciente(paciente_id=ctx.ids_exp[clave], conn_dx=ctx.conn,
                                                  conn_est=ctx.conn, conn_tx=ctx.conn)
    ]
    for r in registros:
        print(f"  [{r.dominio}] paciente {r.paciente_id} | IA: {str(r.recomendacion_sistema)[:60]!r} -> médico: "
              f"{str(r.decision_medico)[:70]!r} (difiere: {r.difiere_de_sugerencia})")
    if not registros:
        nota("Sin decisiones registradas: corre también las secciones 'dx', 'est' y 'tx'.")


# ---------------------------------------------------------------------------
# 11. NFR-06 — Datos personales
# ---------------------------------------------------------------------------


def seccion_privacidad(ctx: Contexto) -> None:
    from privacidad.models import EstadoAutorizacion, Finalidad
    from privacidad.tratamiento_datos import (
        configurar_politica,
        crear_conexion,
        registrar_autorizacion,
        verificar_tratamiento_permitido,
    )

    conn = crear_conexion()
    pid = ctx.ids_exp["pulmon"]
    configurar_politica(
        conn, 1, codigo="co-pacientes", jurisdiccion="Colombia",
        nombre="Política de tratamiento de datos de pacientes",
        marco_normativo="Referencia definida por la institución",
        finalidades=(Finalidad("atencion_clinica", "Prestación del servicio de salud", False),
                     Finalidad("investigacion", "Uso de datos seudonimizados en investigación", True)),
        bases_legales=("autorizacion_titular", "prestacion_servicio_salud"),
        derechos=("acceso", "rectificacion", "supresion", "revocacion"),
        plazo_respuesta_dias=15, ahora=datetime.now(timezone.utc),
    )
    print(f"  Paciente: {ctx.etiqueta('pulmon')}")
    print("  Política 'co-pacientes' (Colombia): atención clínica sin autorización, investigación con autorización.")

    def consultar(momento: str, finalidad: str = "investigacion") -> None:
        d = verificar_tratamiento_permitido(conn, pid, "co-pacientes", finalidad)
        print(f"   {momento:<30} -> {'permitido' if d.permitido else 'NO permitido'}: {d.motivo}")

    consultar("Atención clínica:", "atencion_clinica")
    consultar("Investigación, sin autorización:")
    registrar_autorizacion(conn, 2, paciente_id=pid, codigo_politica="co-pacientes", finalidad="investigacion",
                           base_legal="autorizacion_titular", medio="escrito", evidencia_ref="documento-42")
    consultar("Investigación, autorizada:")
    registrar_autorizacion(conn, 2, paciente_id=pid, codigo_politica="co-pacientes", finalidad="investigacion",
                           base_legal="autorizacion_titular", estado=EstadoAutorizacion.REVOCADA)
    consultar("Investigación, tras revocarla:")
    conn.close()


# ---------------------------------------------------------------------------
# Orquestación
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Seccion:
    clave: str
    historias: str
    nombre: str
    funcion: Callable[[Contexto], None]


SECCIONES: List[Seccion] = [
    Seccion("sec", "SEC-01", "Registro de usuarios, autenticación y control de acceso por rol", seccion_seguridad),
    Seccion("pac", "PAC-01 · PAC-02 · PAC-03 · HC-01", "Pacientes: búsqueda, registro y dashboard 360", seccion_pacientes),
    Seccion("hc", "HC-01 · HC-05", "Historia clínica importada e información faltante", seccion_historia_clinica),
    Seccion("ia", "IA-01 … IA-06", "Asistente de IA: preguntas, explicabilidad, nota SOAP y resumen", seccion_ia),
    Seccion("dx", "DX-01 · DX-02 · DX-03", "Diagnóstico", seccion_diagnostico),
    Seccion("est", "EST-01 · EST-02 · EST-03", "Estadificación", seccion_estadificacion),
    Seccion("tx", "TX-01 … TX-04", "Tratamiento: guía, evidencia, interacciones, decisión y agente", seccion_tratamiento),
    Seccion("ev", "EV-01 · CFG-01", "Evidencia científica y guías institucionales", seccion_evidencia),
    Seccion("doc", "DOC-02 · DOC-01", "Exportación a PDF y carga de documentos", seccion_documentos),
    Seccion("aud", "AUD-01 · AUD-02", "Auditoría de accesos y trazabilidad de la IA", seccion_auditoria),
    Seccion("priv", "NFR-06", "Datos personales: autorizaciones por finalidad", seccion_privacidad),
]


def _argumentos(argv) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python demo.py", description="Demo unificada del copiloto clínico (datos reales).")
    p.add_argument("--solo", nargs="+", metavar="SECCION", choices=[s.clave for s in SECCIONES],
                   help="Correr solo estas secciones (ver --lista).")
    p.add_argument("--sin-pausa", action="store_true", help="No esperar Enter entre secciones.")
    p.add_argument("--sin-red", action="store_true", help="No usar OpenAI ni cBioPortal (la base ya debe estar preparada).")
    p.add_argument("--lista", action="store_true", help="Mostrar las secciones y salir.")
    return p.parse_args(argv)


def main(argv=None) -> int:
    for flujo in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError):
            flujo.reconfigure(encoding="utf-8")
    sys.path.insert(0, str(RAIZ))
    os.chdir(RAIZ)

    args = _argumentos(argv)
    if args.lista:
        for s in SECCIONES:
            print(f"  {s.clave:<5} {s.historias:<34} {s.nombre}")
        return 0

    titulo("COPILOTO CLÍNICO PARA ONCOLOGÍA — DEMO UNIFICADA (datos reales)")
    SALIDA.mkdir(parents=True, exist_ok=True)
    ctx = preparar_bd_real(args.sin_red)
    print(f"  Fuente: cBioPortal, estudio {ESTUDIO} (pacientes reales desidentificados)")
    print(f"  Se trabaja sobre una copia de la base real en {SALIDA / 'bd'}")
    print("  Pacientes de la demo:")
    for clave in PACIENTES_DEMO:
        print(f"   · {ctx.etiqueta(clave)}")
    print(f"  Modelo de lenguaje: {_descripcion_modelo(ctx)}")

    seleccion = [s for s in SECCIONES if not args.solo or s.clave in args.solo]
    pausar = not args.sin_pausa and sys.stdin.isatty()
    fallidas = []
    for n, s in enumerate(seleccion, 1):
        if pausar and n > 1:
            try:
                input(f"\n[Enter] para continuar con «{s.nombre}» (Ctrl+C para salir) ")
            except (KeyboardInterrupt, EOFError):
                print()
                break
        titulo(f"{n}/{len(seleccion)} · {s.historias} — {s.nombre}")
        inicio = time.monotonic()
        try:
            s.funcion(ctx)
        except KeyboardInterrupt:
            print()
            break
        except Exception as exc:  # una sección rota no detiene el resto de la demo
            fallidas.append(s.clave)
            print(f"\n  ✘ La sección falló: {type(exc).__name__}: {exc}")
        print(f"\n  ({time.monotonic() - inicio:.1f} s)")

    titulo("FIN DE LA DEMO")
    if fallidas:
        print(f"  Secciones con error: {', '.join(fallidas)}")
    print(f"  PDFs y copia de trabajo de la base en: {SALIDA}")
    print("  La base real (data/copiloto.db, patients/db/pacientes.db) no se modificó.")
    return 1 if fallidas else 0


if __name__ == "__main__":
    sys.exit(main())
