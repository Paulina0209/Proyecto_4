# NFR-01 — Rendimiento y tiempos de respuesta

> Como usuario del sistema, quiero tiempos de respuesta bajos (consultas < 2 s,
> generación de notas < 10 s), para que la herramienta no interrumpa mi flujo de
> consulta.

La historia no traía criterios de aceptación. Siguiendo la recomendación del
backlog (tratar las NFR como historias técnicas con una métrica que se pueda
verificar), se definieron estos:

```
AC1  Dado 10 médicos consultando a la vez sobre la base real (13.159 pacientes)
     Cuando abren expedientes (ficha, resumen 360, laboratorios) o hacen preguntas (IA-01)
     Entonces el 95 % responde en menos de 2 s y ninguna petición falla

AC2  Dado que se pide un borrador de nota (IA-02) o un resumen (IA-04)
     Cuando el modelo de lenguaje tarda o falla
     Entonces el borrador llega igual en menos de 10 s

AC3  Cada petición se mide y el tiempo queda visible por ruta, para detectar regresiones
```

## Lo que se encontró al medir

| Medición | Antes | Después |
|---|---|---|
| 10 médicos a la vez sobre la API | **80 % de errores 500** (SQLite usado entre hilos), 52 pet/s | 0 errores, p95 ≈ 50 ms, ≈ 300 pet/s |
| 25 médicos a la vez | 85 % de errores | 0 errores, p95 ≈ 100 ms, ≈ 370 pet/s |
| Abrir un paciente de cBioPortal por primera vez | 2,6 a 5 s (descarga por internet) | se puede apagar: `COPILOTO_DETALLE_BAJO_DEMANDA=0` |
| Preguntas IA-01 | ≈ 250 ms | igual |
| Nota SOAP con GPT (`gpt-6-luna`) | 4 a 7 s, sin tope (120 s de espera y 2 reintentos) | tope de 8 s para el modelo y respaldo por reglas: siempre < 10 s |
| Resumen para junta con GPT | 5 a 8 s, sin tope | igual que la nota |

## Qué se hizo

- **Concurrencia en SQLite** (`operacion/sqlite.py`). La conexión de cada
  petición se puede usar en el hilo del endpoint (`check_same_thread=False`), y
  las bases en archivo usan WAL (leer no espera a una escritura) y
  `busy_timeout` de 5 s (una escritura espera a otra en vez de fallar). Se
  aplica en `patients/db.conectar` y en `historia_clinica.db.conectar_expediente`.
- **Presupuesto para el modelo** (`operacion/presupuesto.py`).
  `LLMConPresupuesto` le da 8 s a GPT, sin reintentos. Si no responde a tiempo,
  usa el cliente por reglas, que es igual de trazable porque el generador valida
  cada sección contra la consulta. `ultimo_uso` dice qué respondió y por qué.
- **Medición de cada petición** (`operacion/latencia.py`).
  `MedicionLatenciaMiddleware` agrega `Server-Timing` a cada respuesta y guarda
  el p50 y el p95 por plantilla de ruta (`/pacientes/{paciente_id}`, nunca el
  id), que se publican en `/salud/metricas`. Está en `patients.api` y en la
  pasarela web.
- **Detalle de cBioPortal bajo demanda, configurable.** `COPILOTO_DETALLE_BAJO_DEMANDA=0`
  lo apaga cuando los datos ya están cargados en el expediente.

## Herramientas

```powershell
python -m operacion.carga                         # prueba de carga: 1, 10 y 25 médicos (servidor TLS sobre una copia)
python -m operacion.carga --usuarios 50 --workers 2
python -m operacion.rendimiento                   # IA-01, nota y resumen con GPT sobre P-0016350
```

Las dos trabajan sobre una copia de la base real y devuelven código 1 si algún
objetivo no se cumple.

## Fuera del alcance

El agente de tratamiento (TX) razona en varios pasos con GPT y usa
herramientas. Una respuesta suya no es una "consulta" de las de menos de 2 s, y
no se le aplicó el presupuesto, porque cortarlo a mitad de un razonamiento
dejaría una recomendación incompleta.

## Pruebas y demo

```powershell
python -m pytest tests/operacion/test_rendimiento.py -q
python demo_operacion.py --solo nfr01
```
