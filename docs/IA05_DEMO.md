# IA-05 — Explicabilidad de recomendaciones

## Ejecutar pruebas

```powershell
python -m pytest tests/ia_clinica/explainability -q
```

Resultado esperado:

```text
8 passed
```

## Ejecutar demo

```powershell
python -m ia_clinica.explainability.demo
```

La demo muestra dos escenarios:

1. **María:** recomendación con datos clínicos trazables y guía ESMO versionada. Como el módulo de guía conserva `clinical_validation_status: pending`, el sistema muestra confianza `LOW` y explica la limitación en vez de presentarla con falsa seguridad.
2. **Carlos:** candidato con un hallazgo clínico real pero sin una guía/evidencia asociada. IA-05 devuelve `NOT_EVALUABLE`, identifica el criterio faltante y declara explícitamente que no existe evidencia registrada.

## Qué significa el nivel de confianza

`HIGH`, `MEDIUM`, `LOW` y `NOT_EVALUABLE` son categorías cualitativas derivadas de trazabilidad, disponibilidad/estado de evidencia y datos faltantes. **No son probabilidades clínicas** y el sistema no genera porcentajes de confianza.

## Arquitectura

```text
Salida clínica (DX-02; después EST/TX)
              |
              v
      ExplanationService
       /       |       \
      v        v        v
Datos HC   Evidencia   Faltantes
trazables  versionada  / límites
      \        |        /
       \       |       /
        v      v      v
      ClinicalExplanation
              |
              v
recomendación + razonamiento + fuentes + confianza + incertidumbre
```

El adaptador implementado en esta HU consume hoy `DX-02`, pero el contrato `ExplanationService.build(...)` es transversal y puede ser reutilizado posteriormente por estadificación y tratamiento sin duplicar la lógica de explicabilidad.
