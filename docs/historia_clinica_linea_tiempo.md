# HC-06 — Línea de tiempo cronológica del paciente

> Como oncólogo, quiero ver una línea de tiempo cronológica de eventos clínicos del paciente, para
> entender la evolución del caso de un vistazo.

Módulo: `historia_clinica/linea_tiempo.py`. API: `GET /pacientes/{id}/linea-tiempo` en `patients.api`.
Interfaz: **Expediente › Línea de tiempo** (la pasarela la detecta sola, ver `frontend/extensiones.py`).

## De dónde salen los eventos

No guarda nada: es una vista sobre lo ya registrado (HC-01, HC-02, HC-03, HC-04 e importaciones).

| Tipo (`tipo`) | Fuente |
|---|---|
| `diagnostico` | diagnósticos de la ficha; episodios diagnósticos (HC-04); antecedentes externos de tipo condición |
| `biopsia`, `biomarcador` | HC-04 |
| `estudio_imagen` | informes de imagen; estudios del PACS sin informe (HC-03); estudios de acceso rápido del 360 |
| `laboratorio` | HC-02, **un evento por día** (lo crítico y lo fuera de rango se nombran primero) |
| `tratamiento` | tratamientos de la ficha; antecedentes externos de tipo medicación |
| `procedimiento` | antecedentes externos de tipo procedimiento (cirugías, radioterapia) |
| `consulta` | consultas de la ficha y notas de consulta del expediente |

Lo mismo visto desde dos lugares no se repite: si coinciden tipo y fecha, el informe de imagen gana al
estudio del PACS y al de acceso rápido, y el diagnóstico de la ficha al episodio y al antecedente externo.

## Criterios de aceptación

- **Orden y filtro (AC1).** Del más antiguo al más reciente. `?tipo=consulta` (se puede repetir) filtra
  en el servidor; un tipo desconocido responde 400. La interfaz filtra con un desplegable que muestra
  cuántos eventos hay de cada tipo.
- **Fecha aproximada (AC2).** Una fecha guardada como `AAAA-MM` o `AAAA` (habitual en antecedentes FHIR)
  llega con `precision: "mes" | "anio"` y `fecha_aproximada: true`. La interfaz lo dice en texto
  («mayo de 2019 (fecha aproximada: solo mes y año)») y además con borde punteado. Un evento sin fecha
  legible va al final como «Fecha desconocida»: no se le inventa una.

Leer la línea de tiempo no crea el expediente y queda en la auditoría (AUD-01, `detalle = linea_tiempo`).

## Pruebas

```
python -m pytest tests/historia_clinica/test_linea_tiempo.py tests/patients/test_api_linea_tiempo_notificaciones.py tests/frontend/test_linea_tiempo_notificaciones.py -q
```
