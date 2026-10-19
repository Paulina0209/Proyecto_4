# Interfaz web del copiloto oncológico (`frontend/`)

Una interfaz sobria, blanca y azul, de aspecto clínico, para el núcleo del trabajo de la persona
que atiende pacientes: **iniciar sesión, ver a sus pacientes, abrir un expediente** (resumen,
laboratorios con alertas y tendencias, imágenes del PACS, biomarcadores e historia clínica),
**exportar** el expediente y, para la dirección médica, **ver el tablero de métricas de uso** (ADM-02)
dentro de la misma navegación.

No hay paso de compilación ni dependencias de JavaScript: son archivos estáticos (HTML + CSS + módulos
ES) que sirve FastAPI. Las APIs que ya existían no se modificaron: la pasarela las monta detrás de la
sesión y de los permisos.

## Probarla en 30 segundos (datos inventados)

```
python -m frontend.demo                 # siembra datos sintéticos y abre https://127.0.0.1:8443
python -m frontend.demo --puerto 9443 --carpeta salida_demo_frontend
python -m frontend.demo --solo-sembrar  # solo crea las bases
```

El navegador avisará del certificado autofirmado (es solo para desarrollo). La contraseña de todos
los usuarios de la demostración es `Demo-Clave-2026` y la propia pantalla de acceso los lista:

| Usuario | Qué muestra |
|---|---|
| `dra.rios` | Oncología: seis pacientes con laboratorios, alertas (potasio crítico), tendencia de hemoglobina, biomarcadores, imágenes del PACS, un expediente incompleto y uno sin datos clínicos |
| `dr.vega` | Oncología: otros dos pacientes (la Dra. Ríos no puede verlos) |
| `direccion` | Dirección médica: tablero de métricas de uso |
| `enf.mora`, `auditor.demo`, `admin.demo` | Pantalla de «sin pantallas de expediente» (ver «Límites») |

Todo es sintético: personas, resultados, estudios y el PACS (`PacsDemo`, que nunca toca la red). La
página lo dice en una franja permanente. Los datos se crean con las mismas funciones del sistema
(registro de pacientes, HC-02, HC-04, HC-03), así que la interfaz se prueba contra el comportamiento
real de las APIs, no contra respuestas copiadas a mano.

## Cómo está armada

```
navegador ──HTTPS──▶ frontend.servidor (pasarela)
                       ├─ /                 index.html  (CSP estricta, sin nada en línea)
                       ├─ /ui/*             CSS, JS, icono
                       ├─ /api/sesion       login / estado / logout  (SEC-01 + sesión en servidor)
                       ├─ /api/pacientes/*  patients.api montada SIN cambios, con identidad y permisos por delante
                       ├─ /api/pacientes/{id}/exportar   DOC-02 (HTML accesible o PDF) + auditoría
                       └─ /panel/metricas   tablero ADM-02 (para el marco de la interfaz)
```

- **Sesión.** `POST /api/sesion` usa `seguridad.autenticar` (el bloqueo por intentos fallidos aplica:
  423 si la cuenta está bloqueada, y el mensaje no distingue «usuario inexistente» de «contraseña
  incorrecta»). La sesión vive en el servidor (`frontend/sesiones.py`; el almacén guarda el hash del
  token, caduca a los 20 min de inactividad y a las 8 h como máximo). La cookie es `__Host-`,
  `HttpOnly`, `Secure`, `SameSite=Strict`.
- **La identidad sale de la sesión, no del navegador.** Antes de cada petición a la API de pacientes la
  pasarela descarta cualquier `oncologo_id`/`usuario_id` que mande el cliente y pone los de la sesión
  (esto resuelve, para este camino de acceso, el `TODO(SEC-01)` de `patients/api.py`). En
  `POST …/alertas-laboratorio/{id}/revisar`, `revisada_por` también se fija con la sesión.
- **Permisos por rol** con `verificar_permiso` (cierra por defecto). El usuario se relee de la base en
  cada petición: desactivar una cuenta o cambiarle el rol surte efecto en la siguiente petición, sin
  esperar a que la sesión caduque.
- **Lista cerrada de rutas.** Solo existen las lecturas que la interfaz usa y la revisión de alertas;
  altas, ediciones, borrados, `/docs` y `/openapi.json` responden 404 aun con sesión.
- **CSRF.** Toda petición que cambia algo exige la cabecera `X-Copiloto-Solicitud: 1` (que una página
  de otro sitio no puede mandar sin permiso CORS) y, si trae `Origin`, que sea el mismo sitio; además
  de `SameSite=Strict`.
- **Cabeceras.** CSP `default-src 'none'; script-src 'self'; style-src 'self'; …; frame-ancestors 'none'`
  (sin `unsafe-inline` ni `unsafe-eval`), `nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control:
  no-store` y HSTS. El tablero ADM-02 trae su script y estilos en línea, así que conserva su propia
  política y solo admite ser incrustado por esta misma página (`frame-ancestors 'self'`).
- **Solo HTTPS** (`SoloHTTPSMiddleware`, SEC-02): por HTTP plano todo responde 403.
- **El texto clínico es texto.** El JavaScript construye el DOM con `createElement`/`createTextNode`;
  no hay `innerHTML`, `eval` ni manejadores en línea (una prueba lo verifica archivo por archivo y otra,
  en Chromium, comprueba que un nombre con marcado se muestra como texto).

### Cómo se pone en marcha con bases reales

```
python -m seguridad.servidor_tls --app frontend.servidor:app --port 8443 --cert cert.pem --key clave.pem
```

