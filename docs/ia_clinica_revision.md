# IA-03 — Revisión y aprobación de la nota clínica generada

## Alcance de esta implementación

Este documento describe el diseño del módulo `ia_clinica/review`, que
implementa la historia de usuario **IA-03** del backlog
(`backlog_copiloto_oncologico.md`):

> Como oncólogo, quiero revisar, editar y aprobar el borrador de una nota
> clínica generada por IA, para asegurarme de que su contenido sea
> correcto antes de convertirla en una nota clínica oficial.

IA-03 depende formalmente de IA-02 (`ia_clinica.notes`), ya implementada.
Este módulo recibe el `ClinicalNoteDraft` que produce IA-02 y le agrega el
ciclo de vida de revisión/aprobación; no vuelve a generar contenido
clínico ni a validar trazabilidad contra la consulta (eso ya lo hizo
IA-02).

## Ya hay un modelo real conectado (Ollama)

El proyecto ya tiene un modelo local corriendo con Ollama, usado hasta
ahora por `tx_clinica` (TX-01) para redactar el rationale de una
recomendación de tratamiento. Como parte de esta historia, ese mismo
modelo se conecta también a IA-02 a través de un nuevo cliente:
`ia_clinica.notes.llm_client.OllamaLLMClient`.

Sigue exactamente el mismo contrato (`LLMClient.complete(system_prompt,
user_prompt) -> str`) que ya usaba `RuleBasedLLMClient`, así que
`ClinicalNoteGenerator` no necesitó ningún cambio: sigue validando cada
sección contra los fragmentos reales de la consulta antes de aceptarla en
el borrador (ver `docs/ia_clinica_notas.md`). Esa validación importa
todavía más ahora que hay un LLM real detrás: a diferencia del cliente de
referencia (que solo copia texto existente), un modelo de lenguaje sí
puede redactar contenido que no provenga literalmente de un fragmento —
sigue siendo el generador, no el cliente, quien garantiza que eso nunca
llegue al borrador sin una cita verificable.

`OllamaLLMClient` requiere Ollama corriendo localmente:

```
ollama serve
ollama pull qwen2.5:14b-instruct-q4_K_M
```

Expone además `esta_disponible()`, un chequeo de salud liviano (solo
consulta `/api/tags`, no genera texto) para poder decidir en tiempo de
ejecución si usarlo o usar `RuleBasedLLMClient` como respaldo — así el
demo de esta historia (y cualquier otro código) no se rompe si Ollama no
está corriendo en esa máquina en ese momento.

**Nota de alcance:** el flujo de revisión/aprobación de IA-03 en sí mismo
(`ia_clinica.review`) es independiente de qué LLM generó el borrador.
Todo lo que se describe más abajo funciona igual con `OllamaLLMClient`,
`RuleBasedLLMClient`, o cualquier otro `LLMClient` futuro.

## Cómo se satisface cada criterio de aceptación

| Criterio de aceptación | Mecanismo en el código |
|---|---|
| Dado un borrador de IA, puedo modificar manualmente su contenido antes de aprobarlo | `service.editar_seccion()` actualiza el contenido de una sección mientras la nota siga en estado `DRAFT`; el `ClinicalNoteDraft` original de IA-02 nunca se toca — se guarda una copia congelada (`contenido_ia_original`) aparte del contenido vigente (`contenido_actual`). |
| Al guardar cambios, el sistema conserva la versión modificada para revisión posterior | `store.guardar_edicion()` persiste el nuevo contenido y agrega un registro (`EdicionRegistrada`: autor, contenido anterior/nuevo, fecha) al historial en la base SQLite — no en memoria de un objeto Python. `NotaEnRevision.historial_ediciones` expone ese historial completo. |
| Si no se aprueba, la nota sigue identificada como "borrador no confirmado" aunque se cierre sesión o se abandone la edición | El estado (`EstadoNota.DRAFT`/`APPROVED`) vive en una tabla SQLite (`ia_clinica/review/schema.sql`), no en memoria: una conexión nueva (simulando "volver a entrar") que consulte la misma nota ve exactamente el mismo estado. Ver `demo.py` (PASO 4) y `tests/ia_clinica/review/test_service.py::TestPermaneceComoBorradorSinAprobacion`, que cierra la conexión y abre una nueva sobre el mismo archivo. |
| Con una acción explícita de aprobación, el estado cambia de borrador a nota aprobada | `service.aprobar_nota()` / `store.aprobar_nota()` es la **única** función que escribe `estado = APPROVED`, y exige un `aprobado_por` no vacío (identificador del médico autorizado). No existe ninguna otra función, atajo, ni transición automática que produzca ese cambio. |
| Una nota en borrador no puede presentarse como nota clínica oficial | `NotaEnRevision.es_nota_oficial()` es el único método que debería usarse para esa decisión; devuelve `True` únicamente si `estado is EstadoNota.APPROVED`. `NotaEnRevision` es un snapshot de solo lectura: no tiene ningún setter de `estado`. |

## Regla de negocio: ninguna aprobación implícita

