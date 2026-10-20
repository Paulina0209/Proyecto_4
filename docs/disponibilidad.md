# NFR-02 — Disponibilidad (SLA ≥ 99,5 %)

> Como institución, quiero alta disponibilidad del sistema (SLA ≥ 99,5 %), para
> que esté accesible durante el horario clínico.

Un 99,5 % mensual admite **3 h 39 min de caída al mes** (el *presupuesto de
error*). Criterios de aceptación definidos para la historia:

```
AC1  El balanceador puede preguntar si una réplica está viva y si está lista para atender
AC2  Si cae una dependencia externa (modelo de IA, PACS), el sistema sigue atendiendo degradado;
     bajo carga, la base de datos no provoca caídas
AC3  La disponibilidad real se mide desde afuera contra el SLA, con presupuesto de error e incidentes
```

## Sondas (`operacion/salud.py`)

| Ruta | Responde | Para qué |
|---|---|---|
| `GET /salud/vivo` | siempre 200 si el proceso está en pie. Es la única ruta que también se atiende por HTTP, porque no lleva datos | el orquestador reinicia el proceso si no responde |
| `GET /salud/listo` | 200, o **503** si falla algo crítico | el balanceador deja de mandarle tráfico a esa réplica, sin reiniciarla |
| `GET /salud/metricas` | latencias por ruta (NFR-01) | diagnóstico |

`/salud/listo` revisa:

| Verificación | Si falla |
|---|---|
| Base de pacientes, expediente y usuarios (se abren en solo lectura y nunca se crean) | crítica → 503 |
| Sesiones compartidas (si se usan, NFR-05) | crítica → 503 |
| Espacio en disco (mínimo 200 MB) | crítica → 503 |
| Modelo de IA y PACS | no crítica → `degradado` (hay respaldo por reglas y los informes del expediente) |

Está en `patients.api` y en la pasarela web (`frontend.servidor`).

## Robustez bajo carga

Con 10 médicos a la vez, la API de pacientes devolvía 500 en ~80 % de las
peticiones (`sqlite3.ProgrammingError`), y con 25 en ~85 %. Era un fallo de
disponibilidad que con un solo usuario no se veía. Se corrigió de raíz en
`patients/db` y `historia_clinica/db` (ver `docs/rendimiento.md`): ahora 0
errores con 25 y con 50 médicos.

## Monitor del SLA (`operacion/monitor.py`)

```powershell
python -m operacion.monitor vigilar https://copiloto.hospital/salud/listo --ca certs/ca.pem --intervalo 30
python -m operacion.monitor informe --dias 30
python -m operacion.monitor informe --dias 30 --horario 07:00-19:00   # solo horario clínico
```

- Un sondeo cuenta como disponible si `/salud/listo` responde 200 en menos de
  5 s. Un sistema que tarda más tampoco está disponible para el médico.
- La disponibilidad se pondera por tiempo. Si el monitor estuvo apagado, ese
  hueco no cuenta ni a favor ni en contra.
- El informe da el porcentaje, el presupuesto de error consumido y el que
  queda, y cada incidente con inicio, fin, duración y causa (p. ej.
  `HTTP 503: base de pacientes`). Devuelve código 1 si no se cumple el SLA.

## Recuperación

Los respaldos cifrados de SEC-02 (`python -m seguridad.cifrado respaldar` /
`restaurar`) permiten reconstruir una base dañada. Para que una caída de una
máquina no consuma el presupuesto, hacen falta al menos dos réplicas detrás de
un balanceador (NFR-05).

## Pruebas y demo

```powershell
python -m pytest tests/operacion/test_disponibilidad.py -q
python demo_operacion.py --solo nfr02
```
