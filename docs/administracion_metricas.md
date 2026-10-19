# ADM-02 — Tablero de métricas de uso

## Historia de usuario

Como director médico, quiero un tablero de métricas de uso del sistema
(adopción, tiempo ahorrado, alertas generadas), para evaluar el impacto de
la herramienta.

Épica Administración · Could Have · 8 pts · depende de AUD-01 · no es MVP.

El backlog describe el tablero (adopción, tiempo ahorrado estimado, alertas
generadas y tasa de aceptación de las recomendaciones de IA) y una nota de UX:
la tasa de aceptación debe presentarse con cuidado, una tasa baja no es
necesariamente negativa y **no debe usarse como métrica de desempeño
individual**. No trae criterios de aceptación; estos son los propuestos
(confírmalos o ajústalos):

```
AC1  Dado un director médico y un periodo
     Cuando abre el tablero
     Entonces ve la adopción, el tiempo ahorrado estimado, las alertas generadas y
     cómo se resuelven las recomendaciones de IA, comparados con el periodo anterior;
     y un dato que no se puede leer aparece como "no disponible", nunca como cero

AC2  Dado un usuario que no es director médico
     Cuando intenta consultar las métricas
     Entonces el sistema lo deniega y el intento queda registrado (AUD-01);
     las consultas del director también quedan registradas

AC3  Dadas las métricas
     Cuando se calculan y se muestran
     Entonces son agregados de la institución: no hay ningún dato por persona, la
     aceptación de IA va con su nota de interpretación y se oculta cuando la
     muestra es tan pequeña que permitiría atribuirla a un médico
```

## Qué implementa

- `administracion/metricas_uso.py`: `consultar_metricas(fuentes, actor, desde=, hasta=)`
  devuelve un `MetricasUso` (adopción, tiempo ahorrado, alertas, aceptación de
  IA y serie semanal). Es el único punto de cálculo; el JSON, el panel y los
  tests salen de él.
- `administracion/panel_metricas.py`: `renderizar_panel(metricas)`, una página
  HTML autocontenida (gráficos SVG propios, sin librerías ni recursos externos).
- `administracion/coeficientes_tiempo.yaml`: los supuestos del tiempo ahorrado.
- `administracion/api.py`: `GET /metricas` (JSON) y `GET /metricas/panel` (HTML).
- `administracion/demo_metricas.py`: demo con datos sintéticos.
- Cambios aditivos en SEC-01 y AUD-01: `Rol.DIRECTOR_MEDICO`,
  `Accion.VER_METRICAS_USO` y `TipoAccion.CONSULTAR_METRICAS`.

## Qué mide y de dónde sale

Todo se calcula por día (UTC) para un periodo (por defecto, los últimos 30
días) y se compara con el periodo anterior de igual duración.

| Métrica | Cómo se calcula | Fuente |
|---|---|---|
| Adopción | usuarios clínicos (oncología y enfermería con cuenta activa) que consultaron, editaron o exportaron un expediente al menos una vez, entre todos los usuarios clínicos activos | `eventos_acceso` (AUD-01) + `usuarios` |
| Pacientes atendidos | pacientes distintos con esas acciones | `eventos_acceso` |
| Uso de funciones de IA | notas aprobadas, decisiones de tratamiento, estadificaciones con sugerencia, juicios diagnósticos | `revision_notas`, `decisiones_tratamiento`, `confirmaciones_estadificacion`, `juicios_clinicos_dx` |
| Alertas generadas | alertas críticas de laboratorio del periodo, por severidad, cuántas se revisaron y cuántas siguen pendientes hoy; conflictos de resultados; sincronizaciones externas exitosas y fallidas | `alertas_laboratorio`, `conflictos_laboratorio`, `sincronizaciones_externas` |
| Tiempo ahorrado | eventos contados × minutos supuestos (ver abajo) | los de arriba |
| Aceptación de IA | tratamiento: aceptada / aceptada con cambios / no aceptada; estadificación: estadio igual / distinto a la sugerencia | `decisiones_tratamiento`, `confirmaciones_estadificacion` |

