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
python demo.py --solo ia
```

Demo unificada sobre pacientes reales de cbioportal; ver `docs/demo_unificada.md`. Muestra la recomendación explicable de un paciente real con progresión por imagen: el criterio sustentado con el hallazgo exacto, los criterios faltantes y la confianza `NOT_EVALUABLE` cuando no hay guía asociada.

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
