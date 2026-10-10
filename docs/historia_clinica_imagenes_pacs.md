# HC-03 — Integración de imágenes diagnósticas (DICOM/PACS)

## Historia de usuario

Como oncólogo, quiero integrar las imágenes diagnósticas del paciente
(idealmente por DICOM/PACS) para revisarlas junto al resto de su historia
clínica.

## Evaluación previa (el riesgo de la historia)

El backlog pide evaluar explícitamente, antes de comprometerse, si se
construye un visor DICOM. Decisión: **no se construye; se incrusta uno de
terceros.**

| Opción | Costo | Riesgo | Decisión |
|---|---|---|---|
| Visor DICOM propio (WADO, ventana/nivel, MPR, series, mediciones) | Muy alto: meses de trabajo | Clínico (una medición o una orientación mal hechas) y de mantenimiento | Descartada |
| Visor de terceros incrustado (OHIF u otro de la institución) hablando con el PACS por DICOMweb | Bajo: un enlace por estudio | Depende de que la institución tenga o despliegue el visor | **Elegida** |
| Solo informes (texto) | Mínimo | Pierde la imagen | Se conserva como degradación (ver AC2) |

Consecuencia: este módulo **no maneja píxeles**. Lista los estudios del
PACS, los enlaza a su informe y le entrega al visor el `StudyInstanceUID`
con una plantilla de URL configurable.

## Qué implementa

`historia_clinica/imagenes_pacs.py`:

- `FuenteDICOMweb`: cliente QIDO-RS (`GET {base}/studies?PatientID=…`, DICOM JSON;
  204 = sin estudios). La sesión HTTP es inyectable, igual que `FuenteFHIR` de
  HC-01. Cualquier objeto con `nombre` y `buscar_estudios(identificacion)` cumple
  `FuentePACS` (así se prueba sin red).
- `sincronizar_estudios`: trae e indexa los estudios del paciente en
  `estudios_pacs` (idempotente por `(pacs, study_uid)`).
- `estudios_del_expediente`: lo que se ve al abrir el expediente (AC1/AC2).
- `abrir_visor`: URL del estudio en el visor, o aviso explícito (AC2).
- `historial_consultas`: bitácora `consultas_pacs` (solo inserción).

### Configuración (entorno)

| Variable | Uso |
|---|---|
| `COPILOTO_PACS_URL` | Base DICOMweb del PACS (p. ej. `https://pacs.hospital.org/dicom-web`). Sin ella: "no hay un PACS configurado". |
| `COPILOTO_PACS_NOMBRE` | Nombre que se muestra (por defecto "PACS institucional"). |
| `COPILOTO_PACS_TOKEN` | Token Bearer, si el PACS lo exige. |
| `COPILOTO_PACS_USUARIO` / `COPILOTO_PACS_PASSWORD` | Usuario y contraseña (HTTP Basic), p. ej. Orthanc con `ORTHANC_PASSWORD`. El token tiene prioridad si hay ambos. |
| `COPILOTO_VISOR_URL` | Plantilla del visor, con `{study_uid}`, p. ej. `https://visor.hospital.org/viewer?StudyInstanceUIDs={study_uid}` (formato de OHIF). Solo http(s). |

## Criterios de aceptación

```
Dado que el paciente tiene un estudio de imagen disponible en el PACS
Cuando abro su expediente
Entonces puedo ver el estudio o su informe asociado
```

`GET /pacientes/{id}/imagenes` devuelve cada estudio con modalidad, fecha,
series/instancias, `visor_url` y su `informe`. El informe es la fila de
`imagenologia` que ya existe en el expediente (p. ej. importada por HC-01). Se
enlaza **solo si es único**: misma fecha y modalidad compatible (`CT` ↔
"Tomografía", "TC"…). Con cero o varios candidatos no se adivina: el estudio
queda sin informe y los informes sueltos salen en `informes_sin_estudio`.