Cada métrica suma las tablas que encuentre en las conexiones recibidas, así no
importa en qué base vive cada una (los accesos los guarda la base de pacientes,
las decisiones el expediente, las cuentas la base de usuarios). Una base pasada
dos veces cuenta una sola vez. Por defecto la API abre en **solo lectura** la
base de pacientes y la del expediente si existen, más las que se listen en
`COPILOTO_METRICAS_DBS` (rutas separadas por `;` en Windows o `:` en Linux).

## Decisiones de diseño

- **Nada por persona, por construcción.** Ninguna estructura de salida tiene un
  identificador de usuario, y ninguna función acepta filtrar por usuario: no hay
  forma de pedir "las cifras de la Dra. X". Una prueba revisa los campos de todos
  los dataclasses de salida y que ningún nombre de usuario aparezca en el JSON ni
  en el HTML. Es la respuesta a la nota de UX más fuerte que una advertencia:
  el dato individual simplemente no sale del módulo.
- **La aceptación de IA se presenta como distribución, no como cifra.** No hay
  un número destacado (la única cifra grande del tablero es la adopción): se
  muestra qué pasó con las recomendaciones (aceptadas tal cual, con cambios, no
  aceptadas) siempre junto a la nota "Cómo leer esto" (una tasa baja no es
  negativa; una muy alta tampoco es buena por sí sola; no mide a ningún médico).
  Los colores son una sola gama ordinal azul, sin verde ni rojo: aceptar no es
  "bueno" ni rechazar "malo".
- **Supresión en grupos pequeños.** La aceptación de un dominio no se muestra si
  hay menos de 30 decisiones o menos de 5 médicos distintos en el periodo (con 2
  médicos, el "agregado institucional" es casi una calificación personal). Al
  suprimirla no sale ninguna cifra, ni siquiera el total. Lo mismo con el
  desglose de adopción por rol (menos de 5 personas en el grupo). Los umbrales
  son `Parametros`: se pueden subir, no se recomienda bajarlos.
- **"Sin datos" no es cero.** Cada sección dice si su fuente existe. Una base
  sin conectar o una tabla que falta aparece como "—" con su motivo (y como
  `null` en el JSON), porque un 0 se leería como "nadie usa el sistema". Un cero
  con la fuente conectada sí se muestra como 0. El pie del tablero lista las
  fuentes sin conectar.
- **El tiempo ahorrado es una estimación, y se nota.** Cuenta eventos reales del
  sistema (notas aprobadas, sincronizaciones exitosas, decisiones y
  estadificaciones con apoyo del sistema) multiplicados por minutos *supuestos*,
  en un **rango** (mínimo–máximo), nunca un número puntual. Los minutos por
  defecto de `coeficientes_tiempo.yaml` **no están medidos**: son supuestos de
  partida y la institución debe reemplazarlos con su propio estudio de tiempos
  (`COPILOTO_COEFICIENTES_TIEMPO` apunta a su archivo). Los supuestos se ven en
  el mismo tablero. Si falta una fuente se suma lo que se puede contar y se avisa
  que el total es una subestimación; un archivo de supuestos absurdo (negativo,
  mínimo mayor que máximo) falla en voz alta.
- **Ver el tablero no cuenta como uso del sistema.** Solo VER, EDITAR y EXPORTAR
  (acciones sobre expedientes) cuentan como adopción; la propia consulta de
  métricas (`consultar_metricas`) y la gestión de usuarios no. Si no, mirar las
  métricas inflaría las métricas. También quedan fuera los accesos de cuentas que
  no son personal clínico activo (auditoría, cuentas dadas de baja, cuentas de
  sistema); el tablero informa cuántos fueron.
- **Solo el director médico** (`director_medico`, nuevo; `Accion.VER_METRICAS_USO`,
  fail-closed como el resto de SEC-01). Es un rol de gestión: no tiene acceso
  clínico a expedientes ni gestiona usuarios. Ni el `administrador` del sistema
  ni el `administrador_clinico` ven las métricas. Si la dirección quisiera que
  también las vea el administrador, es una línea en `PERMISOS_POR_ROL`. El
  actor se vuelve a leer de la base en cada consulta (un director desactivado o
  degradado ya no puede, aunque conserve su objeto `Usuario`).
