# HC-01 — Integración de historia clínica externa

> Como oncólogo, quiero integrar la historia clínica previa del paciente (de
> otros sistemas o en PDF/HL7), para no reconstruir manualmente sus
> antecedentes.

Módulo: `historia_clinica/integracion_externa.py`. Esquema:
`historia_clinica/schema_historia_clinica.sql`, que se aplica sobre la misma
base de datos de `expediente`. Lo que se importa queda en
`laboratorios`, `imagenologia` y `antecedentes_externos`, así que DX, EST, TX e
IA lo leen sin adaptadores adicionales.

## Vías de entrada

| Vía | Función | Qué importa |
|---|---|---|
| FHIR R4 | `sincronizar_paciente(conn, id, FuenteFHIR(...))` o `importar_bundle_fhir` | `Observation` (categoría `laboratory`) → `laboratorios`; `DiagnosticReport` (categoría `RAD`/`imaging`) e `ImagingStudy` → `imagenologia`; `Condition`, `Procedure` y `MedicationStatement` → `antecedentes_externos` |
| HL7 v2 | `importar_mensaje_hl7` (o una fuente con `formato = "hl7v2"`) | `ORU^R01`: cada `OBX` → `laboratorios` (la fecha sale de OBX-14 o, si falta, de OBR-7) |
| PDF | `cargar_historia_pdf` | El documento se guarda con DOC-01 (`documentos_clinicos.carga_documentos`) y queda en el historial de documentos del paciente |

`FuenteFHIR` busca `Patient?identifier=<identificación>` y luego trae
`Patient/{id}/$everything`. La `session` HTTP se puede inyectar, así que las
pruebas no dependen de un servidor real.

## Criterios de aceptación

| AC | Cómo se cumple | Pruebas |
|---|---|---|
| AC1: con integración HL7/FHIR, al sincronizar se carga la historia | `sincronizar_paciente` → `importar_bundle_fhir` / `importar_mensaje_hl7` | `test_sincronizar_desde_fhir_carga_la_historia_en_el_expediente`, `test_importar_hl7_oru_carga_los_laboratorios` |
| AC2: sin integración, el PDF queda asociado y consultable aunque no esté estructurado | `cargar_historia_pdf` reutiliza DOC-01 (verifica la firma real `%PDF-`) y deja una sincronización con estado `documento_no_estructurado` | `test_pdf_de_historia_queda_asociado_y_consultable` |
| AC3: si la sincronización falla, se notifica sin bloquear el resto del expediente | Toda excepción de la fuente o del contenido se captura. Queda una fila `fallida` en `sincronizaciones_externas` y se devuelve `ResultadoSincronizacion(exito=False, mensaje=...)`. No se modifica ningún otro dato | `test_fallo_de_la_fuente_se_notifica_sin_bloquear_el_expediente` y demás pruebas de fallo |

## Salvaguardas

- **Verificación de identidad.** Antes de importar se compara la identificación
  del mensaje (`Patient.identifier` o `PID-3`) con la del expediente. Si no
  coincide, el mensaje se rechaza completo. Si el servidor FHIR devuelve más de
  un paciente con la misma identificación, tampoco se importa nada.
- **Todo o nada.** Cada mensaje se importa en una sola transacción. Si falla a
  mitad de camino, se hace rollback y queda registrado el fallo.
- **Idempotencia.** `registros_importados` guarda `(fuente, identificador
  externo)` con restricción `UNIQUE`, así que re-sincronizar no duplica datos.
- Los tipos de recurso que no se reconocen se cuentan como omitidos; no
  producen error.

## Fuera de alcance

- Las alertas por valor crítico y los conflictos de marcador de laboratorio son
  de **HC-02**. Aquí los laboratorios se guardan tal como llegan y `alterado` se
  marca según su rango de referencia.
- La visualización DICOM/PACS es de **HC-03**, y el registro validado de
  biopsias y biomarcadores es de **HC-04**.
- La nota técnica del backlog recomienda dividir la historia por tipo de fuente,
  porque cada EHR es distinto. Esta primera entrega cubre los dos estándares
  (FHIR R4 y HL7 v2 ORU) y el PDF como alternativa. Los perfiles de cada
  institución (códigos locales, extensiones) se agregan como nuevas fuentes que
  implementen `FuenteHistoriaExterna`.
