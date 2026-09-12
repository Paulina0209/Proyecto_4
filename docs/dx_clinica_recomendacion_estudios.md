# DX-01 — Recomendación de estudios necesarios

## Alcance de esta implementación

Este documento describe el diseño de `dx_clinica.catalogo_estudios` y
`dx_clinica.recomendacion_estudios`, que implementan la historia de
usuario **DX-01** del backlog (épica Diagnóstico):

> Como oncólogo, quiero que el sistema recomiende únicamente los estudios
> necesarios según el caso, para evitar exámenes redundantes o costosos.

Criterios de aceptación:

> Dado un caso con sospecha diagnóstica definida, cuando solicito
> recomendación de estudios, entonces recibo una lista priorizada con
> justificación de cada estudio sugerido.
>
> Dado que ya existen estudios equivalentes recientes en el expediente,
> cuando se genera la recomendación, entonces el sistema no vuelve a
> sugerir un estudio redundante.

Dependencias formales: **HC-05** e **IA-01**. HC-05 (resultados de
laboratorio/imagenología/biomarcadores del expediente) ya está cubierto
por `historia_clinica_mock`; IA-01 (el asistente conversacional) es,
en la práctica, quien le entregaría a este módulo la sospecha
diagnóstica como texto — este módulo no depende de ningún componente
concreto de IA-01, solo recibe esa sospecha como parámetro de texto.

## Por qué reutiliza `obtener_hallazgos_de_paciente` de DX-02

Para decidir si un estudio ya es redundante hace falta ver **todo** el
expediente del paciente (cualquier laboratorio, imagen o biomarcador ya
registrado, esté o no vinculado a una consulta puntual), no solo lo de
la consulta actual — exactamente el mismo alcance que ya necesita DX-02.
Por eso `recomendar_estudios(...)` recibe una lista de `HallazgoClinico`
(el mismo tipo que produce `historia_clinica_mock.adapters.obtener_hallazgos_de_paciente`)
en vez de definir su propio adaptador: no hay nada que este módulo
necesite del expediente que DX-02 no haya resuelto ya.

## Dos catálogos curados, en el mismo espíritu que DX-02

Igual que `dx_clinica.knowledge_base` (perfiles diagnósticos de DX-02),
`dx_clinica.catalogo_estudios` es una tabla de conocimiento curada y
explícita, no un modelo estadístico ni un LLM decidiendo qué estudios
pedir:

- `PerfilSospechaDiagnostica`: qué palabras clave reconocen una sospecha
  diagnóstica de entrada, y qué estudios sugiere ese perfil.
- `EstudioCatalogado`: un estudio concreto — nombre, tipo (`laboratorio`
  / `imagenologia` / `biomarcador`, para poder cruzarlo contra
  `HallazgoClinico.origen`), **justificación clínica** (nunca opcional:
  no existe ningún camino para producir una sugerencia sin ella) y las
  palabras clave que identifican, dentro de los hallazgos ya
  registrados del mismo tipo, si un estudio equivalente ya existe.

El reconocimiento de la sospecha diagnóstica reutiliza
`dx_clinica.matcher.coincide_sin_negacion` (el mismo detector simple de
negación que ya usa DX-02): "se descarta progresión de la enfermedad" no
debe activar el perfil de progresión, igual que "sin hallazgos de
progresión" no cuenta como progresión en DX-02.

## Cómo se satisface cada criterio de aceptación

| Criterio de aceptación | Mecanismo en el código |
|---|---|
| Con sospecha diagnóstica definida, se recibe una lista priorizada con justificación de cada estudio | `recomendar_estudios()` reconoce el/los perfil(es) del catálogo que coinciden con la sospecha y devuelve un `EstudioSugerido` por cada estudio no redundante, con `orden` (1-based, por prioridad del catálogo — nunca una probabilidad calculada) y `justificacion` siempre no vacía. |
| No se vuelve a sugerir un estudio redundante si ya existe uno equivalente reciente | Antes de aceptar cada estudio del catálogo, `_ya_existe_equivalente_reciente()` busca en `hallazgos` uno del mismo `tipo` cuyo texto mencione alguna palabra clave de equivalencia **y** cuya fecha esté dentro de `ventana_dias_estudio_reciente` (90 días por defecto, configurable). Si lo encuentra, el estudio se mueve a `estudios_omitidos_por_redundantes` con el motivo y el hallazgo exacto que lo hizo redundante, en vez de incluirse en la lista sugerida. |

