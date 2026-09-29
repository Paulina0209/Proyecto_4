"""Demo unificada del copiloto clínico: todo lo implementado, con un solo comando.

    python demo.py                  # todas las secciones, con pausa entre cada una
    python demo.py --sin-pausa      # de corrido (para grabar o revisar la salida)
    python demo.py --lista          # qué secciones hay
    python demo.py --solo tx ia     # solo algunas secciones
    python demo.py --sin-red        # sin OpenAI ni cBioPortal (respaldo por reglas)

Recorre el flujo de un paciente de principio a fin: acceso seguro, registro
y búsqueda, historia clínica (incluida la importación real desde
cBioPortal), asistente de IA, diagnóstico, estadificación, tratamiento,
evidencia, documentos, auditoría y privacidad.

Reutiliza las demos de cada historia (no duplica su lógica) y agrega
guiones fijos para las que eran interactivas (IA-01, TX). Todo corre en
bases SQLite en memoria o en una carpeta temporal: no modifica
``data/`` ni ``patients/db/``.

Las secciones con IA usan el modelo GPT configurado en el ``.env``
(``docs/llm_openai.md``); si no hay llave o no hay red, usan el cliente por
reglas y lo avisan.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

RAIZ = Path(__file__).resolve().parent
ANCHO = 78
SALIDA = Path(tempfile.gettempdir()) / "copiloto_demo"
SIN_RED = False


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


@contextlib.contextmanager
def silenciar_stderr():
    with contextlib.redirect_stderr(io.StringIO()):
        yield


def _modelo_ia() -> str:
    from core import llm_config

    if SIN_RED:
        return "desactivado (--sin-red): se usa el cliente por reglas"
    if not llm_config.obtener_api_key():
        return "sin OPENAI_API_KEY en el .env: se usa el cliente por reglas"
    return llm_config.obtener_modelo()


# ---------------------------------------------------------------------------
# 1. SEC-01 — Acceso seguro
# ---------------------------------------------------------------------------


def seccion_seguridad() -> None:
    from seguridad import demo

    demo.main()


# ---------------------------------------------------------------------------
# 2. PAC-01/02/03 — Pacientes (API HTTP real, en proceso)
# ---------------------------------------------------------------------------


def seccion_pacientes() -> None:
    from fastapi.testclient import TestClient

    import patients.api as api

    api.DB_PATH = str(SALIDA / "pacientes_demo.db")
    Path(api.DB_PATH).unlink(missing_ok=True)
    api.SEMBRAR_DATOS_PRUEBA = True
    nota("Se usa la API HTTP real (FastAPI) sobre una base temporal con datos de prueba.")

    with TestClient(api.app) as cliente:
        subtitulo("PAC-01 — Registro de un paciente nuevo")
        nuevo = {
            "nombre_completo": "Lucía Fernández",
            "fecha_nacimiento": "1979-08-21",
            "sexo": "femenino",
            "tipo_identificacion": "cedula",
            "numero_identificacion": "43210987",
            "contacto": {"telefono": "3104445566"},
            "oncologo_id": 1,
            "motivo_consulta_inicial": "Nódulo en mama izquierda",
        }
        r = cliente.post("/pacientes", json=nuevo)
        creado = r.json()
        print(f"POST /pacientes -> {r.status_code}: id {creado['id']}, {creado['nombre_completo']}, "
              f"registro completo: {creado['registro_completo']}")

        r = cliente.post("/pacientes", json=nuevo)
        print(f"Mismo documento otra vez -> {r.status_code}: {r.json()['detail']['mensaje']}")

        r = cliente.post("/pacientes", json={**nuevo, "numero_identificacion": "12ab", "nombre_completo": ""})
        print(f"Datos inválidos -> {r.status_code}:")
        for error in r.json()["detail"]["errores"]:
            print(f"  ✘ {error['campo']}: {error['mensaje']}")

        subtitulo("PAC-02 — Búsqueda y filtros")
        for filtros in (
            {"diagnostico": "mama"},
            {"nombre": "maria"},
            {"estado_tratamiento": "en_tratamiento", "diagnostico": "pulmon"},
            {"nombre": "zzz"},
        ):
            res = cliente.get("/pacientes/buscar", params={"oncologo_id": 1, **filtros}).json()
            chips = " · ".join(f"{k}={v}" for k, v in filtros.items())
            print(f"\n  Filtros: {chips} -> {res['total']} resultado(s)")
            if res["total"] == 0:
                print(f"  ⓘ {res['mensaje']}")
            for p in res["items"][:4]:
                print(f"   · [{p['id']}] {p['nombre_completo']:<24} {', '.join(p['diagnosticos']) or '—'}"
                      f" | {p['estado_tratamiento'] or '—'} | última consulta {p['fecha_ultima_consulta'] or '—'}")

        subtitulo("PAC-03 — Dashboard 360 del paciente 1")
        r360 = cliente.get("/pacientes/1/resumen-360", params={"oncologo_id": 1}).json()
        print(f"  {r360['nombre']} — {r360['diagnostico_principal']} (estadio {r360['estadio']})")
        tx = r360["tratamiento_mas_reciente"]
        if tx:
            print(f"  Tratamiento más reciente: {tx['regimen']} ({tx['estado']}, desde {tx['fecha_inicio']})")
        print("  Alertas activas:")
        for a in r360["alertas_activas"]:
            print(f"   ! [{a['severidad']}] {a['descripcion']}")
        for etiqueta, clave in (("Laboratorios", "labs_recientes"), ("Imágenes", "imagenes_recientes"),
                                ("Notas", "notas_recientes")):
            for item in r360[clave][:2]:
                print(f"   {etiqueta}: {item['fecha']} — {item.get('titulo') or ''} {item['resumen']}".rstrip())
        if r360["informacion_incompleta"]:
            print(f"  Campos faltantes: {', '.join(r360['campos_faltantes'])}")

        r = cliente.get("/pacientes/1", params={"oncologo_id": 2})
        print(f"\n  Otro oncólogo pide este paciente -> {r.status_code} (solo ve sus propios pacientes)")


# ---------------------------------------------------------------------------
# 3. HC-01 / HC-05 / DOC-01 — Historia clínica
# ---------------------------------------------------------------------------

_BUNDLE_FHIR = {
    "resourceType": "Bundle",
    "type": "searchset",
    "entry": [
        {"resource": {"resourceType": "Patient", "id": "p1", "identifier": [{"value": "EXT-DEMO-1"}]}},
        {"resource": {
            "resourceType": "Observation", "id": "lab-1",
            "category": [{"coding": [{"code": "laboratory"}]}],
            "code": {"text": "Hemoglobina"}, "effectiveDateTime": "2026-09-03",
            "valueQuantity": {"value": 10.2, "unit": "g/dL"},
            "referenceRange": [{"low": {"value": 12.0}, "high": {"value": 16.0}}],
        }},
        {"resource": {
            "resourceType": "DiagnosticReport", "id": "rx-1",
            "category": [{"coding": [{"code": "RAD"}]}], "code": {"text": "Mamografía mama izquierda"},
            "effectiveDateTime": "2026-08-20", "conclusion": "Lesión espiculada de 2 cm en mama izquierda. BI-RADS 5.",
        }},
        {"resource": {"resourceType": "Condition", "id": "c-1", "code": {"text": "Hipertensión arterial"},
                      "onsetDateTime": "2015-06-01"}},
        {"resource": {"resourceType": "Encounter", "id": "e-1"}},
    ],
}


def seccion_historia_clinica() -> None:
    from historia_clinica.db import crear_conexion
    from historia_clinica.informacion_faltante import evaluar_informacion_faltante
    from historia_clinica.integracion_externa import (
        antecedentes_externos_de_paciente,
        importar_bundle_fhir,
        listar_sincronizaciones,
    )
    from historia_clinica_mock.repository import imagenologia_de_paciente, laboratorios_de_paciente

    conn = crear_conexion(":memory:")
    cur = conn.execute(
        "INSERT INTO pacientes (nombre, fecha_nacimiento, sexo, identificacion) VALUES (?, ?, ?, ?)",
        ("Lucía Fernández (sintética)", "1979-08-21", "femenino", "EXT-DEMO-1"),
    )
    paciente_id = cur.lastrowid
    conn.commit()

    subtitulo("HC-01 — Importar la historia desde otro hospital (FHIR)")
    r = importar_bundle_fhir(conn, paciente_id, _BUNDLE_FHIR, fuente="HIS Hospital de origen")
    print(f"  {r.mensaje}")
    for lab in laboratorios_de_paciente(conn, paciente_id):
        print(f"   Laboratorio: {lab.fecha} {lab.prueba} = {lab.valor} {lab.unidad or ''} "
              f"{'(alterado)' if lab.alterado else ''}".rstrip())
    for img in imagenologia_de_paciente(conn, paciente_id):
        print(f"   Imagen: {img.fecha} {img.modalidad} — {img.hallazgos}")
    for ant in antecedentes_externos_de_paciente(conn, paciente_id):
        print(f"   Antecedente: {ant.descripcion}")

    otro = dict(_BUNDLE_FHIR, entry=[{"resource": {"resourceType": "Patient", "id": "x",
                                                   "identifier": [{"value": "OTRA-PERSONA"}]}}])
    r = importar_bundle_fhir(conn, paciente_id, otro, fuente="HIS Hospital de origen")
    print(f"\n  Mensaje de OTRO paciente -> importado: {r.exito}. {r.mensaje}")
    print("  Sincronizaciones registradas:")
    for s in listar_sincronizaciones(conn, paciente_id):
        print(f"   · {s.fuente} [{s.formato}] {s.estado}: {s.registros_importados} importados, "
              f"{s.registros_omitidos} omitidos")

    subtitulo("HC-05 — ¿Qué información falta para decidir?")
    ev = evaluar_informacion_faltante(conn, paciente_id, tipo_cancer="cáncer de mama", fases=["diagnostico"])
    print(f"  Estado: {ev.estado.value}")
    for item in ev.faltantes:
        print(f"   ✘ {item.descripcion} — {item.motivo}")
    for item_id, fuente in ev.presentes:
        print(f"   ✔ {item_id} (respaldo: {fuente})")
    conn.close()

    subtitulo("DOC-01 — Carga de documentos clínicos")
    from documentos_clinicos import demo_carga_documentos

    demo_carga_documentos._DIRECTORIO_ALMACENAMIENTO = str(SALIDA / "documentos")
    demo_carga_documentos.main()


# ---------------------------------------------------------------------------
# 4. Base de datos real — cBioPortal
# ---------------------------------------------------------------------------


def seccion_cbioportal() -> None:
    if SIN_RED:
        nota("Omitida con --sin-red (necesita internet para consultar cBioPortal).")
        return

    from cbioportal import FuenteCBioPortal, importar_paciente
    from historia_clinica.db import crear_conexion
    from historia_clinica.informacion_faltante import evaluar_informacion_faltante
    from historia_clinica_mock.adapters import obtener_hallazgos_de_paciente
    from historia_clinica_mock.repository import biomarcadores_de_paciente

    conn = crear_conexion(":memory:")
    fuente = FuenteCBioPortal(fecha_referencia=date.today())
    print("  Trayendo un paciente real (desidentificado) de MSK-CHORD por la API pública de cBioPortal...")
    inicio = time.monotonic()
    r = importar_paciente(conn, fuente, "msk_chord_2024", "P-0000015")
    if not r.sincronizacion.exito:
        nota(f"No se pudo consultar cBioPortal: {r.sincronizacion.mensaje}")
        return
    print(f"  {r.identificacion} en {time.monotonic() - inicio:.1f} s — {r.sincronizacion.mensaje}")

    fila = conn.execute("SELECT diagnostico_principal, estadio, sexo FROM pacientes WHERE id = ?",
                        (r.paciente_id,)).fetchone()
    print(f"  Diagnóstico: {fila[0]} | estadio: {fila[1] or 'no registrado'} | sexo: {fila[2]}")
    print("  Biomarcadores:")
    for b in biomarcadores_de_paciente(conn, r.paciente_id)[:8]:
        print(f"   · {b.fecha} {b.biomarcador}: {b.resultado}")
    hallazgos = obtener_hallazgos_de_paciente(conn, r.paciente_id)
    print(f"  Hallazgos en el expediente: {len(hallazgos)} (laboratorios, imágenes, eventos, tratamientos)")

    ev = evaluar_informacion_faltante(conn, r.paciente_id)
    print(f"\n  HC-05 sobre el paciente real: {ev.estado.value}")
    for item in ev.faltantes[:6]:
        print(f"   ✘ {item.descripcion} — {item.motivo}")
    nota("Las variables que requieren juicio clínico (T/N/M, etc.) no se derivan: quedan como faltantes.")
    conn.close()


# ---------------------------------------------------------------------------
# 5. IA-01 … IA-06 — Asistente de IA
# ---------------------------------------------------------------------------


def seccion_ia() -> None:
    import demo_ia01
    from clinical_query import MockSQLiteClinicalRepository, NaturalLanguageClinicalQueryService
    from historia_clinica_mock.db import crear_conexion
    from historia_clinica_mock.repository import obtener_paciente
    from historia_clinica_mock.seed import sembrar_datos_sinteticos
    from ia_clinica.explainability import PatientRecommendationService

    print(f"  Modelo de lenguaje: {_modelo_ia()}")
    conn = crear_conexion()
    ids = sembrar_datos_sinteticos(conn)
    servicio = NaturalLanguageClinicalQueryService(MockSQLiteClinicalRepository(conn))

    subtitulo("IA-01 / IA-06 — Preguntas en lenguaje natural sobre el paciente")
    for paciente_id, pregunta in (
        (ids["paciente_maria"], "¿Cuál es el HER2 más reciente?"),
        (ids["paciente_carlos"], "¿Cuál es el EGFR más reciente?"),
        (ids["paciente_maria"], "¿Cuál es el EGFR?"),
        (ids["paciente_maria"], "¿Cuál es el EGFR de Carlos?"),
        (ids["paciente_diana"], "¿Cuál es la hemoglobina?"),
        (ids["paciente_diana"], "¿Cuál es la última hemoglobina?"),
    ):
        paciente = obtener_paciente(conn, paciente_id)
        print(f"\n  Oncólogo ({paciente.nombre}) > {pregunta}")
        respuesta = servicio.ask(str(paciente_id), pregunta)
        print(f"  Asistente > {respuesta.answer}")
        if respuesta.needs_clarification:
            nota("La pregunta es ambigua: el asistente pide aclaración en vez de adivinar (IA-06).")
        elif respuesta.datum is not None:
            print(f"    fuente: {respuesta.datum.source} #{respuesta.datum.source_id}, "
                  f"{respuesta.datum.observed_at:%Y-%m-%d}")

    subtitulo("IA-05 — Recomendaciones explicables")
    demo_ia01.mostrar_recomendaciones(conn, obtener_paciente(conn, ids["paciente_maria"]),
                                      PatientRecommendationService())
    conn.close()

    subtitulo("IA-02 + IA-03 — Nota clínica generada por IA, revisión y aprobación")
    _con_modelo(lambda: __import__("ia_clinica.review.demo", fromlist=["main"]).main())

    subtitulo("IA-04 — Resumen del caso para junta médica")
    _con_modelo(lambda: __import__("ia_clinica.summary.demo", fromlist=["main"]).main())


def _con_modelo(funcion: Callable[[], None]) -> None:
    """Corre una demo de IA; con --sin-red, oculta la llave para forzar el respaldo."""
    if not SIN_RED:
        funcion()
        return
    guardadas = {k: os.environ.pop(k) for k in ("OPENAI_API_KEY", "API_KEY") if k in os.environ}
    from core import llm_config

    original = llm_config.obtener_api_key
    llm_config.obtener_api_key = lambda: None
    try:
        funcion()
    finally:
        llm_config.obtener_api_key = original
        os.environ.update(guardadas)


# ---------------------------------------------------------------------------
# 6. DX-01/02/03 — Diagnóstico
# ---------------------------------------------------------------------------


def seccion_diagnostico() -> None:
    from dx_clinica import demo, demo_estudios, demo_incertidumbre

    subtitulo("DX-01 — Estudios recomendados según la sospecha")
    demo_estudios.main()
    subtitulo("DX-02 — Diagnóstico diferencial")
    demo.main()
    subtitulo("DX-03 — Incertidumbre diagnóstica y juicio clínico")
    demo_incertidumbre.main()


# ---------------------------------------------------------------------------
# 7. EST-01/02/03 — Estadificación
# ---------------------------------------------------------------------------


def seccion_estadificacion() -> None:
    from estadificacion import demo

    demo.main()


# ---------------------------------------------------------------------------
# 8. TX-01 … TX-04 — Tratamiento
# ---------------------------------------------------------------------------


def seccion_tratamiento() -> None:
    from tx_clinica.tools._db import conn_lock, obtener_conexion
    from tx_clinica.tools.interaction_tools import chequear_interacciones_tratamiento, consultar_medicacion_actual
    from tx_clinica.tools.recommendation_tools import obtener_recomendaciones_tratamiento_por_id

    conn = obtener_conexion()
    with conn_lock:
        if conn.execute("SELECT 1 FROM pacientes WHERE id = 10").fetchone() is None:
            conn.executescript((RAIZ / "patients" / "paciente_de_prueba.sql").read_text(encoding="utf-8"))
            conn.commit()
    print("  Paciente: Diana (id 10), NSCLC metastásico no oncogénico, PD-L1 75 %, ECOG 1.")

    subtitulo("TX-01 + TX-02 — Opciones según la guía, con nivel de evidencia")
    rec = json.loads(obtener_recomendaciones_tratamiento_por_id.invoke({"patient_id": 10}))
    print(f"  Módulo de guía aplicado: {rec.get('module_id')}")
    for i, c in enumerate(rec.get("candidatos", []), 1):
        fase = f" ({c['fase']})" if c["fase"] else ""
        print(f"\n  {i}. {c['regimen_id']}{fase}: {' + '.join(c['farmacos'])}")
        print(f"     regla: {c['rule_id_disparada']}")
        print(f"     evidencia: {' '.join(c['evidencia'].split())}")
        if c["advertencia_comorbilidad"]:
            print(f"     ⚠ {c['advertencia_comorbilidad']}")

    subtitulo("TX-03 — Interacciones con la medicación actual")
    med = json.loads(consultar_medicacion_actual.invoke({"patient_id": 10}))
    print(f"  Medicación activa: {', '.join(med['medicacion_activa'])}")
    regimen = rec["candidatos"][0]["regimen_id"]
    chequeo = json.loads(chequear_interacciones_tratamiento.invoke({"patient_id": 10, "regimen_id": regimen}))
    print(f"  Régimen evaluado: {regimen}")
    for i in chequeo.get("interacciones", []):
        print(f"   ! [{i['severidad']}] {i['medicamento_concomitante']}: {i['descripcion'].strip()}")
        print(f"     recomendación: {i['recomendacion']}")
    if chequeo.get("advertencia_cobertura_incompleta"):
        nota("Cobertura incompleta del catálogo de interacciones: se avisa en vez de afirmar 'sin interacciones'.")

    subtitulo("TX-03 — Motor de interacciones y contraindicaciones (casos de prueba)")
    from interacciones_farmacologicas import demo_checker

    demo_checker.main()

    subtitulo("Agente conversacional de tratamiento (GPT + herramientas + aprobación humana)")
    _agente_tratamiento()


def _agente_tratamiento() -> None:
    from core import llm_config

    if SIN_RED or not llm_config.obtener_api_key():
        nota(f"Omitido: {_modelo_ia()}.")
        return
    if not os.environ.get("LANGFUSE_PUBLIC_KEY"):
        os.environ.setdefault("LANGFUSE_TRACING_ENABLED", "false")

    from tx_clinica.agent import construir_agente
    from tx_clinica.conversacion import enviar_mensaje

    pregunta = "¿Qué opciones de tratamiento de primera línea tiene la paciente 10 y hay alguna interacción con su medicación?"
    print(f"  Modelo: {llm_config.obtener_modelo()}")
    print(f"  Oncólogo > {pregunta}")
    with silenciar_stderr():
        agente = construir_agente()
        respuesta = enviar_mensaje(agente, pregunta, f"demo-unificada-{datetime.now():%H%M%S}", 1)
    herramientas = [tc["name"] for m in respuesta.mensajes for tc in (getattr(m, "tool_calls", None) or [])]
    print(f"  (herramientas usadas: {', '.join(dict.fromkeys(herramientas)) or 'ninguna'})")
    print(f"  Agente > {respuesta.mensajes[-1].text}")
    nota("Si el agente intenta registrar la decisión (TX-04), la ejecución se pausa hasta que el médico apruebe.")


# ---------------------------------------------------------------------------
# 9. EV-01 / CFG-01 — Evidencia y guías institucionales
# ---------------------------------------------------------------------------


def seccion_evidencia() -> None:
    import demo_ia01
    from configuracion.guias_institucionales import (
        ProtocoloInterno,
        buscar_evidencia_institucional,
        configurar_guias,
        crear_conexion,
        obtener_configuracion_vigente,
    )
    from evidencia_clinica import EvidenceSearchService
    from historia_clinica_mock.db import crear_conexion as crear_conexion_mock
    from historia_clinica_mock.repository import obtener_paciente
    from historia_clinica_mock.seed import sembrar_datos_sinteticos
    from seguridad.models import Rol, Usuario

    subtitulo("EV-01 — Evidencia para el paciente activo (Carlos, NSCLC)")
    conn = crear_conexion_mock()
    ids = sembrar_datos_sinteticos(conn)
    servicio = EvidenceSearchService()
    demo_ia01.mostrar_evidencia(conn, obtener_paciente(conn, ids["paciente_carlos"]), servicio)
    subtitulo("EV-01 — Búsqueda libre sin coincidencias")
    demo_ia01.mostrar_evidencia(conn, obtener_paciente(conn, ids["paciente_carlos"]), servicio, "glioblastoma pediátrico")
    conn.close()

    subtitulo("CFG-01 — Guías clínicas institucionales")
    cfg = crear_conexion()
    vigente = obtener_configuracion_vigente(cfg)
    print(f"  Sin configurar: {', '.join(vigente.organizaciones)} (por defecto del sistema), "
          f"{len(vigente.modulos_habilitados)} módulos habilitados")
    admin = Usuario(id=1, nombre_usuario="adm.clinico", rol=Rol.ADMINISTRADOR_CLINICO, activo=True)
    r = configurar_guias(cfg, admin, ["NCCN", "ESMO"], "Acta del comité de oncología 2026-09",
                         protocolo_interno=ProtocoloInterno("Protocolo de mama v3", "DOC-ONC-017"))
    vigente = obtener_configuracion_vigente(cfg)
    print(f"  El administrador clínico configura NCCN > ESMO -> versión {vigente.version}, "
          f"protocolo: {vigente.protocolo_interno.nombre if vigente.protocolo_interno else '—'}")
    for adv in r.advertencias:
        print(f"   ⚠ {adv}")
    oncologa = Usuario(id=2, nombre_usuario="dra.gomez", rol=Rol.ONCOLOGO, activo=True)
    r = configurar_guias(cfg, oncologa, ["ESMO"], "Prefiero ESMO")
    print(f"  Una oncóloga intenta cambiarla -> aceptado: {r.exito}. {r.motivo_rechazo or ''}".rstrip())
    resultados = buscar_evidencia_institucional(cfg, "cáncer de mama triple negativo")
    print(f"  Evidencia filtrada por la configuración institucional: {len(resultados)} resultado(s)")
    for res in resultados[:3]:
        print(f"   · {res.document.organization} — {res.document.title.strip()}")
    cfg.close()


# ---------------------------------------------------------------------------
# 10. DOC-02 — Exportación a PDF
# ---------------------------------------------------------------------------


def seccion_documentos() -> None:
    from documentos_clinicos import demo_exportacion

    demo_exportacion._DIRECTORIO_SALIDA = str(SALIDA / "pdf")
    demo_exportacion.main()


# ---------------------------------------------------------------------------
# 11. AUD-01/02 — Auditoría
# ---------------------------------------------------------------------------


def seccion_auditoria() -> None:
    from auditoria import demo

    demo.main()


# ---------------------------------------------------------------------------
# 12. NFR-06 — Datos personales
# ---------------------------------------------------------------------------


def seccion_privacidad() -> None:
    from privacidad.models import EstadoAutorizacion, Finalidad
    from privacidad.tratamiento_datos import (
        configurar_politica,
        crear_conexion,
        registrar_autorizacion,
        verificar_tratamiento_permitido,
    )

    conn = crear_conexion()
    ahora = datetime.now(timezone.utc)
    configurar_politica(
        conn, 1,
        codigo="co-pacientes", jurisdiccion="Colombia",
        nombre="Política de tratamiento de datos de pacientes",
        marco_normativo="Referencia definida por la institución",
        finalidades=(
            Finalidad("atencion_clinica", "Prestación del servicio de salud", False),
            Finalidad("investigacion", "Uso de datos seudonimizados en investigación", True),
        ),
        bases_legales=("autorizacion_titular", "prestacion_servicio_salud"),
        derechos=("acceso", "rectificacion", "supresion", "revocacion"),
        plazo_respuesta_dias=15, ahora=ahora,
    )
    print("  Política 'co-pacientes' (Colombia): atención clínica sin autorización, investigación con autorización.")

    def consultar(momento: str, finalidad: str = "investigacion") -> None:
        d = verificar_tratamiento_permitido(conn, 1, "co-pacientes", finalidad)
        print(f"   {momento:<30} -> {'permitido' if d.permitido else 'NO permitido'}: {d.motivo}")

    consultar("Atención clínica:", "atencion_clinica")
    consultar("Investigación, sin autorización:")
    registrar_autorizacion(conn, 2, paciente_id=1, codigo_politica="co-pacientes", finalidad="investigacion",
                           base_legal="autorizacion_titular", medio="escrito", evidencia_ref="documento-42")
    consultar("Investigación, autorizada:")
    registrar_autorizacion(conn, 2, paciente_id=1, codigo_politica="co-pacientes", finalidad="investigacion",
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
    funcion: Callable[[], None]


SECCIONES: List[Seccion] = [
    Seccion("sec", "SEC-01", "Autenticación y control de acceso por rol", seccion_seguridad),
    Seccion("pac", "PAC-01 · PAC-02 · PAC-03", "Registro, búsqueda y dashboard 360 de pacientes", seccion_pacientes),
    Seccion("hc", "HC-01 · HC-05 · DOC-01", "Historia clínica: integración externa, información faltante y documentos",
            seccion_historia_clinica),
    Seccion("cbio", "HC-01 + cBioPortal", "Base de datos real: paciente de MSK-CHORD", seccion_cbioportal),
    Seccion("ia", "IA-01 … IA-06", "Asistente de IA: preguntas, explicabilidad, notas y resumen", seccion_ia),
    Seccion("dx", "DX-01 · DX-02 · DX-03", "Diagnóstico", seccion_diagnostico),
    Seccion("est", "EST-01 · EST-02 · EST-03", "Estadificación", seccion_estadificacion),
    Seccion("tx", "TX-01 … TX-04", "Tratamiento: recomendación, evidencia, interacciones y agente", seccion_tratamiento),
    Seccion("ev", "EV-01 · CFG-01", "Evidencia científica y guías institucionales", seccion_evidencia),
    Seccion("doc", "DOC-02", "Exportación del expediente y del resumen a PDF", seccion_documentos),
    Seccion("aud", "AUD-01 · AUD-02", "Auditoría de accesos y trazabilidad de la IA", seccion_auditoria),
    Seccion("priv", "NFR-06", "Datos personales: autorizaciones por finalidad", seccion_privacidad),
]


def _argumentos(argv) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python demo.py", description="Demo unificada del copiloto clínico.")
    p.add_argument("--solo", nargs="+", metavar="SECCION", choices=[s.clave for s in SECCIONES],
                   help="Correr solo estas secciones (ver --lista).")
    p.add_argument("--sin-pausa", action="store_true", help="No esperar Enter entre secciones.")
    p.add_argument("--sin-red", action="store_true", help="No usar OpenAI ni cBioPortal.")
    p.add_argument("--lista", action="store_true", help="Mostrar las secciones y salir.")
    return p.parse_args(argv)


def main(argv=None) -> int:
    global SIN_RED
    for flujo in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError):
            flujo.reconfigure(encoding="utf-8")
    sys.path.insert(0, str(RAIZ))
    os.chdir(RAIZ)

    args = _argumentos(argv)
    if args.lista:
        for s in SECCIONES:
            print(f"  {s.clave:<5} {s.historias:<26} {s.nombre}")
        return 0

    SIN_RED = args.sin_red
    SALIDA.mkdir(parents=True, exist_ok=True)
    seleccion = [s for s in SECCIONES if not args.solo or s.clave in args.solo]
    pausar = not args.sin_pausa and sys.stdin.isatty()

    titulo("COPILOTO CLÍNICO PARA ONCOLOGÍA — DEMO UNIFICADA")
    print("  Datos sintéticos (historia_clinica_mock) y reales desidentificados (cBioPortal).")
    print(f"  Modelo de lenguaje: {_modelo_ia()}")
    print(f"  Archivos generados: {SALIDA}")
    print(f"  Secciones: {', '.join(s.clave for s in seleccion)}")

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
            s.funcion()
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
    print(f"  PDFs y documentos generados en: {SALIDA}")
    return 1 if fallidas else 0


if __name__ == "__main__":
    sys.exit(main())
