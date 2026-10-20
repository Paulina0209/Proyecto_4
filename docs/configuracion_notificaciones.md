# CFG-02 — Notificaciones y alertas

> Como oncólogo, quiero configurar notificaciones y alertas (ej. resultados críticos, estudios
> pendientes), para no perder información relevante.

Módulo: `configuracion/notificaciones.py`. Esquema: `configuracion/schema_notificaciones.sql` (en la base
de pacientes). Dependencias: HC-02 (resultados críticos) y SEC-01 (cada quien ve y configura lo suyo).
Interfaz: **Notificaciones** en el menú de oncología.

## Eventos y canales

| Evento | Origen (no se copian datos) |
|---|---|
| `resultado_critico` | alertas de laboratorio crítico **activas** de HC-02 (al revisarlas, salen) |
| `estudio_pendiente` | alertas `estudio_pendiente` sin resolver del resumen 360 |
| `interaccion_detectada` | alertas `interaccion` sin resolver del resumen 360 |

| Canal | Estado |
|---|---|
| `en_aplicacion` | la bandeja de «Notificaciones» (único canal; no hay envío por correo) |

Sin configuración, todos los eventos avisan en la aplicación.

## Cómo se entera el oncólogo

El enlace **Notificaciones** del menú muestra cuántas tiene sin leer («Notificaciones 3»; un lector de pantalla
oye «3 sin leer»). El contador (`frontend/estatico/app.js`) consulta `GET /notificaciones` al cambiar de pantalla,
al volver a la pestaña y cada 45 s mientras la pestaña está visible. Si sube, anuncia «Tienes 1 notificación nueva»
por la región `aria-live` de la página. No hay notificaciones del sistema operativo ni envío de correo.

## API (`patients.api`; la pasarela pone la identidad de la sesión)

```
GET  /notificaciones                     bandeja: no leídas y más graves primero
GET  /notificaciones/preferencias        eventos, canales y si es la configuración por defecto
PUT  /notificaciones/preferencias        {"preferencias": [{"evento", "activo", "canales"}]}
POST /notificaciones/{id}/leida          id: lab-<n> | alerta-<n>
```

- Guardar es **todo o nada**: evento o canal desconocido, o un evento activo sin canal, responde 400
  con `{campo, mensaje}` y no se guarda nada. Los eventos que no se envían quedan como estaban.
- Solo aparecen pacientes del oncólogo de la sesión. Marcar como leída es personal y **no resuelve la
  alerta de origen** (eso se hace donde corresponde, p. ej. «Marcar como revisada» en Laboratorios).

## Pruebas

```
python -m pytest tests/configuracion/test_notificaciones.py tests/patients/test_api_linea_tiempo_notificaciones.py tests/frontend/test_linea_tiempo_notificaciones.py -q
```
