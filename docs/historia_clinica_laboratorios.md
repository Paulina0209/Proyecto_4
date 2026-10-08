# HC-02 — Integración de resultados de laboratorio

> Como oncólogo, quiero que los resultados de laboratorio se integren
> automáticamente al expediente, para monitorear tendencias sin pedir el dato
> al paciente o a otro sistema.

Módulo: `historia_clinica/laboratorios.py`. Configuración:
`historia_clinica/rangos_criticos_laboratorio.yaml`. Esquema: tablas
`recepcion_laboratorio`, `alertas_laboratorio` y `conflictos_laboratorio` en
`historia_clinica/schema_historia_clinica.sql`.

Los resultados se guardan en la tabla `laboratorios` del expediente, la misma
que ya leen DX, EST, IA y HC-05. Las tablas nuevas son laterales: guardan la
hora de la toma, las alertas y los conflictos sin modificar `laboratorios`.

## Vías de recepción

| Vía | Cómo entra | Procesamiento HC-02 |
|---|---|---|
| Interfaz de laboratorio (HL7 v2 ORU) | `importar_mensaje_hl7` (HC-01) o `POST /pacientes/{id}/laboratorios/hl7` | `_importar` llama a `procesar_resultados` en la misma transacción |
| FHIR | `importar_bundle_fhir` / `sincronizar_paciente` (HC-01) | Igual |
| cBioPortal | `python -m cbioportal` (pasa por HC-01) | Igual |
| Manual | `registrar_resultado_laboratorio` o `POST /pacientes/{id}/laboratorios` | En la misma transacción |

## Criterios de aceptación

| AC | Cómo se cumple | Pruebas |
|---|---|---|
| AC1: el resultado se asocia al paciente correcto y a su fecha | Doble validación (riesgo de la historia): la identificación debe ser exacta y el nombre debe coincidir (`nombres_coinciden`) antes de guardar nada. HL7 toma el nombre de PID-5 y FHIR de `Patient.name`; un mensaje con laboratorios sin nombre se rechaza. La fecha sale de OBX-14 u OBR-7, y la hora queda en `recepcion_laboratorio.fecha_hora` | `test_doble_validacion_*`, `test_hl7_con_el_id_correcto_pero_otro_nombre_se_rechaza_completo`, `test_hl7_queda_asociado_al_paciente_y_a_la_hora_de_la_toma`, `test_fhir_con_laboratorios_exige_el_nombre` |
| AC2: un valor fuera del rango crítico genera una alerta visible en el dashboard | `procesar_resultados` compara con el YAML y crea una fila en `alertas_laboratorio`. El resumen 360 la muestra con severidad alta hasta que se marca como revisada | `test_valor_critico_genera_alerta`, `test_la_alerta_sigue_activa_hasta_que_se_revisa`, `test_resultado_critico_aparece_como_alerta_en_el_360` |
| AC3: dos resultados del mismo marcador con el mismo momento no se sobrescriben; el conflicto se marca para revisión | Ambos quedan en `laboratorios` y el par se registra en `conflictos_laboratorio` (pendiente). `resolver_conflicto` deja constancia de la decisión sin borrar nada | `test_mismo_momento_y_valor_distinto_marca_conflicto_sin_sobrescribir`, `test_resolver_conflicto_conserva_ambos_resultados`, `test_conflicto_entre_dos_mensajes_hl7` |

## Reglas

- **Crítico no es lo mismo que fuera de rango.**
  - "Fuera de rango" (`alterado`) sale del rango de referencia de cada resultado.
  - "Crítico" sale del YAML y exige acción inmediata.
  - Los marcadores tumorales (CEA, CA 15-3, CA 19-9, PSA) no tienen valor crítico: se interpretan por tendencia.
- **Sin conversión de unidades.** Un resultado en una unidad distinta a la del YAML no se evalúa. Una tendencia con varias unidades se muestra en series separadas, con una advertencia.
- **Alias exactos.** "Hb", "HGB" y "Hemoglobina" son la misma prueba; "Hemoglobina glicosilada" no lo es.
- **Momento.** Si los dos resultados traen hora, se compara la hora. Si a alguno le falta, se compara el día, porque no se puede descartar que sean del mismo momento.
- **Mismo valor.** Dos resultados iguales (`4.2` y `4.20`) no son conflicto.
- **Configuración validada.** El YAML se valida al cargarlo: límites numéricos, al menos un límite por prueba y alias sin repetir. Un archivo inválido se rechaza completo.

## Tendencias

- `marcadores_de_paciente`: un resumen por marcador (cantidad y último valor).
- `tendencia_marcador`: la serie ordenada. Cada punto trae el valor numérico y las marcas `alterado`, `critico` y `en_conflicto`.
- En la API: `GET /pacientes/{id}/laboratorios/marcadores` y `GET /pacientes/{id}/laboratorios/tendencia?prueba=CEA`.

## API

| Ruta | Qué hace |
|---|---|
| `POST /pacientes/{id}/laboratorios` | Registro manual. Responde 409 si la identificación o el nombre no corresponden y 400 si los datos no son válidos |
| `POST /pacientes/{id}/laboratorios/hl7` | Mensaje ORU de la interfaz de laboratorio |
| `GET /pacientes/{id}/alertas-laboratorio`, `POST …/{alerta_id}/revisar` | Alertas críticas |
| `GET /pacientes/{id}/conflictos-laboratorio`, `POST …/{conflicto_id}/resolver` | Conflictos (`valido_a`, `valido_b`, `ambos_validos` o `ninguno_valido`) |

Un paciente de la base de `patients` entra al expediente la primera vez que
se le registra un laboratorio (`patients/expediente.py`). Las lecturas nunca
lo crean.

## Demo

`python -m patients.demo`:

- **Opción 5:** marcadores, tendencia y registro manual.
- **Opción 6:** revisar alertas y resolver conflictos.
- **Opción 4 (resumen 360):** muestra las alertas y marca los laboratorios críticos o en conflicto.

## Pruebas

```bash
python -m pytest tests/historia_clinica/test_laboratorios.py tests/patients/test_api_laboratorios_biomarcadores.py -q
```

## Fuera de alcance

- **Notificaciones** (correo, push) para valores críticos. Eso es CFG-02; aquí la alerta se ve en el 360.
- **Rangos críticos por institución desde una pantalla de configuración.** Hoy se editan en el YAML.
