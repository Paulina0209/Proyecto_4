# IA-02 — Generación automática de notas clínicas

## Alcance de esta implementación

Este documento describe el diseño del módulo `ia_clinica/notes`, que
implementa la historia de usuario **IA-02** del backlog
(`backlog_copiloto_oncologico.md`, sección 10.2).

> Como oncólogo, quiero que el sistema genere automáticamente un borrador
> estructurado de nota clínica a partir de la información registrada
> durante la consulta, para reducir el tiempo dedicado a la documentación
> clínica.

IA-02 depende formalmente de IA-01 (consulta en lenguaje natural sobre el
expediente) según el backlog. Como IA-01 todavía no está implementada en
este repositorio, este módulo se diseñó para **no depender de código de
IA-01**: recibe un `ClinicalContext` ya construido (los fragmentos de la
consulta) como entrada explícita, en vez de ir a buscar datos por su
cuenta. Cuando IA-01 (o la integración HC-01/02/04) exista, puede
construir ese `ClinicalContext` y pasarlo a este generador sin cambios en
este módulo.

**Nota importante sobre las guías clínicas (`guidelines/`):** este módulo
*no* usa el contenido de `guidelines/` para generar la nota. El criterio de
aceptación de IA-02 exige que "el contenido generado corresponde
únicamente a información disponible en el contexto clínico proporcionado"
(es decir, la consulta), y las guías de tratamiento no son parte de ese
contexto — son conocimiento de referencia para las historias de la épica
TX/DX (recomendación de tratamiento), que tienen su propio mecanismo de
citación de evidencia (IA-04) y no deben mezclarse con la redacción de la
nota de la consulta. Mezclar ambas fuentes en este generador aumentaría el
riesgo de alucinación que la propia historia busca evitar.

## Cómo se satisface cada criterio de aceptación

| Criterio de aceptación | Mecanismo en el código |
|---|---|
| Genera un borrador estructurado en SOAP o el estándar configurado | `formats.py` define `SOAP_FORMAT` y `get_format()`; una institución puede registrar su propio `NoteFormatSpec` sin tocar el generador. |
| El contenido corresponde únicamente al contexto proporcionado | `generator.py` exige que cada sección documentada cite `source_span_ids` que existan realmente en el `ClinicalContext`; si no hay ninguna referencia válida, la sección se descarta. Además se calcula una cobertura léxica de aviso (no bloqueante) para reforzar la revisión manual. |
| No inventa información para secciones con datos faltantes | Toda sección sin contenido válido (marcada `missing` por el modelo, omitida, o sin fragmento verificable) se reemplaza por el texto fijo `MISSING_INFO_MARKER`, nunca por texto libre. |
| El resultado queda identificado explícitamente como borrador de IA | `ClinicalNoteDraft.is_ai_generated_draft` es siempre `True`, `status` es siempre `"borrador_ia_no_confirmado"`, y `to_text()` antepone el aviso. No existe ningún método para "firmar" o marcar la nota como oficial en este módulo. |

## Formas de entregar la información de la consulta

El criterio de aceptación de IA-02 no exige que quien registra la consulta
la entregue ya separada por tema. Hay dos formas de construir el
`ClinicalContext`, y ambas producen el mismo tipo de borrador:

1. **Fragmentos ya separados**: se construye `ClinicalContext` pasando
   directamente la lista de `SourceSpan` (por ejemplo, si la transcripción
   ya viene marcada por turno de habla, o si otra pantalla ya capturó
   campos discretos).
2. **Un solo párrafo de texto libre**: `ClinicalContext.from_text(...)`
   separa automáticamente el texto en oraciones (usa puntuación de cierre
   y saltos de línea) y genera un `SourceSpan` por oración. Esto es lo más
   parecido a "un oncólogo dicta todo de una vez" y es la forma recomendada
   de entrada cuando no hay una fuente ya estructurada.

