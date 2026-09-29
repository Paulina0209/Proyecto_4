 IA-04 — Resumen clínico de caso para junta médica / interconsulta

## Alcance de esta implementación

Este documento describe el diseño del módulo `ia_clinica/summary`, que
implementa la historia de usuario recibida esta sesión como **IA-04**:

> Como oncólogo, quiero generar un resumen médico del caso completo, para
> poder compartirlo durante juntas médicas o interconsultas con otros
> especialistas.

Criterios de aceptación:

> Dado un paciente con historia clínica suficiente, cuando solicito el
> resumen, entonces recibo un documento estructurado listo para
> presentarse en una junta médica.
>
> Dado que el paciente tiene información incompleta, cuando genero el
> resumen, entonces el documento indica explícitamente las secciones con
> datos faltantes.

Dependencias formales indicadas junto con la historia: **IA-02** (ya
implementada, `ia_clinica.notes`) y **HC-06**.

> **Nota de numeración.** El backlog versionado
> (`backlog_copiloto_oncologico.md`) ya registra un **IA-04** distinto:
> "Como oncólogo, quiero que cada recomendación de la IA muestre el
> razonamiento y las fuentes que la sustentan" — con dependencia `IA-01`
> únicamente, ya cubierto por `ia_clinica/explainability/`. La historia de
> "resumen de caso" descrita arriba se recibió esta sesión explícitamente
> rotulada como IA-04, con otras dependencias (`AI-02, HC-06`) y otro
> contenido. Se implementó tal como se pidió, dejando esta nota para
> reconciliar la numeración del backlog cuando corresponda.

## Por qué necesita su propio adaptador (no reutiliza `ClinicalContext`)

IA-02 razona sobre una **consulta puntual**: `ClinicalContext` solo
contiene lo registrado en esa consulta. Un resumen para junta médica, en
cambio, necesita "diagnóstico, estadio, tratamientos previos y estado
actual" del **caso completo** — el mismo alcance de "todo el expediente
disponible" que ya usa DX-02 (`obtener_hallazgos_de_paciente`), no el de
IA-02.

Por eso `ia_clinica.summary.models.CaseSummaryContext` combina dos tipos
de información:

1. **Datos estructurados del paciente** (`diagnostico_principal`,
   `estadio`, columnas de la tabla `pacientes`): se copian directamente,
   sin pasar por ningún LLM. No hay nada que "redactar" ni que alucinar
   en un dato que ya está en una columna de la base de datos, y son
   además los dos datos más consecuentes de la junta médica — eliminar
   por completo cualquier dependencia del modelo para estos dos campos
   es una decisión de diseño deliberada, no un descuido.
2. **Hallazgos no estructurados de todo el expediente** (notas de
   consulta, laboratorios, imagenología, biomarcadores — los mismos que
   reúne `obtener_hallazgos_de_paciente`): de estos sí hace falta extraer
   "tratamientos previos" y "estado actual", que no existen como columnas
   discretas. Ahí participa el generador/LLM, con la misma validación de
   trazabilidad que ya usa IA-02.

El adaptador `expediente.adapters.construir_contexto_resumen_caso`
arma ese contexto reutilizando `obtener_hallazgos_de_paciente` (sin
duplicar su lógica) y convirtiendo cada `HallazgoClinico` a un
`SourceSpan` — el mismo tipo que ya usa IA-02 para poder citar
fragmentos exactos.

## Ya hay un modelo real conectado (OpenAI) — se reutiliza sin cambios

Igual que IA-03, esta historia reutiliza el modelo GPT del proyecto
(`ia_clinica.notes.llm_client.OpenAILLMClient`, ver `docs/llm_openai.md`),
sin necesidad de un segundo cliente ni un segundo adaptador: el
generador de IA-04 simplemente le pasa un prompt distinto al mismo
`LLMClient.complete(system_prompt, user_prompt) -> str`.

Solo se le pide al modelo redactar **dos** de las cuatro secciones
("tratamientos_previos" y "estado_actual") — nunca "diagnóstico" ni
"estadio" (ver sección anterior). `ia_clinica.summary.llm_client` define
el prompt de sistema con esta restricción explícita, y
`RuleBasedSummaryLLMClient` (clasificador léxico sin red, análogo a
`RuleBasedLLMClient` de IA-02) sirve de respaldo automático si el
modelo de OpenAI no está disponible, exactamente con el mismo mecanismo de
`esta_disponible()` que ya usan los demos de IA-02/IA-03.

## Cómo se satisface cada criterio de aceptación