`frontend.servidor:app` usa la configuración de siempre: `COPILOTO_USUARIOS_DB` (usuarios),
`COPILOTO_EXPEDIENTE_DB`, la base de pacientes de `patients`, `COPILOTO_METRICAS_DBS` y la
configuración de PACS y visor de HC-03 (`docs/historia_clinica_imagenes_pacs.md`). Con el PACS sin configurar o caído,
la pantalla de imágenes lo dice y muestra lo último sincronizado y los informes del expediente.

## Pantallas

| Pantalla | Qué hace |
|---|---|
| Acceso | Un campo por línea, errores por campo y en un resumen con `role="alert"`, foco en el primer campo con problema |
| Pacientes | Filtros (nombre, diagnóstico, estado, fechas), tabla paginada con estado del tratamiento (icono + texto) |
| Expediente › Resumen | Diagnóstico y tratamiento, alertas activas, biomarcadores clave, laboratorios, imágenes y notas recientes, uso de IA y consentimiento |
| Expediente › Laboratorios | Alertas críticas con **Marcar como revisada** (solo oncología), tendencia por prueba (SVG con círculo/cuadrado/rombo según estado, más su tabla) y marcadores |
| Expediente › Imágenes | Estudios del PACS con informe, **Abrir en el visor** y bitácora de consultas; si el PACS no responde, lo dice y conserva el informe |
| Expediente › Biomarcadores / Historia | Biopsias y biomarcadores; diagnósticos, tratamientos, consultas y episodios |
| Exportar | HTML accesible (recomendado) o PDF, con traza de auditoría (`exportar_expediente_html/pdf`) |
| Métricas de uso | El tablero ADM-02 dentro de la navegación, solo para dirección médica |
| Sin pantallas de expediente | Explica por qué un rol no ve pacientes (ver «Límites») |

Tema automático, claro u oscuro (botón de la cabecera; solo se recuerda esa preferencia en
`localStorage`, nunca datos clínicos).

## Accesibilidad (NFR-03)

La interfaz entra a la compuerta de `accesibilidad/` completa:

- **Estática** (`tests/frontend/test_estatico.py`): `auditar_html(index.html)` sin hallazgos; 36 pares de
  color verificados en claro, oscuro del sistema y oscuro manual; sin estilos ni scripts en línea;
  objetivos de al menos 2.5 rem; texto en rem; reglas del JavaScript.
- **Chromium real** (`tests/frontend/test_navegador.py`): cada pantalla autenticada, en claro 1280 px,
  oscuro 1280 px y claro 320 px: contraste calculado, reflujo, espaciado de texto y axe-core (WCAG 2.1
  A/AA); recorrido por teclado con foco visible; salto al contenido; foco al título al cambiar de
  pantalla; anuncios para lectores de pantalla; gráfica con nombre, descripción, formas distintas y
  tabla; consola sin errores. Se omiten (no fallan) si no hay Playwright, Chromium o uvicorn.

**Qué NO está hecho.** Un resultado automático limpio no es «accesible»: falta la prueba manual con
lector de pantalla (NVDA/JAWS/VoiceOver) y con personas usuarias (`docs/accesibilidad.md`, «Prueba
manual»). El PDF sigue sin estar etiquetado (reportlab); la alternativa accesible es el HTML. El tablero
incrustado (ADM-02) y el visor de imágenes (OHIF, de terceros) tienen su propia cobertura o ninguna: el
visor se abre en otra pestaña y su accesibilidad es la del visor.

## Límites conocidos

- **Solo el rol `oncologo` ve expedientes.** SEC-01 da `ver_expediente` también a enfermería y
  auditoría, pero el modelo de datos todavía no dice a qué oncólogo asiste cada persona (no hay
  asignación de pacientes). Mientras no exista, se les niega con una explicación en lugar de adivinar
  o enseñar todo. Es una decisión de seguridad, no un olvido; cuando exista la asignación, basta con
  ampliar la regla en `frontend/servidor.py`.
- **Las sesiones viven en la memoria del proceso.** Reiniciar el servidor cierra todas, y con varios
  procesos cada uno tendría las suyas; para producción con varias réplicas hay que moverlas a un almacén
  compartido (la interfaz `AlmacenSesiones` es pequeña a propósito).
- **Casi todo es de solo lectura.** La única escritura es revisar una alerta de laboratorio. No hay aún
  pantallas para resolver conflictos de laboratorio, registrar el consentimiento de IA, cargar
  documentos (DOC-01) ni las funciones de IA (resumen, estadificación, recomendación de tratamiento).
- **Sin pruebas en navegadores distintos de Chromium** ni con lectores de pantalla (ver arriba).
- La interfaz asume `patients.api` tal como está. Al probarla apareció un fallo latente de esa API: su
  `get_conn` abre la conexión SQLite en un hilo y el endpoint corre en otro, y SQLite lo prohíbe
  (`ProgrammingError`) cuando llegan varias peticiones a la vez, que es justo lo que hace la pantalla
  del expediente. La pasarela lo evita sin tocar `patients/` (reemplaza esa dependencia solo mientras
  corre); el arreglo de raíz es una línea: `check_same_thread=False` en `get_conn`/`db.conectar`.

## Pruebas

```
python -m pytest tests/frontend -q
```

135 pruebas: almacén de sesiones, pasarela (autenticación, bloqueo, CSRF, identidad inyectada, roles,
lista cerrada de rutas, HTTPS, exportación y auditoría, tablero, cabeceras), archivos estáticos y
Chromium. Para las de navegador: `pip install playwright` y `playwright install chromium`; para axe-core,
`npm install axe-core` y `AXE_CORE_JS=ruta\axe.min.js` (sin él se omite solo axe).
