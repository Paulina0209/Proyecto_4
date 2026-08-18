# Base de datos mock de historia clínica oncológica

## Qué es y qué no es

`historia_clinica_mock/` es una base de datos SQLite pequeña, con datos
**sintéticos** (inventados, no reales), pensada para poder probar
`ia_clinica.notes` (IA-02) contra algo parecido a un historial clínico en
vez de construir un `ClinicalContext` a mano en cada prueba o demo.

**No es** una implementación de las historias HC-01 a HC-06 del backlog
(integración con sistemas externos, HL7/FHIR, laboratorios reales,
PACS/DICOM). No hay visor de imágenes, no hay ingesta de archivos, no hay
ningún estándar de interoperabilidad: es solo texto estructurado en unas
pocas tablas SQLite, suficiente para alimentar IA-02 con datos que sí
tienen la forma de una historia clínica oncológica (paciente, consultas,
laboratorios, imagenología, biomarcadores).

## Esquema

- `pacientes`: datos demográficos mínimos + diagnóstico principal y estadio.
- `consultas`: una consulta por paciente, con `notas_libres` (el texto
  dictado/resumido de la consulta — la entrada principal de IA-02).
- `laboratorios`, `imagenologia`, `biomarcadores`: resultados clínicos.
  Cada fila tiene una columna `consulta_id` **opcional**: cuando no es
  nula, indica que ese resultado se registró o revisó durante esa
  consulta puntual. Esto es lo que le permite al adaptador construir el
  contexto de "esta consulta" y no "todo el historial del paciente",
  que es justo el recorte que exige el criterio de aceptación de IA-02.

## El puente hacia IA-02 (`adapters.construir_contexto_clinico`)

Recibe un `consulta_id` y devuelve un `ia_clinica.notes.ClinicalContext`
con:

- un fragmento (`SourceSpan`) por cada oración de `notas_libres` de esa
  consulta (usa el mismo separador de oraciones que
  `ClinicalContext.from_text`, vía `ia_clinica.notes.split_sentences`);
- un fragmento por cada laboratorio/imagen/biomarcador vinculado a esa
  consulta, con un id que apunta a la fila real de la base de datos
  (`lab-7`, `imagen-3`, `biomarcador-2`).

Esto significa que, cuando `ClinicalNoteGenerator` genera el borrador, la
trazabilidad que expone (`draft.traceability`) apunta hasta la fila exacta
de la base de datos que sustenta cada sección — no solo a "la consulta"
en general. Es la forma concreta en que este mock cumple la observación
técnica de IA-02 sobre conservar trazabilidad entrada → borrador.

## Datos sintéticos incluidos (`seed.sembrar_datos_sinteticos`)

Dos pacientes ficticios:

1. **María Fernanda Ríos** — cáncer de mama triple negativo, estadio II.
   Dos consultas: la primera con laboratorio, imagenología y biomarcador
   (HER2) vinculados; la segunda **a propósito sin ningún resultado
   vinculado**, para poder probar (y demostrar en el demo) que esas
   secciones del borrador quedan marcadas como "información no
   disponible", nunca inventadas.
2. **Carlos Andrés Muñoz** — cáncer de pulmón no microcítico metastásico,
   con biomarcador EGFR positivo. Una consulta con laboratorio, imagen
   (TAC de tórax) y biomarcador vinculados.

## Cómo probarlo

```
python -m historia_clinica_mock.demo
```

Genera el borrador de nota de las tres consultas de ejemplo, mostrando en
cada caso los fragmentos disponibles y la trazabilidad resultante.

## Limitación conocida (heredada de IA-02)

El cliente de referencia (`RuleBasedLLMClient`) sigue siendo una
heurística por palabras clave, no un LLM real. Con oraciones que
contienen palabras clave de más de una sección (por ejemplo, una frase de
plan que también menciona "evaluación"), esa misma oración puede
aparecer repetida en más de una sección del borrador. No es un defecto de
`ClinicalNoteGenerator` (que sigue validando y trazando correctamente
cada cita) ni de este mock: es la limitación ya documentada del
clasificador de referencia en `docs/ia_clinica_notas.md`. Con un LLM real
esa clasificación sería más precisa.
