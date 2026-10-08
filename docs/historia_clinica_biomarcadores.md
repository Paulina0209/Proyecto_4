# HC-04 — Integración de biopsias y biomarcadores

> Como oncólogo, quiero integrar resultados de biopsias y biomarcadores, para
> contar con la información molecular relevante al decidir tratamiento.

Módulo: `historia_clinica/biopsias_biomarcadores.py`. Catálogo:
`historia_clinica/catalogo_biomarcadores.yaml`. Esquema: tablas
`episodios_diagnosticos`, `biopsias` y `detalle_biomarcador` en
`historia_clinica/schema_historia_clinica.sql`.

Cada biomarcador ocupa dos filas:

- **En `biomarcadores`:** un texto legible, por ejemplo "detectada: L858R (NGS)". Es lo que ya leen HC-05, DX e IA, así que no cambian.
- **En `detalle_biomarcador`:** el dato validado (estado, variante, valor y método) y su relevancia para el tratamiento.

## Criterios de aceptación

| AC | Cómo se cumple | Pruebas |
|---|---|---|
| AC1: la biopsia queda vinculada a su episodio diagnóstico | `registrar_biopsia` exige un episodio del paciente. Si tiene uno solo, se vincula a ese; con cero o con varios hay que indicarlo (fail-closed) | `test_con_un_solo_episodio_la_biopsia_se_vincula_sola`, `test_con_varios_episodios_hay_que_indicar_cual`, `test_sin_episodio_no_se_puede_registrar_la_biopsia` |
| AC2: un biomarcador relevante para una terapia dirigida disponible se destaca como información clave (insumo de TX-01) | `clasificar` aplica las reglas del catálogo según el tipo de cáncer. Un accionable queda `accionable_confirmado`: aparece en `biomarcadores_clave`, en el 360 ("Biomarcadores clave") y en la herramienta `obtener_datos_paciente` de TX-01. Además, su variable (`egfr_status`, `alk_status`, `her2_status`, `braf_v600_status`, `er_status`, `pr_status` o `pdl1_tps`) se escribe en `datos_clinicos_estructurados`, que es lo que lee TX-01 | `test_egfr_sensibilizante_se_destaca_y_llega_a_tx`, `test_pdl1_tps_pasa_su_valor_a_tx`, `test_biomarcador_confirmado_llega_como_fact_y_como_clave` |

## Riesgo: biomarcador mal registrado

Un resultado invertido (positivo por negativo) puede llevar a un tratamiento
equivocado. Por eso la validación es estricta (`_validar`):

- **Sin texto libre.** Solo se aceptan los estados del formato del biomarcador:
  - `alteracion`: detectada / no_detectada / no_concluyente;
  - `reordenamiento`: reordenado / no_reordenado / no_concluyente;
  - `ihc_her2`: positivo / negativo / equivoco / no_concluyente;
  - `receptor`: positivo / negativo / no_concluyente;
  - `porcentaje`: cuantificado / no_concluyente.
- **Métodos del catálogo.** Solo se aceptan los métodos definidos para cada biomarcador (NGS, PCR, IHC, FISH, 22C3…).
- **Coherencia interna.**
  - HER2 IHC 3+ es positivo; IHC 0 o 1+ es negativo; IHC 2+ depende del ISH, y sin ISH es equívoco.
  - Un receptor con 1 % o más de células teñidas es positivo.
  - PD-L1 TPS debe estar entre 0 y 100.
  - Una alteración detectada exige la variante.
- **Doble ingreso.** `confirmacion` debe repetir el resultado clave (el estado, o el valor en PD-L1).
- **Todos los errores juntos.** Se reportan todos a la vez (`ErrorBiomarcador.errores`), y no se guarda nada.

Además, el resultado solo se considera accionable si el tipo de cáncer del
episodio (o el último `cancer_type` del expediente) está entre los del catálogo.
Sin tipo de cáncer conocido, el resultado queda `informativo`.

Un resultado negativo también escribe su variable (por ejemplo, EGFR no
detectada → `egfr_status=wild_type`), porque es igual de decisivo para TX-01.

## Biomarcadores importados (cBioPortal)

El mapeo de cBioPortal guarda las variantes como hechos ("mutación detectada:
L858R") y nunca como "positivo". HC-04 mantiene esa regla:

1. **Vinculación.** `cbioportal.importador.vincular_biopsias` crea:
   - el episodio, a partir del diagnóstico primario; si hay más de un primario, no crea nada;
   - una biopsia por cada muestra secuenciada;
   - el vínculo entre cada biomarcador "— muestra X" y su biopsia.
2. **Pendientes.** `marcar_potencialmente_accionables` destaca las variantes que el catálogo considera accionables como `pendiente_confirmacion`, **sin** escribir la variable de TX. Ejemplos: EGFR L858R, la deleción del exón 19, KRAS G12C, fusiones de ALK/ROS1/RET/NTRK y HER2 "positivo".
3. **Confirmación.** El oncólogo confirma (`confirmar_biomarcador`, repitiendo el estado) o descarta (`descartar_biomarcador`). Solo al confirmar se escribe la variable de TX.

Una variante que no está en el catálogo (por ejemplo, EGFR V834L) no se
destaca. Una fusión catalogada como "antisense" se destaca, pero solo como
pendiente: el oncólogo decide si es funcional.

## Catálogo

`catalogo_biomarcadores.yaml` define, por biomarcador:

- alias;
- formato;
- tipos de cáncer;
- métodos;
- reglas accionables (patrones de variante, terapia y variable/valor de TX);
- `otros_tx`, para los estados no positivos.

Al cargarlo, cada `variable_tx`/`valor_tx` se valida contra
`guidelines/*/variables.yaml`. Así el catálogo no puede apuntar a una variable
o un valor que TX-01 no entiende
(`test_catalogo_que_apunta_a_algo_que_tx_no_entiende_se_rechaza`).

## API

| Ruta | Qué hace |
|---|---|
| `POST`/`GET /pacientes/{id}/episodios` | Episodios diagnósticos |
| `POST`/`GET /pacientes/{id}/biopsias` | Biopsias (AC1) |
| `POST /pacientes/{id}/biomarcadores` | Registro validado; responde 400 con todos los errores |
| `GET /pacientes/{id}/biomarcadores?solo_clave=true` | Información clave (AC2) |
| `POST …/biomarcadores/{bid}/confirmar`, `POST …/descartar` | Revisión de los pendientes |

El resumen 360 incluye `biomarcadores_clave`, y una alerta "biomarcador por
confirmar" por cada pendiente.

## Demo

- `python -m patients.demo`, opción 7: registrar episodio y biopsia, registrar un biomarcador, y confirmar o descartar pendientes.
- El 360 (opción 4) muestra la sección "BIOMARCADORES CLAVE".

## Pruebas

```bash
python -m pytest tests/historia_clinica/test_biopsias_biomarcadores.py tests/cbioportal/test_vinculacion_hc04.py \
    tests/tx_clinica/test_biomarcadores_clave_tool.py -q
```

## Fuera de alcance

- **`molecular_pathway_status` y `actionable_driver_names`** (los usa la guía de NSCLC con driver oncogénico). Siguen siendo juicio del oncólogo: un panel completo sin drivers no se deriva automáticamente.
- **Anotación automática de variantes** (OncoKB, ClinVar). El catálogo es una lista curada y revisable.