**Importante — limitación conocida del cliente de referencia
(`RuleBasedLLMClient`):** si en vez de usar `from_text` se construye un
`ClinicalContext` con un único `SourceSpan` que contiene todo el párrafo
sin segmentar, `RuleBasedLLMClient` (que no es un LLM, solo clasifica por
palabras clave a nivel de fragmento completo) no puede separar internamente
ese bloque: el mismo párrafo completo queda repetido en cada sección cuya
palabra clave aparezca en él. Esto está documentado y cubierto por una
prueba (`test_parrafo_sin_segmentar_con_cliente_de_referencia_no_separa_secciones`)
para que no se confunda con un defecto del generador — el generador sí
valida correctamente contra el fragmento citado, es la heurística de
clasificación la que es demasiado simple para texto sin segmentar. Un LLM
real, en cambio, sabría dividir un párrafo único en las secciones
correctas aunque llegue como un solo fragmento; aun así, se recomienda
usar `from_text` (o fragmentos ya separados) para conservar trazabilidad
más fina, a nivel de oración en vez de a nivel de párrafo completo.

## Componentes

- `models.py`: `SourceSpan`, `ClinicalContext`, `NoteSectionDraft`,
  `ClinicalNoteDraft`.
- `formats.py`: `NoteFormatSpec`, `NoteSectionSpec`, `SOAP_FORMAT`,
  `get_format()`.
- `llm_client.py`: interfaz `LLMClient`; `RuleBasedLLMClient` (implementación
  de referencia sin proveedor externo, usada por defecto en desarrollo y
  pruebas); `AnthropicLLMClient` (adaptador opcional, no instanciado por
  defecto); `OllamaLLMClient` (adaptador para el modelo local ya
  configurado con Ollama en este proyecto — usado a partir de IA-03; ver
  `docs/ia_clinica_revision.md`).
- `generator.py`: `ClinicalNoteGenerator`, `GenerationError`.

## Actualización (IA-03): ya hay un proveedor de LLM real conectado

Lo que la sección anterior llamaba "decisión pendiente para producción"
ya está resuelto parcialmente: `llm_client.OllamaLLMClient` conecta este
generador con el modelo local que el proyecto ya tiene corriendo con
Ollama (el mismo servidor que usa `tx_clinica` para TX-01). Sigue el
mismo contrato `LLMClient` que `RuleBasedLLMClient`, así que
`ClinicalNoteGenerator` no cambió en absoluto: toda la validación
anti-alucinación de esta sección (citas a `source_span_ids` reales,
descarte de contenido sin fuente verificable, `MISSING_INFO_MARKER`)
sigue aplicándose exactamente igual, sea cual sea el cliente. De hecho
es *más* importante con `OllamaLLMClient`: a diferencia del cliente de
referencia (que solo copia texto existente y por lo tanto nunca puede
"alucinar"), un modelo de lenguaje real sí puede redactar contenido que
no provenga literalmente de un fragmento — es este generador, no el
cliente, quien sigue garantizando que eso nunca llegue al borrador
final sin una cita válida.

`RuleBasedLLMClient` se conserva como valor por defecto seguro para
pruebas y para cuando no hay un servidor Ollama disponible (no depende
de red ni de que el modelo esté descargado).

## Decisión pendiente para producción

1. Validar clínicamente el prompt del sistema (`build_system_prompt`) con
   el equipo médico antes de exponerlo a oncólogos reales, incluso usando
   ya un modelo real.
2. Definir en qué punto del flujo clínico se conecta este módulo con el
   registro de la consulta (dictado/transcripción) — hoy el
   `ClinicalContext` se construye manualmente porque esa integración de
   captura de consulta no existe aún en el repositorio.
3. Evaluar si el modelo local (`qwen2.5:14b-instruct-q4_K_M` vía Ollama)
   es suficiente para producción o si conviene un proveedor gestionado
   (`AnthropicLLMClient` ya deja esa integración lista si se elige esa
   ruta más adelante).
