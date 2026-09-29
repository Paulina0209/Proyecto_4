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
3. Opcional: `OPENAI_MODEL` (por defecto `gpt-5.4-mini`) y
   `OPENAI_TIMEOUT` en segundos (por defecto 120).

El `.env` está en `.gitignore`: **nunca** se sube a GitHub. Solo se versiona
`.env.example`, sin llaves.

```powershell
pip install -r requirements.txt
python -m ia_clinica.summary.demo    # IA-04 con GPT
python -m ia_clinica.review.demo     # IA-02 + IA-03 con GPT
python demo_tx.py                    # agente de tratamiento con GPT
```

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
