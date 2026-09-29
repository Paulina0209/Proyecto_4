# NFR-06 — Cumplimiento de datos personales y gestión de derechos

> Como institución, quiero que el sistema permita aplicar las políticas de
> tratamiento de datos de la jurisdicción correspondiente y gestionar los
> derechos asociados a la información personal, para facilitar el
> cumplimiento normativo.

Módulos: `privacidad/tratamiento_datos.py`, `privacidad/models.py`. Esquema:
`privacidad/schema_privacidad.sql`.

## Principio de diseño: la norma es un dato, no código

La nota técnica de la historia pide no escribir la lógica como "HIPAA", "GDPR"
o "Ley 1581". Por eso una `PoliticaTratamiento` es configuración de la
institución, que es la responsable del tratamiento:

| Campo | Para qué |
|---|---|
| `jurisdiccion`, `marco_normativo` | Dónde aplica y qué norma dice aplicar la institución (texto de referencia) |
| `finalidades` | Para qué se tratan los datos. Cada una indica si **requiere autorización** registrada |
| `bases_legales` | Bases legales que la institución admite |
| `derechos` | Derechos del titular que reconoce (`acceso`, `rectificacion`, `supresion`, `portabilidad`...) |
| `plazo_respuesta_dias` | Plazo para responder una solicitud |
| `requiere_evidencia_autorizacion` | Si una autorización otorgada debe traer medio y soporte |

Varias jurisdicciones pueden convivir (`politicas_vigentes(conn, jurisdiccion=...)`).
El sistema facilita el cumplimiento; la definición de la base legal, las
políticas y las obligaciones sigue siendo responsabilidad de la institución
(regla de negocio de la historia).

## Criterios de aceptación

| AC | Funciones | Pruebas |
|---|---|---|
| AC1: la institución configura sus normas y políticas | `configurar_politica` (cada cambio publica una **versión nueva**), `politica_vigente`, `politicas_vigentes`, `historial_politica` | `test_configurar_politica_por_jurisdiccion`, `test_varias_jurisdicciones_conviven`, `test_reconfigurar_crea_una_version_nueva_sin_perder_la_anterior` |
| AC2: si el tratamiento requiere autorización, se conserva evidencia de su existencia y estado | `registrar_autorizacion` (otorgada / revocada / denegada, con medio y referencia al soporte), `estado_autorizacion`, `verificar_tratamiento_permitido` | `test_autorizacion_registrada_conserva_evidencia_y_estado`, `test_revocar_deja_nuevo_registro_y_conserva_el_anterior`, `test_verificar_tratamiento_segun_politica` |
| AC3: se identifica la finalidad de lo registrado | Cada autorización guarda su `finalidad`, su `base_legal` y la **versión exacta** de la política (`politica_de_autorizacion`) | `test_finalidad_identificable_con_la_version_de_politica_vigente_entonces` |
| AC4: una solicitud de derechos permite identificar y recuperar la información | `registrar_solicitud_derechos` (plazo tomado de la política), `actualizar_solicitud`, `solicitudes_abiertas` (marca las vencidas) y `recopilar_informacion_titular`, que reúne expediente, autorizaciones, solicitudes y accesos (AUD-01) y exporta a JSON | `test_recopilar_informacion_del_titular_en_todas_las_fuentes`, `test_ciclo_de_vida_de_la_solicitud` |
| AC5: cada acción de consentimiento, autorización o derechos queda en la auditoría | Cada operación exitosa escribe un evento en `eventos_acceso` (AUD-01) en la **misma transacción** que el registro. Tipos nuevos: `configurar_politica_datos`, `registrar_autorizacion` y `gestionar_derechos_titular` | `test_cada_operacion_queda_en_la_traza_de_auditoria`, `test_operacion_rechazada_no_deja_registro_ni_evento` |

## Salvaguardas

- **Solo inserción.** Hay triggers en las cuatro tablas. Una revocación es un
  registro nuevo y el avance de una solicitud es un evento nuevo, así que la
  evidencia de lo que estaba vigente en cada momento nunca se pierde.
- **Fail-closed.** `verificar_tratamiento_permitido` deniega el tratamiento si
  la política no existe, si la finalidad no está declarada o si la última
  autorización no está otorgada.
- Solo se revoca una autorización otorgada vigente. Una solicitud cerrada no
  se reabre, y cerrarla exige dejar por escrito cómo se atendió.

## Límites conocidos

- `recopilar_informacion_titular` **recupera** la información. Ejecutar una
  supresión o rectificación sobre el expediente clínico es una decisión de la
  institución, porque puede chocar con obligaciones de conservación de la
  historia clínica. Aquí queda registrada la solicitud, su resolución y su
  traza.
- Todavía no se exige un rol concreto para configurar políticas o gestionar
  solicitudes. Cuando ADM-01 defina los permisos institucionales, se puede
  agregar la verificación con `seguridad.autorizacion.verificar_permiso`.
