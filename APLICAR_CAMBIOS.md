# Fix del motor de reglas del Proyecto_4

Este paquete pertenece **solo al proyecto de clase** `Proyecto_4 / copilot_clínico`.
No requiere ni modifica `cdss_pembrolizumab` ni ningún archivo del trabajo de grado.

## Cambios

- Agrega `core/engine.py`, motor genérico de evaluación de reglas YAML.
- Agrega `core/__init__.py`.
- Corrige en los tests de guías el import heredado `cdss.core.engine` por `core.engine`.
- Corrige rutas heredadas `src/cdss/guidelines/...` por `guidelines/...`.
- Corrige rutas heredadas `tests/unit/guidelines/cases/...` por `tests/guidelines/cases/...`.

## Validación realizada

- `python -m pytest tests/guidelines -q` -> **236 passed**.
- Con IA-01 integrada: `python -m pytest tests/guidelines tests/clinical_query -q` -> **242 passed**.

## Aplicación

Copiar el contenido de este ZIP sobre la raíz de `copilot_clínico`.
Los archivos bajo `tests/guidelines/` reemplazan únicamente los tests indicados; no modifican YAML clínicos ni documentación de guías.

Después ejecutar:

```powershell
python -m pytest tests/guidelines -q
python -m pytest tests/clinical_query -q
python -m pytest -q
```
