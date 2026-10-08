# Módulo de pacientes (`patients/`)

Es lo que usa el oncólogo para encontrar a un paciente y abrir su expediente:

- registro de pacientes;
- búsqueda con filtros;
- resumen 360;
- registro y revisión de laboratorios (HC-02), biopsias y biomarcadores (HC-04).

Todo se expone en una API HTTP (`patients/api.py`) y en un cliente de consola
para demostraciones (`patients/demo.py`, ver `docs/PACIENTES_DEMO.md`).

## Historias

| Historia | Archivo | Qué hace |
|---|---|---|
| Registro de paciente (el código la llama HC-01; en el backlog es PAC-01) | `registro.py` | Valida los campos obligatorios y el formato; alerta de posible duplicado antes de crear; genera un identificador temporal para pacientes sin documento; permite "completar después" los antecedentes y el motivo de consulta |
| PAC-02 Búsqueda y filtros | `busqueda.py` | Nombre parcial (sin importar mayúsculas ni tildes), diagnóstico, estado del tratamiento y fecha de la última consulta, con paginación. Sin resultados responde con un mensaje, no con una lista vacía. Cada oncólogo solo ve a sus pacientes |
| PAC-03 Resumen 360 | `resumen_360.py` | Diagnóstico, estadio, tratamiento más reciente, alertas activas, acceso rápido a laboratorios, imágenes y notas, campos clave faltantes y biomarcadores clave |
| HC-02 Laboratorios | `historia_clinica/laboratorios.py` (expuesto aquí) | Ver `docs/historia_clinica_laboratorios.md` |
| HC-04 Biopsias y biomarcadores | `historia_clinica/biopsias_biomarcadores.py` (expuesto aquí) | Ver `docs/historia_clinica_biomarcadores.md` |

## Dos bases de datos

| Base | Ruta | Qué guarda | Quién la lee |
|---|---|---|---|
| Módulo de pacientes | `patients/db/pacientes.db` (`schema.sql`) | `pacientes`, `diagnosticos`, `tratamientos`, `consultas`, `alertas` y `estudios` | Búsqueda (PAC-02) y 360 (PAC-03) |
| Expediente clínico | `data/copiloto.db`, o `COPILOTO_EXPEDIENTE_DB` (esquemas de `expediente` + `historia_clinica`) | Laboratorios, imágenes, biomarcadores, datos estructurados, biopsias, alertas y conflictos de laboratorio… | DX, EST, TX, IA, HC-05 y el 360 (parte de HC-02/HC-04) |

**Cómo se vinculan.** Un paciente es el mismo en las dos bases por su identificación:
`patients.pacientes.numero_identificacion == expediente.pacientes.identificacion`.
Lo resuelve `patients/expediente.py`:

- **Pacientes de cBioPortal:** ya están vinculados, con tipo `externo` e identificación `CBIO:<estudio>:<paciente>`.
- **Pacientes registrados en la plataforma:** entran al expediente la primera vez que se les registra un laboratorio, un episodio, una biopsia o un biomarcador (`paciente_en_expediente(..., crear=True)`). Las lecturas nunca crean al paciente.

**Qué agrega el 360 cuando el paciente está en el expediente:**

- **Alertas:** laboratorio crítico (alta), conflicto de laboratorio (media) y biomarcador por confirmar (media).
- **Laboratorios recientes:** se leen del expediente, con las marcas "(crítico)", "(en conflicto)" o "(fuera de rango)".
- **Biomarcadores clave** (HC-04).
- **Diagnóstico:** si la base de pacientes no tiene ninguno, se muestra el del último episodio diagnóstico.

Si el expediente no existe, el 360 funciona igual que antes y no lo crea.

## Origen de los pacientes

La aplicación no trae datos de ejemplo:

- los pacientes son los que se registran en la plataforma y los importados de cBioPortal (`python -m cbioportal`, ver `docs/cbioportal.md`);
- los pacientes de ejemplo de las pruebas viven en `tests/patients/datos_prueba.sql`.

## API

```powershell
uvicorn patients.api:app --reload      # documentación interactiva en http://127.0.0.1:8000/docs
```

**Reglas generales:**

- **Alcance por oncólogo.** Todas las rutas reciben `oncologo_id` y solo actúan sobre los pacientes de ese oncólogo. Un paciente ajeno responde 404, igual que uno inexistente, para no confirmar que existe. *Pendiente (SEC-01): `oncologo_id` debe salir de la identidad autenticada.*
- **Formato de errores:** siempre `{"detail": {"errores": [{"campo", "mensaje"}]}}`.
  - 400: datos inválidos.
  - 409: duplicado al registrar un paciente, o identidad que no coincide al registrar un laboratorio.
- **Rutas del expediente.** Las de HC-02 y HC-04 abren el expediente en `EXPEDIENTE_PATH`. Por defecto es el de `historia_clinica.db.ruta_expediente()`; los tests lo apuntan a una base temporal.

| Método y ruta | Historia |
|---|---|
| `POST /pacientes` · `GET /pacientes` · `GET /pacientes/{id}` · `PATCH /pacientes/{id}` | Registro |
| `GET /pacientes/buscar` | PAC-02 |
| `POST`/`GET /pacientes/{id}/diagnosticos`, `…/tratamientos`, `…/consultas` | PAC-02 (datos que alimentan los filtros y el 360) |
| `GET /pacientes/{id}/resumen-360` | PAC-03 |
| `POST /pacientes/{id}/laboratorios` · `POST …/laboratorios/hl7` | HC-02: registro manual (doble validación) e interfaz de laboratorio |
| `GET …/laboratorios/marcadores` · `GET …/laboratorios/tendencia?prueba=` | HC-02: tendencias |
| `GET …/alertas-laboratorio` · `POST …/alertas-laboratorio/{alerta_id}/revisar` | HC-02: valores críticos |
| `GET …/conflictos-laboratorio` · `POST …/conflictos-laboratorio/{conflicto_id}/resolver` | HC-02: conflictos |
| `POST`/`GET …/episodios` · `POST`/`GET …/biopsias` | HC-04: episodio diagnóstico y biopsias |
| `POST`/`GET …/biomarcadores` (`?solo_clave=true`) · `POST …/biomarcadores/{bid}/confirmar` · `…/descartar` | HC-04: biomarcadores |

Con el expediente real presente, `GET /pacientes/{id}` y el 360 traen el
detalle de un paciente del índice de cBioPortal la primera vez que se abre
(`cbioportal.indice.CargadorDetalle`, ver `docs/cbioportal.md`). Si
`GET /pacientes/{id}` recibe `usuario_id`, el acceso queda registrado en la
auditoría (AUD-01).

## Archivos

```text
patients/
├── registro.py        Registro de paciente
├── busqueda.py        PAC-02
├── resumen_360.py     PAC-03 (+ datos del expediente: HC-02, HC-04)
├── expediente.py      Puente con el expediente clínico
├── models.py          Modelos de dominio (sin SQL ni HTTP)
├── schemas.py         Esquemas de entrada/salida de la API
├── api.py             API HTTP
├── demo.py            Cliente de consola
├── medicacion_actual.py  Lo usa tx_clinica (interacciones); no es parte de esta base
└── db/                schema.sql y conexión
```

## Pruebas

```powershell
python -m pytest tests/patients -q
```

- Cada prueba usa bases temporales, tanto la de pacientes como el expediente; nunca `patients/db/pacientes.db` ni `data/copiloto.db`.
- `test_api_laboratorios_biomarcadores.py` cubre las rutas de HC-02/HC-04 y su efecto en el 360, incluido que TX-01 reciba el biomarcador confirmado.
