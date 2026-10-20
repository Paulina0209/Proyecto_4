"""El asistente conversacional: grafo de LangGraph, base vectorial, control de alucinaciones e historial.

Sin red: ChromaDB en memoria con embeddings deterministas (bolsa de palabras con
hash), y sin modelo de lenguaje salvo donde se simula uno.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3

import pytest

from asistente import MENSAJE_SIN_INFORMACION, grafo as g, llm
from asistente.fragmentos import Fragmento, fragmentos_de_guias, fragmentos_del_expediente, trocear
from asistente.indice import IndiceVectorial
from asistente.intencion import detectar_intencion, mencion_de_paciente
from historia_clinica.db import crear_conexion
from privacidad.consentimiento_ia import activar_consentimiento_ia, registrar_consentimiento_ia, retirar_consentimiento_ia
from tests.datos_sinteticos import sembrar_datos_sinteticos

DIM = 256


def embeddings_falsos(textos):
    """Bolsa de palabras con hash, normalizada: textos con palabras en común son similares."""
    vectores = []
    for t in textos:
        v = [0.0] * DIM
        for palabra in re.findall(r"\w+", t.casefold()):
            if len(palabra) > 2:
                v[int(hashlib.md5(palabra.encode()).hexdigest(), 16) % DIM] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        vectores.append([x / n for x in v])
    return vectores


@pytest.fixture()
def indice(tmp_path):
    import chromadb

    return IndiceVectorial(cliente=chromadb.PersistentClient(path=str(tmp_path / "vec")), embeddings=embeddings_falsos)


@pytest.fixture()
def expediente():
    conn = crear_conexion()
    ids = sembrar_datos_sinteticos(conn)
    activar_consentimiento_ia(conn, 1)
    registrar_consentimiento_ia(conn, 1, ids["paciente_maria"], medio="escrito", soporte="doc")
    return conn, ids


@pytest.fixture(autouse=True)
def sin_modelo(monkeypatch):
    monkeypatch.setattr(llm, "disponible", lambda: False)


def deps(conn, ids, indice, guardados=None):
    pid = ids["paciente_maria"]
    return g.Dependencias(
        usuario_id=2, conn_exp=conn, indice=indice,
        buscar_pacientes=lambda texto: [(pid, "María Fernanda Ríos", "SINT-0001")] if "maria" in texto.lower() or "sint" in texto.lower() else [],
        expediente_de=lambda p: (pid, "María Fernanda Ríos") if p == pid else (None, "otro"),
        guardar=(guardados.append if guardados is not None else None))


# --- Intención y paciente --------------------------------------------------------------


@pytest.mark.parametrize("pregunta,intencion", [
    ("¿Cuál es el CEA más reciente?", "dato"), ("Resúmeme el caso", "resumen"), ("¿Qué diagnóstico diferencial sugieres?", "diagnostico"),
    ("¿En qué estadio está?", "estadificacion"), ("¿Qué opciones de tratamiento tiene?", "tratamiento"),
    ("¿Qué falta para decidir?", "faltantes"), ("¿Qué dice la guía ESMO?", "evidencia"), ("hola", "saludo"),
])
def test_intencion(pregunta, intencion):
    assert detectar_intencion(pregunta) == intencion


def test_mencion_de_paciente():
    assert mencion_de_paciente("¿Cuál es el CEA de P-0008538?").texto == "P-0008538"
    assert mencion_de_paciente("¿y la paciente María Ríos?").texto == "maria rios"
    assert mencion_de_paciente("¿cuál es el valor de hemoglobina?").texto is None


# --- Fragmentos e índice -----------------------------------------------------------------


def test_trocear_con_solape():
    texto = " ".join(f"palabra{i}" for i in range(400))
    trozos = trocear(texto, tamano=300, solape=50)
    assert len(trozos) > 3 and all(len(t) <= 300 for t in trozos)
    assert trozos[0].split()[-1] in trozos[1]  # el solape conserva el contexto entre trozos


def test_fragmentos_del_expediente_usan_los_ids_del_sistema_y_salen_seudonimizados(expediente):
    conn, ids = expediente
    conn.execute("INSERT INTO consultas (paciente_id, fecha, motivo, notas_libres) VALUES (?, '2026-02-01', 'x', ?)",
                 (ids["paciente_maria"], "María Fernanda refiere dolor. Teléfono 3001234567."))
    frags = fragmentos_del_expediente(conn, ids["paciente_maria"])
    prefijos = {f.id.split("-")[0] for f in frags}
    assert {"consulta", "lab", "imagen", "biomarcador"} <= prefijos
    assert not any("María" in f.texto or "3001234567" in f.texto for f in frags)


def test_sin_consentimiento_no_hay_fragmentos(expediente):
    from privacidad.consentimiento_ia import ConsentimientoIARequerido

    conn, ids = expediente
    otro = conn.execute("SELECT id FROM pacientes WHERE id != ?", (ids["paciente_maria"],)).fetchone()[0]
    with pytest.raises(ConsentimientoIARequerido):
        fragmentos_del_expediente(conn, otro)


def test_indice_filtra_por_paciente_y_se_actualiza_por_huella(indice):
    a = [Fragmento("lab-1", "Hemoglobina 11 g/dL", "expediente", "laboratorio", 1)]
    b = [Fragmento("lab-9", "Hemoglobina 13 g/dL", "expediente", "laboratorio", 2)]
    assert indice.sincronizar_paciente(1, a) == 1 and indice.sincronizar_paciente(2, b) == 1
    assert indice.sincronizar_paciente(1, a) == 0                      # misma huella: no recalcula
    assert [r.id for r in indice.buscar("hemoglobina", paciente_id=1)] == ["lab-1"]
    indice.sincronizar_paciente(1, a + [Fragmento("lab-2", "CEA 3 ng/ml", "expediente", "laboratorio", 1)])
    assert indice.cuantos(1) == 2
    indice.olvidar_paciente(1)
    assert indice.cuantos(1) == 0 and indice.cuantos(2) == 1


def test_guias_indexadas_con_su_fuente(indice):
    frags = fragmentos_de_guias()
    assert frags and all(f.id.startswith("guia-") and f.metadatos.get("modulo") and f.metadatos.get("archivo") for f in frags)
    assert indice.asegurar_guias() == len(frags) and indice.asegurar_guias() == 0
    assert indice.buscar("pembrolizumab", tipo="guia", k=3)


# --- Grafo -----------------------------------------------------------------------------------


def nodos(estado):
    return [p["nodo"] for p in estado["pasos"]]


def test_dato_exacto_con_su_fuente(expediente, indice):
    conn, ids = expediente
    r = g.ejecutar("¿Cuál es el HER2?", deps(conn, ids, indice), paciente_activo=ids["paciente_maria"])
    assert r["estado"] == "respondida" and "negativo" in r["respuesta"].lower()
    assert [f["id"] for f in r["fuentes"]][0].startswith("biomarcador-")
    assert nodos(r)[:4] == ["validar_intencion", "resolver_paciente", "recuperar", "recuperar"] and "evaluar_contexto" in nodos(r)


def test_fuera_de_la_base_se_rechaza_explicitamente(expediente, indice, monkeypatch):
    conn, ids = expediente
    monkeypatch.setenv("COPILOTO_UMBRAL_SIMILITUD", "0.6")
    r = g.ejecutar("¿Cuál es la capital de Francia?", deps(conn, ids, indice), paciente_activo=ids["paciente_maria"])
    assert r["estado"] == "rechazada" and r["respuesta"].startswith(MENSAJE_SIN_INFORMACION)
    assert "rechazar" in nodos(r) and "responder" not in nodos(r) and not r["fuentes"]


def test_sin_paciente_pide_aclaracion(expediente, indice):
    conn, ids = expediente
    r = g.ejecutar("¿Cuál es el CEA?", deps(conn, ids, indice))
    assert r["estado"] == "aclaracion" and "recuperar" not in nodos(r)


def test_paciente_nombrado_en_la_pregunta(expediente, indice):
    conn, ids = expediente
    r = g.ejecutar("¿Cuál es el HER2 de la paciente María?", deps(conn, ids, indice))
    assert r["paciente"]["expediente_id"] == ids["paciente_maria"] and r["estado"] == "respondida"


def test_sin_consentimiento_no_consulta_nada_y_saca_al_paciente_del_indice(expediente, indice):
    conn, ids = expediente
    pid = ids["paciente_maria"]
    g.ejecutar("¿Cuál es el HER2?", deps(conn, ids, indice), paciente_activo=pid)
    assert indice.cuantos(pid) > 0
    retirar_consentimiento_ia(conn, 1, pid)
    r = g.ejecutar("¿Cuál es el HER2?", deps(conn, ids, indice), paciente_activo=pid)
    assert r["estado"] == "rechazada" and "consentimiento" in r["respuesta"] and "recuperar" not in nodos(r)
    assert indice.cuantos(pid) == 0


def test_diagnostico_con_sustento_trazable(expediente, indice):
    conn, ids = expediente
    r = g.ejecutar("¿Qué diagnóstico diferencial sugieres?", deps(conn, ids, indice), paciente_activo=ids["paciente_maria"])
    assert r["estado"] in ("respondida", "rechazada")
    if r["estado"] == "respondida":
        assert "apoyo" in r["respuesta"].lower() or "no sustenta" in r["respuesta"].lower() or r["fuentes"]


def test_estadificacion_y_faltantes(expediente, indice):
    conn, ids = expediente
    e = g.ejecutar("¿En qué estadio está?", deps(conn, ids, indice), paciente_activo=ids["paciente_maria"])
    f = g.ejecutar("¿Qué falta para decidir?", deps(conn, ids, indice), paciente_activo=ids["paciente_maria"])
    assert e["estado"] == "respondida" and ("estadio" in e["respuesta"].lower())
    assert f["estado"] == "respondida" and "falta" in f["respuesta"].lower()


def test_el_modelo_que_inventa_citas_se_descarta(expediente, indice, monkeypatch):
    conn, ids = expediente
    monkeypatch.setattr(llm, "disponible", lambda: True)
    monkeypatch.setattr(llm, "descripcion", lambda: "modelo de prueba")
    monkeypatch.setattr(llm, "redactar", lambda s, u, timeout=None: "El HER2 es positivo 3+ [lab-999].")
    r = g.ejecutar("¿Cuál es el HER2?", deps(conn, ids, indice), paciente_activo=ids["paciente_maria"])
    assert "lab-999" not in r["respuesta"] and "positivo 3+" not in r["respuesta"]   # se responde con lo verificado
    assert any(p["titulo"] == "Descarté el texto del modelo" for p in r["pasos"])


def test_el_modelo_con_citas_validas_se_usa(expediente, indice, monkeypatch):
    conn, ids = expediente
    monkeypatch.setattr(llm, "disponible", lambda: True)
    monkeypatch.setattr(llm, "descripcion", lambda: "modelo de prueba")

    def redactar(sistema, usuario, timeout=None):
        assert "Usa SOLO la información del CONTEXTO" in sistema
        fid = re.search(r"\[(biomarcador-\d+)\]", usuario).group(1)
        return f"HER2 negativo [{fid}]."

    monkeypatch.setattr(llm, "redactar", redactar)
    r = g.ejecutar("¿Cuál es el HER2?", deps(conn, ids, indice), paciente_activo=ids["paciente_maria"])
    assert r["modelo"] == "modelo de prueba" and r["respuesta"].startswith("HER2 negativo [biomarcador-")


def test_modelo_caido_responde_con_lo_encontrado(expediente, indice, monkeypatch):
    conn, ids = expediente
    monkeypatch.setattr(llm, "disponible", lambda: True)

    def caido(*a, **k):
        raise llm.ModeloNoDisponible("sin red")

    monkeypatch.setattr(llm, "redactar", caido)
    r = g.ejecutar("¿Cuál es el HER2?", deps(conn, ids, indice), paciente_activo=ids["paciente_maria"])
    assert r["estado"] == "respondida" and r["fuentes"]


def test_evidencia_de_guias_sin_paciente(expediente, indice):
    conn, ids = expediente
    r = g.ejecutar("¿Qué dice la guía ESMO sobre pembrolizumab?", deps(conn, ids, indice))
    assert r["paciente"] is None and r["estado"] == "respondida" and all(f["id"].startswith("guia-") for f in r["fuentes"])


def test_se_guarda_el_historial(expediente, indice):
    conn, ids = expediente
    guardados = []
    g.ejecutar("¿Cuál es el HER2?", deps(conn, ids, indice, guardados), paciente_activo=ids["paciente_maria"])
    assert len(guardados) == 1 and guardados[0]["respuesta"] and guardados[0]["intencion"] == "dato"


def test_el_indice_mide_con_coseno_aunque_se_abra_con_autorreparacion(tmp_path):
    from asistente.indice import _abrir_o_reconstruir, _espacio

    idx = IndiceVectorial(cliente=_abrir_o_reconstruir(tmp_path / "vec"), embeddings=embeddings_falsos)
    assert _espacio(idx._coleccion) == "cosine"
    idx.sincronizar_paciente(1, [Fragmento("lab-1", "Hemoglobina 11 g/dL", "expediente", "laboratorio", 1)])
    assert idx.buscar("Hemoglobina 11 g/dL", paciente_id=1)[0].similitud == pytest.approx(1.0, abs=1e-3)


def test_si_chroma_aun_no_escribio_el_segmento_se_busca_contra_todos(indice, monkeypatch):
    indice.sincronizar_paciente(1, [Fragmento("lab-1", "Hemoglobina 11 g/dL", "expediente", "laboratorio", 1),
                                    Fragmento("lab-2", "CEA 3 ng/ml", "expediente", "laboratorio", 1)])

    def sin_segmento(**_k):
        raise RuntimeError("Error creating hnsw segment reader: Nothing found on disk")

    monkeypatch.setattr(indice._coleccion, "query", sin_segmento)
    r = indice.buscar("hemoglobina", paciente_id=1, k=2)
    assert [x.id for x in r][0] == "lab-1" and r[0].similitud > r[1].similitud


def test_un_indice_creado_en_l2_se_rehace_con_coseno(tmp_path):
    import chromadb

    from asistente.indice import COLECCION, _espacio

    cliente = chromadb.PersistentClient(path=str(tmp_path / "vec"))
    viejo = cliente.get_or_create_collection(COLECCION)            # sin métrica: L2, como quedaban antes
    viejo.add(ids=["lab-1"], documents=["x"], embeddings=[[1.0] + [0.0] * (DIM - 1)])
    idx = IndiceVectorial(cliente=cliente, embeddings=embeddings_falsos)
    assert _espacio(idx._coleccion) == "cosine" and idx.cuantos() == 0   # se reindexa al consultar


def test_el_resumen_arma_el_panorama_sin_depender_de_la_similitud(expediente, indice, monkeypatch):
    conn, ids = expediente
    monkeypatch.setenv("COPILOTO_UMBRAL_SIMILITUD", "0.99")         # ningún fragmento pasaría por parecido
    r = g.ejecutar("Resume el caso", deps(conn, ids, indice), paciente_activo=ids["paciente_maria"])
    assert r["estado"] == "respondida"
    prefijos = {f["id"].split("-")[0] for f in r["fuentes"]}
    assert {"biomarcador", "lab", "imagen"} <= prefijos
    assert any(p["titulo"] == "Armé el panorama del caso" for p in r["pasos"])


def test_la_estadificacion_informa_el_estadio_registrado_aunque_falte_el_tnm(expediente, indice):
    conn, ids = expediente
    pid = ids["paciente_maria"]
    conn.execute("UPDATE pacientes SET estadio = 'IV' WHERE id = ?", (pid,))
    r = g.ejecutar("¿En qué estadio está?", deps(conn, ids, indice), paciente_activo=pid)
    assert r["estado"] == "respondida" and "Estadio registrado en el expediente: IV" in r["respuesta"]
    assert f"paciente-{pid}" in [f["id"] for f in r["fuentes"]]


def test_una_repregunta_se_entiende_con_la_pregunta_anterior(expediente, indice, monkeypatch):
    conn, ids = expediente
    monkeypatch.setenv("COPILOTO_UMBRAL_SIMILITUD", "0")                # que llegue al modelo
    consultas = []
    original = indice.buscar
    monkeypatch.setattr(indice, "buscar", lambda q, **k: consultas.append(q) or original(q, **k))
    monkeypatch.setattr(llm, "disponible", lambda: True)
    monkeypatch.setattr(llm, "descripcion", lambda: "modelo de prueba")
    prompts = []
    monkeypatch.setattr(llm, "redactar", lambda s, u, timeout=None: prompts.append(u) or MENSAJE_SIN_INFORMACION)
    historia = [{"rol": "medico", "texto": "¿Cuál es el HER2?"}, {"rol": "asistente", "texto": "HER2 negativo."}]
    g.ejecutar("¿Y eso desde cuándo?", deps(conn, ids, indice), paciente_activo=ids["paciente_maria"], historia=historia)
    assert "HER2" in consultas[0]
    assert "CONVERSACIÓN PREVIA" in prompts[0] and "HER2 negativo" in prompts[0]


def test_el_grafo_tiene_los_nodos_del_flujo():
    nombres = set(g.construir_grafo().get_graph().nodes)
    assert {"validar_intencion", "resolver_paciente", "recuperar", "evaluar_contexto", "responder", "rechazar", "guardar_historial"} <= nombres


# --- Historial ------------------------------------------------------------------------------------


def test_historial_por_usuario(tmp_path, monkeypatch):
    from asistente import historial

    monkeypatch.setenv("COPILOTO_CONVERSACIONES_DB", str(tmp_path / "c.db"))
    cid = historial.nueva_conversacion(2, "Caso de María")
    historial.guardar_mensaje(cid, "medico", "¿HER2?")
    historial.guardar_mensaje(cid, "asistente", "Negativo", fuentes=[{"id": "biomarcador-1"}], estado="respondida")
    assert historial.es_de(cid, 2) and not historial.es_de(cid, 3)
    assert [m["rol"] for m in historial.mensajes_de(cid)] == ["medico", "asistente"]
    assert historial.mensajes_de(cid)[1]["fuentes"] == [{"id": "biomarcador-1"}]
    assert historial.conversaciones_de(2)[0]["mensajes"] == 2 and historial.conversaciones_de(3) == []


# --- Enfermería: órdenes médicas, dosis y horarios ----------------------------------------------------


def _enfermeria(conn, ids, indice):
    import dataclasses

    return dataclasses.replace(deps(conn, ids, indice), perfil="enfermeria")


def _ordenar(conn, paciente_id, **cambios):
    from datetime import date

    from historia_clinica import ordenes_medicas as om

    datos = {"medicamento": "Ondansetrón", "dosis": "8 mg", "via": "VO", "intervalo_horas": 8, "fecha_inicio": date.today().isoformat(),
             "hora_inicio": "08:00", "ordenado_por": "Dra. Ana Gómez (dra.gomez)", **cambios}
    return om.prescribir(conn, paciente_id, **datos)


def test_enfermeria_pregunta_por_las_ordenes_y_se_citan(expediente, indice):
    conn, ids = expediente
    orden = _ordenar(conn, ids["paciente_maria"], indicaciones="Antes de la quimioterapia")
    r = g.ejecutar("¿Qué medicamentos tiene ordenados?", _enfermeria(conn, ids, indice), paciente_activo=ids["paciente_maria"])
    assert r["intencion"] == "medicacion" and r["estado"] == "respondida"
    assert "Ondansetrón 8 mg" in r["respuesta"] and f"orden-{orden.id}" in [f["id"] for f in r["fuentes"]]
    assert "Próximas administraciones" in r["respuesta"]


def test_sin_ordenes_lo_dice_sin_inventar(expediente, indice):
    conn, ids = expediente
    r = g.ejecutar("¿Qué le toca hoy y a qué hora?", _enfermeria(conn, ids, indice), paciente_activo=ids["paciente_maria"])
    assert r["estado"] == "respondida" and "No hay órdenes médicas activas" in r["respuesta"]


def test_enfermeria_no_recibe_recomendaciones_de_tratamiento(expediente, indice):
    conn, ids = expediente
    r = g.ejecutar("¿Qué opciones de tratamiento tiene?", _enfermeria(conn, ids, indice), paciente_activo=ids["paciente_maria"])
    assert r["estado"] == "fuera_de_rol" and "oncólogo tratante" in r["respuesta"]
    assert "recuperar" not in nodos(r) and not r.get("fuentes")


def test_enfermeria_si_consulta_datos_del_expediente(expediente, indice):
    conn, ids = expediente
    r = g.ejecutar("¿Cuál es el HER2?", _enfermeria(conn, ids, indice), paciente_activo=ids["paciente_maria"])
    assert r["estado"] == "respondida" and "negativo" in r["respuesta"].lower()


def test_las_ordenes_suspendidas_no_salen_como_vigentes(expediente, indice):
    from historia_clinica import ordenes_medicas as om

    conn, ids = expediente
    o = _ordenar(conn, ids["paciente_maria"])
    om.suspender(conn, ids["paciente_maria"], o.id, suspendida_por="Dra. Gómez", motivo="Náuseas controladas")
    r = g.ejecutar("¿Qué medicamentos tiene ordenados?", _enfermeria(conn, ids, indice), paciente_activo=ids["paciente_maria"])
    assert "No hay órdenes médicas activas" in r["respuesta"] and "Náuseas controladas" in r["respuesta"]
