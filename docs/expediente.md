# Expediente clínico oncológico (`expediente/`)

## Qué es

`expediente/` es el esquema SQLite y las lecturas del expediente clínico
que usan DX, EST, TX, IA, HC-05 y DOC. Antes se llamaba
`historia_clinica_mock` y traía datos inventados; ya no trae datos:

- **Datos reales:** pacientes desidentificados de cBioPortal (MSK-CHORD)
  cargados en `data/copiloto.db` con `python -m cbioportal` o al correr
  `python demo.py` (ver `docs/cbioportal.md`). La ruta se cambia con
  `COPILOTO_EXPEDIENTE_DB` (`historia_clinica.db.conectar_expediente`).
- **Lo que documenta el oncólogo** (notas de consulta, T/N/M, entorno de
  la enfermedad, línea de tratamiento, comorbilidades): `expediente/registro.py`.
- **Pruebas automáticas:** usan pacientes sintéticos propios en
  `tests/datos_sinteticos.py`; nunca tocan la base real.

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
en general. Es la forma concreta en que este expediente cumple la observación
técnica de IA-02 sobre conservar trazabilidad entrada → borrador.

## Registro por el oncólogo (`registro.py`)

cBioPortal no trae notas de consulta ni variables que requieren juicio
clínico. `registrar_consulta`, `registrar_datos_clinicos` y
`registrar_comorbilidad` las agregan como filas nuevas con su fecha (nada
se sobrescribe; los lectores toman el valor más reciente de cada variable).

## Hallazgos de todo el paciente (`adapters.obtener_hallazgos_de_paciente`)

Reúne consultas, laboratorios, imágenes, biomarcadores y, si existen, los
antecedentes importados por HC-01 (tratamientos, cirugías, radioterapia,
diagnósticos previos). Es la entrada de DX-02, IA-04 e IA-05.

## Cómo probarlo

```
pytest tests/expediente -v
python demo.py --solo ia     # sobre pacientes reales
```

## Limitación conocida (heredada de IA-02)

El cliente de referencia (`RuleBasedLLMClient`) sigue siendo una
heurística por palabras clave, no un LLM real. Con oraciones que
contienen palabras clave de más de una sección (por ejemplo, una frase de
plan que también menciona "evaluación"), esa misma oración puede
aparecer repetida en más de una sección del borrador. No es un defecto de
`ClinicalNoteGenerator` (que sigue validando y trazando correctamente
cada cita) ni de este expediente: es la limitación ya documentada del
clasificador de referencia en `docs/ia_clinica_notas.md`. Con un LLM real
esa clasificación sería más precisa.
