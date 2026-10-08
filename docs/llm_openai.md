# Modelo de lenguaje: OpenAI (GPT)

El proyecto usa un modelo GPT de OpenAI como LLM real. Reemplaza al modelo
local servido por Ollama (`qwen2.5:14b-instruct`) que se usaba antes: ya no
hace falta `ollama serve` ni descargar modelos.

## Quién lo usa

| Componente | Cómo |
|---|---|
| IA-02 / IA-03 (`ia_clinica.notes`, `ia_clinica.review`) | `ia_clinica.notes.llm_client.OpenAILLMClient` |
| IA-04 (`ia_clinica.summary`) | El mismo `OpenAILLMClient`, con otro prompt |
| Agente de tratamiento (`tx_clinica/agent.py`) | `langchain_openai.ChatOpenAI` |

Ambos leen la llave y el modelo de `core/llm_config.py`, así que cambiar de
modelo es cambiar una variable de entorno.

## Configuración

1. Copia `.env.example` como `.env` en la raíz del repositorio.
2. Pon tu llave en `OPENAI_API_KEY` (por compatibilidad también se acepta
   `API_KEY`).
3. Opcional: `OPENAI_MODEL` (por defecto `gpt-6-luna`) y
   `OPENAI_TIMEOUT` en segundos (por defecto 120).

El `.env` está en `.gitignore`: **nunca** se sube a GitHub. Solo se versiona
`.env.example`, sin llaves.

```powershell
pip install -r requirements.txt
python demo.py --solo ia tx          # IA-02/03/04 y agente de tratamiento con GPT
python demo_tx.py                    # agente de tratamiento, conversación libre
```

## Verificar la conexión

```powershell
python -c "from ia_clinica.notes.llm_client import OpenAILLMClient; print(OpenAILLMClient().esta_disponible())"
```

Devuelve `True` si la llave del `.env` es válida y tiene acceso al modelo
configurado. Es una consulta de metadatos (`models.retrieve`): no genera texto
ni envía datos.

## Particularidades de gpt-6-luna

- **Respuestas en bloques.** Las respuestas del agente llegan como una lista de bloques (`[{"type": "text", "text": ...}]`), no como un `str`.
  - `tx_clinica.conversacion` usa `.text` para que `RespuestaAgente.texto` sea siempre un `str`.
  - Al leer mensajes del agente, use `.text` y no `.content`.
- **Sin parámetros especiales.** Las llamadas no envían `temperature` ni `max_tokens`, así que no hay parámetros que el modelo pueda rechazar.
- **Dependencia.** El agente necesita `langchain-openai` (está en `requirements.txt`).

## Trazas (Langfuse)

El agente de TX envía una traza por mensaje a Langfuse (`LANGFUSE_HOST`,
`LANGFUSE_PUBLIC_KEY` y `LANGFUSE_SECRET_KEY` en el `.env`). Cada traza tiene:

- la sesión (`thread_id` de la conversación) y el usuario (oncólogo);
- las llamadas a `gpt-6-luna` y las herramientas usadas;
- la respuesta final como texto.

**Máscara de datos.** Con `LANGFUSE_MASK_DATOS_PACIENTE=true`, el campo
`nombre` que devuelven las herramientas llega como `[REDACTADO]`.
`inicializar_langfuse` lee el `.env` antes de crear el cliente, así que la
máscara se aplica aunque quien construye el agente no lo haya cargado.
Limitación: un nombre escrito en texto libre (en el chat o en la respuesta del
modelo) no se detecta.

**Servidor local.** El `.env` apunta a un Langfuse v4 en Docker
(`http://localhost:3000`).
- **Si no está corriendo:** el agente funciona igual, pero al terminar aparece `Failed to export span batch due to timeout`. Levántelo, o ponga `LANGFUSE_TRACING_ENABLED=false` en el `.env`.
- **Para consultar trazas por API:** Langfuse v4 en modo `events_only` no ofrece `/api/public/traces`. Use `/api/public/v2/observations?traceId=<id>&fields=core,basic,io,model`.

## Salvaguardas que no cambian

- El modelo solo redacta. `ClinicalNoteGenerator` y `CaseSummaryGenerator`
  siguen descartando cualquier sección sin cita a un fragmento real.
- Se pide `response_format={"type": "json_object"}`: la API garantiza JSON
  válido.
- Si no hay llave o no hay red, `esta_disponible()` devuelve `False` y los
  demos usan el cliente por reglas (`RuleBasedLLMClient` /
  `RuleBasedSummaryLLMClient`), sin romperse.
- Las pruebas (`tests/ia_clinica/notes/test_openai_llm_client.py`) no llaman
  a la API: usan un cliente falso.

## Privacidad

A diferencia de Ollama, los prompts salen de la máquina hacia OpenAI. Hoy
solo se envían datos sintéticos o desidentificados (cBioPortal). Antes de
enviar datos de pacientes reales identificables hay que revisar las
condiciones de uso y retención de datos del proveedor con la institución.
