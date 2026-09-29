# Demo unificada IA-01 + IA-05

La demo principal es `demo_ia01.py`. Mantiene un **paciente activo** y ofrece:

- preguntas de datos clínicos (IA-01), con trazabilidad explícita del registro fuente;
- `recomendaciones`, que muestra únicamente recomendaciones del paciente activo y su explicabilidad (IA-05);
- `cambiar`, para seleccionar otro paciente sin mezclar expedientes;
- `salir`, para terminar.

## Ejecutar

```powershell
python demo_ia01.py
```

## Flujo sugerido

Usa la base real (`data/copiloto.db`; se prepara con `python demo.py`). Los
pacientes se eligen por id interno o por su id de cBioPortal.

1. Elegir `P-0016350` (pulmón, EGFR L858R).
2. Preguntar: `¿Cuál es el EGFR?`
3. Escribir: `recomendaciones`
4. Escribir: `cambiar`
5. Elegir `P-0008538` (mama).
6. Preguntar: `¿Cuál es el CEA más reciente?`
7. Escribir: `evidencia`
8. Escribir: `salir`

Cada consulta clínica muestra el paciente consultado, repositorio, concepto, registro, ID exacto y fecha. Las recomendaciones se construyen solo con hallazgos del paciente activo y muestran datos usados, evidencia/guía, confianza cualitativa, datos faltantes y limitaciones.
