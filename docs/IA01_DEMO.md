# IA-01 — Consulta de datos clínicos en lenguaje natural

## Objetivo del MVP

Implementar los criterios de aceptación de la HU #10 con datos clínicos sintéticos y trazables.

## Flujo

```text
Pregunta en lenguaje natural
        ↓
Identificación del concepto clínico
        ↓
Recuperación desde el expediente del paciente activo
        ↓
Selección cronológica del registro más reciente
        ↓
Respuesta controlada con valor + fecha + fuente + source_id
```

La recuperación ocurre antes de construir la respuesta. El sistema no usa conocimiento generativo para completar valores clínicos ausentes.

## Ejecutar pruebas de IA-01

```bash
python -m pytest tests/clinical_query -v
```

## Ejecutar demostración

```bash
python demo_ia01.py
```

Preguntas sugeridas:

```text
¿Cuál fue el último CA-125?
¿Cuál es la hemoglobina?
¿Cuál es la creatinina más reciente?
¿Cuál es el último PSA?
¿Cómo está el paciente?
```

## Decisiones de diseño

- Los datos de demostración son sintéticos y usan un identificador pseudonimizado.
- Todo `ClinicalDatum` obliga a conservar fecha, fuente y `source_id`.
- `ClinicalRepository` desacopla la lógica de consulta de la fuente de datos.
- El adaptador actual usa JSON; puede sustituirse posteriormente por una base clínica, FHIR u otra fuente estructurada.
- La interpretación lingüística del MVP es determinista. Un componente NLU/LLM puede reemplazarla más adelante sin convertirse en la fuente de los valores clínicos.
