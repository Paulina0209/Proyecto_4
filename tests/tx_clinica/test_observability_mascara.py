"""La máscara de datos del paciente se activa aunque LANGFUSE_MASK_DATOS_PACIENTE
solo esté en el .env (y nadie lo haya cargado antes de construir el agente)."""

import json

from tx_clinica import observability


def test_la_mascara_se_activa_con_la_variable_del_env(monkeypatch):
    monkeypatch.delenv("LANGFUSE_MASK_DATOS_PACIENTE", raising=False)
    monkeypatch.setattr(observability, "_inicializado", False)
    creados = []
    monkeypatch.setattr(observability, "Langfuse", lambda **kwargs: creados.append(kwargs))

    from core import llm_config

    # Simula el .env de la raíz: la variable solo aparece al cargarlo.
    monkeypatch.setattr(llm_config, "cargar_env", lambda *a, **k: monkeypatch.setenv("LANGFUSE_MASK_DATOS_PACIENTE", "true"))

    observability.inicializar_langfuse()

    assert creados == [{"mask": observability._mascara_langfuse}]


def test_la_mascara_redacta_el_nombre_dentro_del_json_de_las_tools():
    salida_tool = json.dumps({"paciente_id": 7, "nombre": "Paciente X", "biomarcadores_clave": [{"biomarcador": "EGFR"}]})

    enmascarado = json.loads(observability._mascara_langfuse(salida_tool))

    assert enmascarado["nombre"] == "[REDACTADO]"
    assert enmascarado["biomarcadores_clave"] == [{"biomarcador": "EGFR"}]
