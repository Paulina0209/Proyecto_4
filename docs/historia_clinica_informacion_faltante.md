# HC-05 — Detección de información faltante

> Como oncólogo, quiero que el sistema me indique qué información clínica falta
> para tomar una decisión (diagnóstico, estadificación o tratamiento), para no
> avanzar con datos incompletos.

Módulo: `historia_clinica/informacion_faltante.py`. Checklist por defecto:
`historia_clinica/checklists_informacion.yaml`.

## Uso

```python
from historia_clinica.informacion_faltante import evaluar_informacion_faltante

evaluacion = evaluar_informacion_faltante(conn, paciente_id, fases=["diagnostico"])
if evaluacion.mostrar_alerta:
    print(evaluacion.alerta)          # qué falta y por qué
for item in evaluacion.faltantes:     # id, descripcion, motivo, valor_registrado, fuente
    ...
```

- Por defecto se evalúan las tres fases: `diagnostico`, `estadificacion` y `tratamiento`.
- El tipo de cáncer sale de la variable `cancer_type` del expediente. Para un
  caso **sospechado** se puede pasar con `tipo_cancer="cáncer de mama"`, y se
  resuelve con los alias del checklist.
- `checklists=cargar_checklists(ruta)` permite usar el checklist propio de la institución.

## Checklist configurable

Cada tipo de cáncer define ítems. Cada ítem indica en qué fases aplica y qué
evidencias del expediente lo satisfacen; basta con que **una** tenga un valor
concluyente:

| Evidencia | Se busca en |
|---|---|
| `variable: er_status` | último valor en `datos_clinicos_estructurados` |
| `biomarcador: [re, er, ...]` | filas de `biomarcadores` cuyo nombre coincide con un alias (se usa la más reciente) |
| `imagen: [mama]` | `imagenologia`, filtrada por región |
| `laboratorio: [...]` | `laboratorios`, por nombre de prueba |

Valores como `unknown`, `pending`, `equivocal`, "pendiente", "equívoco" o
"indeterminado" **no** cuentan como presentes. El ítem se reporta como
`valor no concluyente`, con el valor y la fila de origen.

El checklist se valida al cargarlo. Un ítem sin evidencias o con una fase
inexistente se rechaza, porque de lo contrario fallaría en silencio.

El contenido incluido (mama, NSCLC, melanoma, carcinoma renal) es ilustrativo y
usa el mismo vocabulario de variables que `guidelines/*/variables.yaml`. Cada
institución debe revisarlo con su comité clínico.

## Criterios de aceptación

| AC | Resultado | Pruebas |
|---|---|---|
| AC1: sospecha de cáncer de mama → indica si faltan receptores hormonales o HER2 | `INCOMPLETA`, con cada ítem faltante y su motivo | `test_mama_sin_receptores_hormonales_ni_her2_los_reporta_como_faltantes`, `test_paciente_sembrada_con_her2_pero_sin_receptores` |
| AC2: con toda la información disponible, no se muestra alerta | `COMPLETA`, con `mostrar_alerta == False` y `alerta is None` | `test_expediente_completo_no_muestra_alerta` |
| AC3: sin checklist para el tipo de cáncer, se indica que no se puede evaluar | `NO_EVALUABLE`, con una alerta explícita ("esto no significa que la información esté completa") | `test_tipo_de_cancer_sin_checklist_es_no_evaluable_y_alerta` |

## Riesgo clínico: un falso "completo"

La evaluación es *fail-closed*. Solo se devuelve `COMPLETA` cuando existe un
checklist para ese cáncer y esa fase, y todos sus ítems tienen un valor
concluyente. Cualquier otra situación genera alerta: tipo de cáncer
desconocido, fase sin ítems o valor no interpretable.

## Relación con otras historias

- Lee los datos que cargan HC-01 (integración externa), HC-02 (laboratorios) y
  HC-04 (biomarcadores), pero no depende de su implementación: consulta las
  tablas del expediente.
- EST-03 (`estadificacion/incompleta.py`) detalla, **dentro** de la fase de
  estadificación, qué componente T/N/M falta y qué rango de estadios es posible.
  HC-05 es la vista transversal de las tres fases.
- Es insumo natural de DX-01 (recomendación de estudios), que depende de HC-05
  en el backlog.
