# EV-01 — Consulta de evidencia sin salir de la plataforma

## Alcance del MVP

EV-01 incorpora un buscador local sobre el catálogo de guías versionadas incluidas en `guidelines/*/metadata.yaml`.

La demo unificada agrega dos usos:

- `evidencia`: busca evidencia relevante al contexto del paciente activo.
- `evidencia <texto>`: realiza una búsqueda libre, por ejemplo `evidencia EGFR NSCLC metastatic`.

Cada resultado muestra título, organización, fecha de publicación cuando está registrada, DOI, módulo, ruta local, estado de validación y estado de licenciamiento.

El MVP no descarga ni reproduce contenido íntegro de journals o guías. Esto mantiene el alcance coherente con el riesgo de licenciamiento descrito en EV-01.

## Seguridad y trazabilidad

- No se inventan referencias cuando no existe coincidencia.
- La búsqueda por paciente usa únicamente el contexto del paciente activo.
- Los resultados apuntan a un `metadata.yaml` versionado del repositorio.
- Si una fecha o estado no está registrado en el catálogo, se informa como no registrado en vez de inferirlo.

## Ejecutar

```powershell
python demo_ia01.py
```

Ejemplo:

```text
Seleccione paciente por ID > 2
Oncólogo > evidencia
Oncólogo > evidencia EGFR NSCLC metastatic
```

## Pruebas

```powershell
python -m pytest tests/evidencia_clinica -q
```
