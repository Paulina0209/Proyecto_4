# Asistente clínico conversacional (chatbot RAG)

La forma principal de trabajar del oncólogo: conversa con el copiloto y, al lado,
ve la historia clínica del paciente con los registros de los que salió cada
respuesta resaltados. El universo de conocimiento son **solo** las bases del
sistema: el expediente de sus pacientes, los documentos cargados y las guías
clínicas versionadas.

```
┌ Conversaciones ┐┌──────────── Chat ─────────────┐┌──── Historia clínica ────┐
│ historial del  ││ pregunta → pasos en vivo →    ││ ficha, consultas, labs,  │
│ médico         ││ respuesta con citas [lab-12]  ││ imágenes, biomarcadores… │
└────────────────┘└───────────────────────────────┘│ ▲ fuente citada resaltada │
                                                   └──────────────────────────┘
```

## Arquitectura

| Capa | Dónde | Qué hace |
|---|---|---|
| Interfaz | `frontend/estatico/vista_chat.js` | Chat, pasos en vivo (NDJSON), panel de HC con resaltado de fuentes |
| API | `frontend/chat.py` | `POST /api/chat/mensajes` (flujo), historial, HC del panel. Sesión obligatoria, solo oncología, solo sus pacientes |
| Agente | `asistente/grafo.py` | `StateGraph` de LangGraph |
| Recuperación | `asistente/indice.py` | ChromaDB, embeddings de OpenAI (`text-embedding-3-small`) |
| Conocimiento | `asistente/fragmentos.py` | Expediente (mismos ids que la HC), documentos (DOC-01) y guías |
| Modelo | `asistente/llm.py` | GPT por defecto; Ollama local con `COPILOTO_LLM_PROVEEDOR=ollama` |
| Historial | `asistente/historial.py` | SQLite: conversaciones y mensajes con fuentes y pasos |

## El grafo

```
validar_intencion → resolver_paciente ─┬→ recuperar → evaluar_contexto ─┬→ responder → guardar_historial
                                       │                                └→ rechazar  → guardar_historial
                                       ├→ (aclaración / sin consentimiento) ──────────→ guardar_historial
                                       └→ responder_saludo ───────────────────────────→ guardar_historial
```

1. **validar_intencion**: dato, resumen, diagnóstico, estadificación, tratamiento, faltantes, evidencia o saludo (reglas, sin modelo).
2. **resolver_paciente**: el paciente abierto o el nombrado en la pregunta (id `P-…`, documento o nombre), solo entre los del médico. Si es ambiguo o falta, **pide aclaración**. Sin consentimiento de IA (SEC-03) no consulta nada.
3. **recuperar**: búsqueda vectorial filtrada por paciente (y en guías si aplica) + las funciones del sistema como datos estructurados: IA-01 (dato exacto), DX-02 (diferencial), EST-01/03, TX-01, HC-05.
4. **evaluar_contexto**: nodo dedicado; ¿hay con qué responder sin inventar?
5. **responder** / **rechazar**: el modelo redacta solo con el contexto y cita cada afirmación; o el rechazo explícito.
6. **guardar_historial**.

## Control de alucinaciones (cinco estrategias)

1. **Umbral de similitud** (`COPILOTO_UMBRAL_SIMILITUD`, 0.30): lo que no lo supera no entra al contexto.
2. **Nodo de validación del contexto** antes de redactar.
3. **Prompt** que obliga a usar solo el contexto y a citar con `[id]`.
4. **Verificación posterior**: citas que no están en el contexto se borran; un texto sin citas válidas se descarta y se responde con lo verificado.
5. **Rechazo explícito**: «No tengo suficiente información en mi base de conocimiento para responder esa pregunta.» + sugerencia de cargar documentos.

Además, **se muestran las fuentes** (con su similitud) y se resaltan en la historia clínica.

## Carga de documentos → base de conocimiento

DOC-01 (`POST /api/clinica/pacientes/{id}/documentos`): se guarda cifrado (SEC-02) y,
con consentimiento de IA, se **extrae el texto** (PDF/TXT), se **divide en fragmentos**
(~900 caracteres con solape), se **calculan embeddings**, se **guardan en ChromaDB**
asociados al documento y al paciente, y se **confirma** al usuario cuántos fragmentos se agregaron.

## Privacidad

- Solo se indexan pacientes con consentimiento de IA vigente; al retirarlo, salen del índice.
- El texto va **seudonimizado** (sin nombre, documento, teléfono ni correo, NFR-04) a OpenAI.
- El índice vive **fuera de OneDrive** (`%LOCALAPPDATA%/copiloto_clinico/vectorial`): las carpetas
  sincronizadas dañan sus binarios. Si se daña, se aparta y se reconstruye solo.

## Uso

```powershell
python -m datos preparar           # capas de datos (una vez)
python -m asistente indexar        # guías + pacientes con consentimiento (evita esperar en la primera pregunta)
python -m seguridad.servidor_tls --app frontend.servidor:app --cert certs/localhost.pem --key certs/localhost-clave.pem
# https://127.0.0.1:8443  ·  dra.gomez / Demo-Clave-2026
```

Variables: ver `asistente/config.py` (`COPILOTO_LLM_PROVEEDOR`, `OLLAMA_URL`, `OLLAMA_MODEL`,
`OPENAI_EMBEDDING_MODEL`, `COPILOTO_VECTORIAL_DIR`, `COPILOTO_UMBRAL_SIMILITUD`,
`COPILOTO_CONVERSACIONES_DB`, `COPILOTO_LLM_TIMEOUT`).

## Pruebas

```powershell
python -m pytest tests/asistente -q      # sin red: ChromaDB local y embeddings deterministas
```