- **Cada consulta queda en AUD-01** (`TipoAccion.CONSULTAR_METRICAS`), también los
  intentos denegados, con el periodo y la vía (`api`, `panel`), nunca con los
  datos. Si la traza no se puede escribir, no se entregan las métricas.
- **Solo lectura.** Las bases clínicas se abren en modo solo-lectura; lo único que
  escribe este módulo es el evento de auditoría, en la base de usuarios.
- **El tablero es una sola página sin dependencias externas** (sirve en una
  intranet hospitalaria sin internet) con política de contenido estricta
  (`default-src 'none'`), modo claro y oscuro, contraste forzado e impresión,
  cada gráfico con su tabla equivalente y el tooltip nunca como única vía para
  leer un valor. Los textos pasan por `html.escape`; el script usa `textContent`.
  La accesibilidad (WCAG 2.1 AA: teclado, lector de pantalla, contraste, reflujo a 320 px)
  está cubierta por pruebas propias (NFR-03): ver `docs/accesibilidad.md`.

## API

Misma autenticación que ADM-01 (HTTP Basic sobre el login de SEC-01, solo
HTTPS). 401 sin credenciales, 403 si el usuario no es director médico, 400 si el
periodo no es válido (al revés, futuro o de más de 400 días). En `/metricas/panel` el 400
es una página HTML que explica el error y deja corregir el periodo; en `/metricas`, JSON.

| Método y ruta | Qué hace |
|---|---|
| `GET /metricas?desde=AAAA-MM-DD&hasta=AAAA-MM-DD` | Las métricas en JSON (`Cache-Control: no-store`) |
| `GET /metricas/panel?desde=&hasta=` | El tablero HTML, con filtros de periodo |

```
python -m administracion crear-admin                 # primer administrador (si aún no existe)
# el administrador da de alta al director médico: POST /usuarios con "rol": "director_medico"
python -m seguridad.servidor_tls --app administracion.api:app --cert certs/localhost.pem --key certs/localhost-clave.pem
# abre /metricas/panel en la dirección HTTPS que imprima el servidor (usuario y contraseña del director médico)
```

## Límites conocidos

- **El tiempo ahorrado es tan bueno como sus supuestos.** Mientras no se calibren
  con un estudio de tiempos propio, léelo como orden de magnitud, no como cifra
  para reportar.
- **La adopción mide uso de expedientes, no calidad de uso.** Y depende de que los
  accesos se registren en AUD-01: hoy la API de pacientes solo los registra cuando
  recibe `usuario_id` (TODO SEC-01 en `patients/api.py`); sin eso la adopción
  subestima el uso real.
- **La plantilla es la de hoy.** `usuarios` no guarda historia: el denominador es
  "cuentas clínicas activas ahora", así que una baja reciente cambia la tasa de
  periodos pasados.
- **La identidad de quien decide no es homogénea**: TX guarda el id del oncólogo y
  EST el nombre del autor; por eso la supresión se evalúa por dominio y no se
  mezclan en una sola tasa.
- **DX-03 no entra en la aceptación**: el sistema no compara el juicio del médico
  con su priorización, así que no hay con qué calcular una tasa (el tablero lo dice).
- Solo hay una fuente de alertas (laboratorio, HC-02); cuando haya otras
  (interacciones, guías) se suman como fuente nueva.
- La supresión protege contra identificar a una persona en una cifra, no contra
  quien cruce el tablero con otras fuentes; el control de quién ve el tablero es
  el rol.

## Cómo probarlo

```
python -m pytest tests/administracion -q
python -m administracion.demo_metricas                # institución mediana; abre panel_metricas_demo.html
python -m administracion.demo_metricas --pequeno      # pocos médicos: se ven las supresiones de privacidad
```