## La ventana de recencia: por qué un estudio antiguo sí se vuelve a sugerir

Un estudio "ya existente" en el expediente no siempre significa que ya
no haga falta pedirlo de nuevo — un resultado de hace dos años no
responde la pregunta clínica de hoy. Por eso la redundancia se evalúa
como "¿existe uno equivalente **dentro de la ventana de recencia**?",
no "¿existe alguna vez en el historial?". Esto se ve directamente en el
escenario B del demo: el biomarcador molecular de Carlos (EGFR,
registrado en 2024) queda **fuera** de la ventana de 90 días respecto a
la fecha de referencia del escenario (2026-02-10), así que
`reevaluacion_biomarcadores_moleculares` **sí** se sugiere — coincidiendo
con lo que su propia nota de consulta ya pedía ("se solicita nueva
biopsia para reevaluar biomarcadores"). En cambio, su TAC de tórax y su
perfil hepático son de días antes de esa misma fecha de referencia, así
que esos dos sí quedan correctamente omitidos como redundantes.

La comparación de fechas usa cadenas ISO (`AAAA-MM-DD`) directamente
(`hallazgo.fecha >= fecha_limite`), válida porque ese formato ordena
lexicográficamente igual que cronológicamente — el mismo patrón que ya
usa `historia_clinica_mock.repository.facts_estructurados_de_paciente`.

## Nunca se inventa una lista genérica

Si la sospecha diagnóstica de entrada no coincide con ningún perfil del
catálogo, `recomendar_estudios()` no cae de vuelta a una lista "por si
acaso": devuelve `estudios_sugeridos=()` junto con
`advertencia_sospecha_no_reconocida` explícita (`SOSPECHA_NO_RECONOCIDA`).
Es el mismo principio que ya usa DX-02 con `SIN_SUSTENTO_SUFICIENTE`
cuando ninguna alternativa diagnóstica tiene sustento real.

## Componentes

- `catalogo_estudios.py`: `EstudioCatalogado`, `PerfilSospechaDiagnostica`,
  `CATALOGO_ESTUDIOS_POR_SOSPECHA` (tres perfiles de ejemplo: progresión
  de enfermedad metastásica, toxicidad musculoesquelética, proceso
  infeccioso respiratorio).
- `recomendacion_estudios.py`: `EstudioSugerido`, `EstudioOmitidoPorRedundante`,
  `ResultadoRecomendacionEstudios`, y `recomendar_estudios(...)` — el
  punto de entrada de la historia.
- `demo_estudios.py`: tres escenarios (AC1 sin estudios previos; AC2 no
  repite lo reciente pero sí reevalúa lo antiguo; sospecha no
  reconocida), usando los pacientes sintéticos María y Carlos.

## Cómo probarlo

```
python -m dx_clinica.demo_estudios
```

Y las pruebas automatizadas:

```
pytest tests/dx_clinica/test_recomendacion_estudios.py -v
```

## Fuera de alcance de esta historia

- **Costo de cada estudio:** la historia menciona "exámenes redundantes o
  costosos", pero el criterio de aceptación solo exige evitar
  redundancia (no un modelo de costos). El catálogo no incluye ningún
  campo de costo todavía; podría añadirse sin cambiar la forma del
  resultado si se necesitara más adelante.
- **Registrar/enviar la orden del estudio:** este módulo solo sugiere;
  no existe ningún flujo en este repositorio que convierta una sugerencia
  en una orden médica real (sería una historia propia, similar en
  espíritu a TX-04 para tratamientos).
- **Cobertura clínica del catálogo:** igual que `knowledge_base.py` de
  DX-02, los tres perfiles incluidos son un punto de partida pequeño
  para poder probar la historia de punta a punta con los pacientes
  sintéticos existentes, no un catálogo clínico validado ni exhaustivo.