> Ninguna nota generada por IA puede adquirir estado final u oficial sin
> una acción explícita de aprobación por parte del médico autorizado.

Esto se sostiene con varias decisiones de diseño conjuntas, no una sola:

1. `NotaEnRevision` es un `frozen dataclass` de solo lectura: no expone
   `aprobar()`, `confirmar()` ni ningún mutador. Toda mutación pasa por
   funciones de módulo (`store`/`service`), nunca por un método del
   propio objeto.
2. `store.py` no tiene ninguna función genérica `actualizar_estado(...)`:
   solo `crear_revision`, `guardar_edicion` y `aprobar_nota`, cada una
   correspondiente a exactamente una acción explícita de la historia. Es
   imposible poner `estado = "APPROVED"` por un camino distinto a
   `aprobar_nota()`.
3. `aprobar_nota()` valida que `aprobado_por` no esté vacío — una
   aprobación anónima o "de sistema" no es una aprobación válida.
4. `aprobar_nota()` lanza `NotaYaAprobadaError` si la nota ya estaba
   aprobada: no se puede "reaprobar" pisando silenciosamente quién y
   cuándo aprobó originalmente (importante para el riesgo regulatorio de
   la historia: la auditoría de quién aprobó qué nota debe ser
   confiable).
5. Una vez aprobada, `guardar_edicion()` (y por lo tanto
   `service.editar_seccion()`) rechaza cualquier intento de edición con
   `NotaYaAprobadaError`. Editar una nota ya oficial desde este flujo de
   borrador reintroduciría exactamente el riesgo que la historia busca
   evitar (contenido no revisado colándose en el expediente oficial).

## Por qué la persistencia es SQLite y no un objeto en memoria

El criterio de aceptación "si cierro sesión o abandono el proceso de
edición, la nota sigue identificada como borrador no confirmado" no se
puede demostrar de forma convincente con un objeto Python que vive solo
en memoria del proceso actual — eso sería cierto por definición, sin
probar nada sobre persistencia real. `ia_clinica/review/store.py` guarda
cada revisión en una tabla SQLite propia (`revision_notas`), separada de
`historia_clinica_mock` porque una nota en revisión no es un dato clínico
del expediente, es un artefacto del flujo de trabajo del copiloto. Esto
permite que las pruebas (y el demo) abran una conexión, hagan cambios,
cierren esa conexión, abran una conexión **nueva** apuntando al mismo
archivo, y verifiquen que el estado observado es el mismo — una
simulación razonable de "cerrar sesión y volver a entrar".

## Componentes

- `models.py`: `EstadoNota` (`DRAFT`/`APPROVED`), `EdicionRegistrada`,
  `AprobacionRegistrada`, `NotaEnRevision` (snapshot de solo lectura),
  excepciones (`RevisionNoEncontradaError`, `RevisionYaExisteError`,
  `NotaYaAprobadaError`).
- `schema.sql` / `store.py`: persistencia SQLite; único módulo que
  escribe en la tabla `revision_notas`.
- `service.py`: `iniciar_revision(conn, borrador_ia02)`,
  `editar_seccion(...)`, `aprobar_nota(...)`, `obtener_revision(...)` —
  capa fina que traduce entre `ClinicalNoteDraft` (IA-02) y el
  almacenamiento de IA-03.
- `demo.py`: flujo completo — genera un borrador (con `OllamaLLMClient`
  si hay servidor disponible, si no con `RuleBasedLLMClient`), inicia la
  revisión, edita una sección, cierra y reabre la conexión para simular
  "cerrar sesión", aprueba explícitamente, y muestra que ya no se puede
  editar después de aprobada.

## Cómo probarlo

```
python -m ia_clinica.review.demo
```

Y las pruebas automatizadas:

```
pytest tests/ia_clinica/review -v
pytest tests/ia_clinica/notes/test_ollama_llm_client.py -v
```

Las pruebas de `OllamaLLMClient` no requieren un servidor Ollama real:
simulan la librería `requests` para verificar el contrato (qué se envía,
qué se devuelve, y que los errores de red se traducen en
`OllamaConnectionError`).

## Fuera de alcance de esta historia

- **Autenticación real de "médico autorizado":** este repositorio no
  tiene un sistema de usuarios/roles. `aprobado_por` es un identificador
  de texto que quien llama debe proporcionar explícitamente; validar que
  ese identificador corresponde a un oncólogo con permisos reales es
  responsabilidad de una capa de autenticación/autorización que no existe
  todavía en el proyecto.
- **Enmienda de una nota ya aprobada:** una vez `APPROVED`, este módulo no
  ofrece ningún camino para seguir modificándola (a propósito, ver regla
  de negocio arriba). Corregir una nota oficial ya aprobada sería una
  historia distinta, con su propio rastro de auditoría explícito.
- **Integración con el expediente oficial del paciente:** esta historia
  deja la nota en estado `APPROVED` dentro de `revision_notas`; llevarla
  al expediente real del paciente (`historia_clinica_mock` u otro sistema
  en producción) es un paso posterior no definido en el backlog todavía.