```
Dado que no hay conexión con el PACS de la institución
Cuando intento ver la imagen
Entonces el sistema me informa que la integración no está disponible, sin fallar en silencio
```

- `GET /pacientes/{id}/imagenes/{study_uid}/visor` responde **503** con
  `{"mensaje": …, "informe": …}`: el motivo (red, HTTP, formato, sin PACS
  configurado, sin visor) y, si el estudio tiene informe, el informe, para poder
  leerlo igual.
- `GET /pacientes/{id}/imagenes` responde 200 con `integracion_disponible=false`
  y `mensaje`; muestra lo último indexado (`desde_indice_local=true`) y los
  informes del expediente.
- Todo fallo queda en `consultas_pacs` con estado `fallida`
  (`GET /pacientes/{id}/imagenes/consultas`).
- Ninguna excepción del PACS se propaga; el resto del expediente no se toca.

## Decisiones de seguridad

- **Identidad primero**: cada estudio debe traer el `PatientID` del
  expediente y, si trae nombre, coincidir con él (`nombres_coinciden`, de
  HC-02). Un estudio de otro paciente se descarta, se cuenta (`estudios_rechazados`)
  y se avisa; nunca se muestra.
- Un `StudyInstanceUID` que no cumple el formato DICOM (dígitos y puntos,
  ≤ 64) se rechaza: no llega al visor ni a la URL.
- La plantilla del visor debe ser http(s) y contener `{study_uid}`.
- Un estudio ya indexado para otro paciente no se reasigna.
- Con `usuario_id`, abrir las imágenes o el visor queda en AUD-01 (`ver`).

## Límites conocidos

- Si un estudio desaparece del PACS, sigue en el índice local hasta que se
  limpie (se marca con su `sincronizado_en`).
- No se recupera un informe desde el PACS (QIDO-RS no lo trae; en DICOM sería un
  SR o un DiagnosticReport del RIS). Se usa el del expediente. Un RIS/FHIR
  `DiagnosticReport` sería otra `FuentePACS` opcional.
- La autenticación del visor y del PACS depende de la institución
  (SEC-01 sigue pendiente a nivel de API).
- Para un paciente que aún no estaba en el expediente, consultar sus imágenes
  lo crea ahí (igual que registrar un laboratorio), porque el índice cuelga de él.

## Probarlo con un PACS real (Orthanc + OHIF en Docker)

```
docker run -p 8042:8042 -p 4242:4242 -e ORTHANC_PASSWORD=orthanc `
  -e DICOM_WEB_PLUGIN_ENABLED=true -e OHIF_PLUGIN_ENABLED=true orthancteam/orthanc
pip install pydicom
python -m historia_clinica.demo_orthanc
```

`demo_orthanc` genera un estudio DICOM sintético (ecografía de la paciente
sintética `SINT-0001`), lo sube a Orthanc, consulta HC-03 por DICOMweb e imprime
el link del visor OHIF (`http://localhost:8042/ohif/viewer?StudyInstanceUIDs=…`),
que se abre en el navegador (usuario `orthanc`, contraseña la de arriba). Después
simula la caída del PACS para mostrar el aviso de AC2. Para usar HC-03 con la API
contra ese Orthanc:

```
$env:COPILOTO_PACS_URL = "http://localhost:8042/dicom-web"
$env:COPILOTO_PACS_USUARIO = "orthanc"; $env:COPILOTO_PACS_PASSWORD = "orthanc"
$env:COPILOTO_VISOR_URL = "http://localhost:8042/ohif/viewer?StudyInstanceUIDs={study_uid}"
```

El estudio solo se muestra si su `PatientID` y nombre coinciden con los del
paciente del expediente (identidad primero). `demo_imagenes_pacs` es la versión
sin red, con un PACS simulado: su link es de ejemplo y no abre.

## Cómo probarlo

```
python -m pytest tests/historia_clinica/test_imagenes_pacs.py tests/patients/test_api_imagenes_pacs.py -q
python -m historia_clinica.demo_imagenes_pacs
```
