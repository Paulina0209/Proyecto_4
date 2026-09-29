# Base de datos real con cBioPortal

El copiloto deja de depender solo de los pacientes sintéticos de
`expediente/seed.py`. El paquete `cbioportal/` importa pacientes
reales y desidentificados de estudios públicos de
[cBioPortal](https://www.cbioportal.org) al mismo expediente SQLite que ya
leen DX, EST, TX, IA y HC-05. Si se indica, también los crea en la base del
módulo de pacientes, para que aparezcan en la búsqueda (PAC-02) y en el
dashboard 360 (PAC-03).

## Dos formas de cargar

| | Modo índice (recomendado para la demo) | Modo completo |
|---|---|---|
| Qué trae | Todos los pacientes del estudio con datos básicos (sexo, edad, diagnóstico). El detalle se trae al abrir cada paciente | Todo el detalle de cada paciente, de una vez |
| Volumen | 13.159 pacientes de mama y pulmón en **4 s** (medido) | ~5 s por paciente: sirve para decenas o cientos |
| Búsqueda (PAC-02) | Sobre todos los pacientes: 56–114 ms con 13.159 (medido) | Sobre los importados |
| Abrir un paciente | 1ª vez ~5,5 s (trae el detalle); después, ~10 ms | Siempre local |
| Sin internet | Buscar sí; abrir un paciente nuevo no (se muestran sus datos básicos) | Todo |

Se pueden combinar: índice para todos y modo completo para precargar los
pacientes que se van a mostrar en la demo (así se abren al instante).

### Modo índice

```bash
# 1. Índice de todos los pacientes de mama y pulmón (o --tipos todos)
python -m cbioportal --indice --db data/copiloto.db --fecha-referencia 2026-09-29 \
    --db-pacientes patients/db/pacientes.db --oncologo-id 1

# 2. (Opcional) precargar los pacientes de la demo
python -m cbioportal --db data/copiloto.db --pacientes P-0000015 P-0002266 \
    --db-pacientes patients/db/pacientes.db --oncologo-id 1

# 3. Levantar la API con la carga bajo demanda activada
COPILOTO_EXPEDIENTE_DB=data/copiloto.db uvicorn patients.api:app
```

Cómo funciona (`cbioportal/indice.py`):

1. **Índice.** Dos llamadas masivas a la API (atributos de paciente y de
   muestra de todo el estudio) y una inserción en lote en ambas bases. No
   hace ninguna llamada por paciente.
2. **Detalle bajo demanda.** `GET /pacientes/{id}` y `GET
   /pacientes/{id}/resumen-360` llaman a `CargadorDetalle.asegurar_detalle`.
   Si el paciente es del índice y todavía no tiene detalle, lo trae con el
   importador de siempre (camino de HC-01) y completa su 360. Hay un candado
   por paciente, así que dos pestañas abriendo al mismo paciente no lo
   importan dos veces.
3. **Si cBioPortal falla,** el 360 responde igual con los datos del índice,
   el fallo queda en `sincronizaciones_externas` y se reintenta la próxima
   vez que se abra. Al haber un médico esperando, se usa un timeout de 20 s
   y un solo reintento.
4. **Solo se carga el detalle de pacientes del propio oncólogo:** primero se
   verifica el acceso y después se llama a la API.
5. **La fecha de referencia del índice se guarda** en `indices_cbioportal`.
   El detalle que se cargue días después usa la misma, así las fechas son
   coherentes. Re-ejecutar el índice solo agrega pacientes que falten y
   conserva la fecha original.

Sin la variable `COPILOTO_EXPEDIENTE_DB`, la API funciona exactamente como
antes.

### Modo completo

```bash
# 25 pacientes de mama y 25 de pulmón no microcítico de MSK-CHORD
python -m cbioportal --db data/copiloto.db --fecha-referencia 2026-09-29

# Pacientes puntuales, y también en la base de búsqueda/360
python -m cbioportal --db data/copiloto.db --pacientes P-0000015 P-0002266 \
    --fecha-referencia 2026-09-29 \
    --db-pacientes patients/db/pacientes.db --oncologo-id 1
```

| Opción | Por defecto | Para qué |
|---|---|---|
| `--db` | `data/copiloto.db` | Expediente clínico (esquema de `historia_clinica`). |
| `--estudio` | `msk_chord_2024` | Cualquier estudio público de cBioPortal. |
| `--pacientes` | — | Ids del estudio. Sin esta opción, se eligen por tipo de cáncer. |
| `--indice` | — | Modo índice (requiere `--db-pacientes` y `--oncologo-id`). |
| `--tipos` / `--por-tipo` | mama y NSCLC / 25 (sin tope en modo índice) | Selección reproducible: los primeros N por id. En modo índice, `--tipos todos` trae el estudio completo. |
| `--fecha-referencia` | hoy | Fecha en la que cae el último evento de cada paciente (ver *Fechas*). |
| `--db-pacientes` + `--oncologo-id` | — | Crea también los pacientes en `patients/db`. |
| `--url` | API pública | Instancia institucional de cBioPortal; el token va en `CBIOPORTAL_TOKEN`. |

Re-ejecutar el comando es seguro. Por la idempotencia de HC-01, solo se
agregan los registros nuevos.

Desde código:

```python
from datetime import date
from historia_clinica.db import crear_conexion
from cbioportal import FuenteCBioPortal, importar_paciente

conn = crear_conexion("data/copiloto.db")
fuente = FuenteCBioPortal(fecha_referencia=date(2026, 9, 29))
resultado = importar_paciente(conn, fuente, "msk_chord_2024", "P-0000015")
```

Como `FuenteCBioPortal` cumple el protocolo de HC-01, sirve también con
`historia_clinica.integracion_externa.sincronizar_paciente` para
re-sincronizar a un paciente que ya existe.

## Por qué MSK-CHORD

`msk_chord_2024` (MSK, *Nature* 2024) tiene unos 25.000 pacientes de mama,
pulmón no microcítico, colorrectal, próstata y páncreas. Además de la
genómica, trae la línea de tiempo clínica (tratamientos, marcadores
tumorales, ECOG, diagnóstico del registro de tumores), HER2, receptores
hormonales, PD-L1 y hallazgos de radiología. Es de los pocos estudios
públicos con datos suficientes para los módulos clínicos del copiloto. Los
estudios TCGA también funcionan, pero traen menos información clínica.

## Qué se importa y a dónde

| cBioPortal | Expediente | Notas |
|---|---|---|
| Paciente (sexo, edad) | `pacientes` | Identificación `CBIO:<estudio>:<paciente>`. El nombre es el id, porque no hay nombres. |
| Tipo de cáncer de la muestra | `datos_clinicos_estructurados.cancer_type` | `breast`, `NSCLC`, …; los demás tipos conservan su nombre original. |
| Diagnóstico primario (registro de tumores) | `pacientes.estadio`, `ajcc_stage_at_diagnosis`, antecedente `condicion` | AJCC al diagnóstico. |
| HER2 / HR (solo positivos) | `her2_status`, `hormone_receptor_status`, biomarcadores | Ver reglas. |
| ECOG | `ecog_ps` | El más reciente. |
| Marcadores tumorales (CEA, CA 15-3, CA 19-9, PSA) | `laboratorios` | Con rango de referencia y `alterado`. |
| Radiología (NLP) | `imagenologia` | Un estudio por día y modalidad. Redactado para la detección de negación de DX-02 ("Progresión detectada" / "Sin progresión"). |
| Tratamientos, radioterapia, cirugía | `antecedentes_externos` | Con fechas de inicio y fin. |
| Mutaciones y fusiones de genes clave | `biomarcadores` | Genes según el tipo de cáncer (`mapeo.GENES_POR_TIPO`). |
| MSI, TMB | `biomarcadores` | Por muestra. |
| PD-L1 positivo/negativo | `pdl1_positive_without_tps` | Ver reglas. |
| Estado vital, tabaquismo (predicción) | `vital_status`, `smoking_status_nlp_prediction` | |

Cada fila queda en `registros_importados` con su identificador de origen.
Cada importación deja una fila en `sincronizaciones_externas` con
`formato = 'cbioportal'`.

## Reglas clínicas (fail-closed)

Siguen el mismo principio que HC-05: un falso "completo" es peor que un
dato faltante.

- **No se deriva nada que requiera juicio clínico.** `disease_setting`, las
  categorías T/N/M, `molecular_pathway_status` y `smoking_status` no se
  llenan. HC-05 los muestra como faltantes y el oncólogo los completa.
- **Las variantes se guardan como hechos, nunca como "positivo".** Por
  ejemplo, "mutación detectada: L858R (Missense_Mutation)" o "fusión
  detectada: EML4-ALK". No toda variante en EGFR o RET es un driver
  accionable; hay variantes de significado incierto.
- **"No detectada" solo para genes que el panel de la muestra cubre.** Si
  no se conoce el panel, solo se guardan los hallazgos.
- **HR y HER2 solo cuando son positivos.** En MSK-CHORD son "antecedente
  de un resultado positivo": un "No" significa que no se encontró un
  positivo, no un negativo confirmado (hay pacientes con "No" tratadas con
  trastuzumab u hormonoterapia). "No" queda faltante y nunca se deriva
  "triple negativo". Con HR positivo tampoco se sabe si es RE o RP, así que
  RE/RP quedan faltantes.
- **ERBB2 no se consulta en mama.** Su nombre coincide con el ítem HER2 de
  HC-05, y "sin mutación en ERBB2" no equivale al estado HER2 por IHC/ISH.
- **PD-L1 binario no cumple el ítem de TPS.** Por eso no se guarda como
  biomarcador `PD-L1`: la elección de inmunoterapia depende del porcentaje.
- **Pacientes con muestras de más de un tipo de cáncer.** No se registra
  `cancer_type`, y HC-05 dice que no puede evaluar la completitud.
  Tampoco se toma estadio si hay más de un diagnóstico primario.
- **Radiología.** Los hallazgos vienen de NLP sobre informes, no del
  informe original, y el texto guardado lo dice.
- **Rangos de laboratorio.** `mapeo.RANGOS_LABORATORIO` tiene límites
  habituales en adultos. Son ilustrativos: cada institución debe poner los
  de su laboratorio.

## Fechas

cBioPortal está desidentificado y publica días relativos, no fechas. El
importador ubica al paciente en el calendario de forma que su último evento
cae en `--fecha-referencia`. Los intervalos entre eventos son reales; las
fechas absolutas no. La fecha de nacimiento es aproximada (1 de enero del
año que da la edad). Conviene fijar `--fecha-referencia` para que dos
importaciones den las mismas fechas.

## Módulo de pacientes (PAC-02 / PAC-03)

`--db-pacientes` crea al paciente en `patients/db` con tipo de
identificación `externo`, junto con su diagnóstico, un tratamiento por
fármaco y sus estudios de laboratorio e imagen. Un tratamiento queda
`en_tratamiento` si terminó a menos de 30 días del último evento y el
paciente no falleció; los demás quedan `finalizado`.

Si el paciente ya existe en esa base, no se modifica. El oncólogo pudo
haber agregado datos a mano, y esa base no guarda de dónde viene cada fila.
El expediente de `historia_clinica` sí se actualiza en cada importación.

## Limitaciones

- No hay consultas ni notas clínicas: cBioPortal no las publica. IA-02
  necesita una consulta registrada.
- No hay comorbilidades, así que TX no tiene datos de contraindicaciones
  de inmunoterapia.
- Las dos bases (`historia_clinica` y `patients/db`) siguen separadas. El
  importador llena ambas, pero unificarlas es un trabajo aparte.
- Son datos de investigación de MSK: sirven para desarrollar y demostrar,
  no para atender pacientes.
- En modo índice, un paciente sin detalle todavía no tiene `cancer_type`
  en el expediente: HC-05 lo reporta como no evaluable hasta que se abre.
- La primera apertura (~5,5 s) hace unas 8 llamadas en serie. Se podría
  bajar haciéndolas en paralelo.
- Todos los pacientes del índice quedan a cargo de un solo oncólogo
  (`--oncologo-id`).

## Pruebas

`tests/cbioportal/` no usa la red: un cliente falso responde con la misma
forma que la API real. Hay pruebas del cliente, del mapeo (cada regla
fail-closed), de la importación (idempotencia, fallos de red, HC-05 sobre
pacientes importados), del volcado a PAC-02/03, y del índice con carga
bajo demanda, incluidas pruebas por la API HTTP (`test_indice.py`).