| Criterio de aceptación | Mecanismo en el código |
|---|---|
| Con historia clínica suficiente, se recibe un documento estructurado listo para junta médica | `CaseSummaryGenerator.generate_summary()` siempre produce las cuatro secciones en el mismo orden (`ORDEN_SECCIONES`); `CaseSummary.to_text()` arma el documento completo (disclaimer + encabezado + secciones) listo para copiar/presentar. Ver `demo.py`, escenario A. |
| Con información incompleta, el documento indica explícitamente qué secciones faltan | Toda sección sin dato suficiente (estructurado o derivado) queda con `status="missing"` y `content=MISSING_INFO_MARKER`; `CaseSummary.secciones_faltantes()` las enumera y `to_text()` antepone un bloque `⚠ INFORMACIÓN INCOMPLETA — secciones sin datos suficientes...` al inicio del documento, visible de un vistazo. Ver `demo.py`, escenario B. |

## Regla de negocio heredada: nunca se inventa contenido clínico

Igual que IA-02, ninguna sección derivada (`tratamientos_previos`,
`estado_actual`) puede llegar al resumen sin una cita verificable:

1. Si el modelo marca la sección como `"missing"`, se respeta tal cual.
2. Si el modelo cita un `source_span_id` que no existe en el contexto, esa
   cita se descarta; si no queda ninguna cita válida, la sección completa
   se descarta y se reemplaza por `MISSING_INFO_MARKER` — nunca se acepta
   contenido "documentado" sin al menos un fragmento real que lo respalde.
3. Si el contenido aceptado comparte poco vocabulario con los fragmentos
   citados (cobertura léxica baja), se conserva pero se agrega una
   advertencia pidiendo verificación manual reforzada — igual que en
   `ClinicalNoteGenerator` de IA-02.
4. Si el paciente no tiene ningún hallazgo registrado en absoluto
   (`context.segments` vacío), ni siquiera se llama al modelo: ambas
   secciones derivadas se marcan como faltantes directamente, porque no
   hay nada de qué extraerlas.

## Componentes

- `models.py`: `CaseSummaryContext` (contexto de entrada, análogo a
  `ClinicalContext` de IA-02 pero a nivel de todo el paciente),
  `CaseSummarySection`, `CaseSummary` (documento de salida — siempre
  `is_ai_generated_draft=True`, sin ningún método para "aprobarlo" u
  "oficializarlo"), constantes de sección (`DIAGNOSTICO`, `ESTADIO`,
  `TRATAMIENTOS_PREVIOS`, `ESTADO_ACTUAL`) y `AI_SUMMARY_DISCLAIMER`.
- `llm_client.py`: `build_system_prompt()` / `build_user_prompt()`
  (prompts específicos de IA-04, piden únicamente las dos secciones
  derivadas) y `RuleBasedSummaryLLMClient` (implementación de referencia
  sin proveedor externo).
- `generator.py`: `CaseSummaryGenerator.generate_summary()` — orquesta las
  secciones estructuradas (directas) y las derivadas (vía `LLMClient` +
  validación de trazabilidad), y `CaseSummaryGenerationError`.
- `expediente/adapters.py`: nuevo
  `construir_contexto_resumen_caso(conn, paciente_id)`.
- Demo: `python demo.py --solo ia` (demo unificada sobre pacientes reales de cBioPortal; ver `docs/DEMO_UNIFICADA.md`).

## Cómo probarlo

```
python demo.py --solo ia
```

Y las pruebas automatizadas:

```
pytest tests/ia_clinica/summary -v
pytest tests/expediente/test_adapters.py -v
```

## Configuración del modelo (recordatorio)

Solo hace falta la llave de OpenAI en el `.env` de la raíz
(`OPENAI_API_KEY`); el modelo se cambia con `OPENAI_MODEL`. Ver
`docs/llm_openai.md`. Si no hay llave o no hay red, el demo lo detecta
solo (`esta_disponible()`) y sigue funcionando con
`RuleBasedSummaryLLMClient`, imprimiendo un aviso.

## Fuera de alcance de esta historia

- **Flujo de revisión/aprobación del resumen:** a diferencia de las notas
  de IA-02 (que sí tienen su propio flujo de aprobación en IA-03), esta
  historia no pidió uno para el resumen de caso; el documento se entrega
  siempre marcado como generado por IA y pendiente de revisión del
  oncólogo, pero este módulo no tiene tabla de persistencia ni estados
  `DRAFT`/`APPROVED` propios. Si se necesitara ese flujo más adelante,
  podría replicarse el patrón de `ia_clinica/review` sin cambios al
  generador.
- **Formato de exportación (PDF, PPTX, etc.):** `CaseSummary.to_text()` /
  `to_dict()` producen el contenido estructurado; convertirlo a un
  formato específico de presentación de junta médica es una decisión de
  producto no definida en el criterio de aceptación ("documento
  estructurado").
- **Reconciliación de la numeración IA-04 en el backlog** (ver nota al
  inicio de este documento).
