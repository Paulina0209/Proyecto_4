# IA-06 — Manejo de consultas clínicas ambiguas

## Historia

Como oncólogo, quiero que el asistente detecte cuándo una consulta clínica es
ambigua o no contiene suficiente contexto, para evitar respuestas incorrectas y
aclarar la información necesaria antes de recibir una respuesta.

## Dónde vive

Extiende el componente existente `clinical_query/` (IA-01). No se creó un
componente nuevo: IA-06 es una capa de detección **previa a la construcción de
la respuesta** dentro del mismo servicio.

- `clinical_query/ambiguity.py`: funciones puras de detección (sin estado, sin
  base de datos) y los tipos `AmbiguityKind` / `AmbiguityFinding` / `PacienteRef`.
- `clinical_query/service.py`: `NaturalLanguageClinicalQueryService.ask` orquesta
  la detección y decide entre responder o devolver una solicitud de aclaración
  (`QueryResponse.needs_clarification`). Acepta un parámetro opcional
  `clarification: Clarification` para reanudar la conversación.
- `clinical_query/normalizer.py`: `detect_concepts` devuelve **todos** los
  conceptos que la pregunta podría estar pidiendo (IA-01 usaba `detect_concept`,
  que se queda con uno solo en silencio).

## Los tres tipos de ambigüedad

Uno por criterio de aceptación de la historia:

1. **`PATIENT`** — la pregunta menciona el nombre o la identificación de un
   paciente distinto al activo (o de más de uno). Nunca se consulta a otro
   paciente: la recuperación **siempre** se acota al `patient_id` activo y,
   además, se pide confirmación (`Clarification(confirm_active_patient=True)`)
   antes de responder.
2. **`DATA_POINT`** — la pregunta menciona más de un dato clínico posible
   (`detect_concepts` devuelve 2+). Se listan las opciones y se pide especificar
   (`Clarification(concept=...)`).
3. **`EPISODE`** — el dato solicitado existe en más de un episodio (consulta) y
   la pregunta no trae un calificador temporal (`"último"`, `"más reciente"`,
   una fecha ISO…). Se listan los episodios con su valor y fecha y se pide
   indicar cuál (`Clarification(episode_id="consulta-N")`).

## Regla de negocio

Cuando la ambigüedad podría cambiar el significado clínico de la respuesta, el
asistente pide aclaración y **nunca selecciona una interpretación de forma
arbitraria**. No mezcla información entre pacientes ni entre episodios. La
aclaración del usuario se incorpora al contexto antes de volver a recuperar
información: el servicio es sin estado, así que se reenvía la misma pregunta
original junto con el `Clarification`.

## Datos de prueba

El paciente sintético 6 (`Diana Sofía Restrepo`) tiene la misma prueba
(hemoglobina) registrada en dos consultas distintas, para ejercitar la
ambigüedad de episodio sin tocar los pacientes ya fijados por otras pruebas.

## Pruebas y demo

- `tests/clinical_query/test_ia06_ambiguous_queries.py`: un caso por criterio de
  aceptación más el round-trip de aclaración.
- `demo_ia01.py`: `resolver_consulta_con_aclaracion` muestra el ciclo
  pregunta → solicitud de aclaración → reintento con el contexto aclarado.
