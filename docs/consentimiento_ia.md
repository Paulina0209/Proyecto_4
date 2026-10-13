# SEC-03 — Consentimiento informado y privacidad

> Como paciente/institución, quiero que el sistema gestione el consentimiento
> informado sobre el uso de los datos y de la IA, para cumplir la normativa de
> protección de datos de salud.

```
Dado un paciente nuevo
Cuando se crea su historia clínica
Entonces el sistema exige registrar el consentimiento informado antes de
habilitar las funciones de IA sobre sus datos

Dado que un paciente retira su consentimiento
Cuando se registra el retiro
Entonces las funciones de IA dejan de aplicarse a su historia clínica, sin
borrar la historia existente
```

Módulo: `privacidad/consentimiento_ia.py`.

## Diseño: una autorización de NFR-06

El consentimiento es una autorización de la finalidad `asistencia_ia` dentro de
la política `consentimiento-ia` (ver `docs/privacidad.md`). Por eso hereda,
sin código nuevo:

- **Solo inserción.** Retirar es un registro nuevo (`revocada`). El
  consentimiento anterior y la historia clínica no se tocan, y los triggers
  impiden borrarlos.
- **Evidencia obligatoria.** Sin medio y soporte del documento firmado, no se
  registra.
- **Versión exacta de la política** vigente cuando el paciente firmó.
- **Auditoría (AUD-01)** de cada registro y de cada retiro, en la misma
  transacción.

## Activación

La exigencia rige en una base desde que la institución activa la política
(`activar_consentimiento_ia`). Desde ese momento es fail-closed: un paciente
sin consentimiento otorgado vigente, nuevo o antiguo, queda sin IA.

- La API de pacientes la activa sola la primera vez que abre el expediente.
- `demo.py` la activa sobre su copia y registra el consentimiento de sus tres
  pacientes.
- Una base donde nunca se activó, como las bases en memoria de las pruebas de
  cada módulo, no aplica la exigencia.

> **Para el equipo:** si se levantó la API sobre `data/copiloto.db`, ese
> expediente ya exige consentimiento. Para usar `demo_tx.py` o
> `demo_ia01.py` con un paciente, primero hay que registrarlo:
> `python -m privacidad.consentimiento_ia otorgar 6788 --medio escrito --soporte doc-6788`.

## Dónde se exige

Justo antes de armar lo que se le entrega a cada función de IA:

| Función | Punto de control |
|---|---|
| IA-01 / IA-06, consultas en lenguaje natural | `NaturalLanguageClinicalQueryService.ask` responde que falta el consentimiento y no entrega ningún dato |
| IA-02, borrador de nota | `expediente.adapters.construir_contexto_clinico` |
| IA-04, resumen para junta | `construir_contexto_resumen_caso` |
| DX-02 / IA-05, diferencial y explicabilidad | `obtener_hallazgos_de_paciente` |
| EST-01, propuesta de estadificación | `proponer_estadificacion` |
| Agente de tratamiento (TX-01 a TX-04) | `obtener_paciente_o_error`, que comparten todas las tools: devuelve `consentimiento_ia_requerido` y el agente se lo comunica al oncólogo |

Leer la historia clínica sin IA (resumen 360, exportación a PDF, laboratorios)
no cambia. La confirmación manual del estadio (EST-02) tampoco depende de la
propuesta automática.

## API

| Método | Ruta | Qué hace |
|---|---|---|
| `GET` | `/pacientes/{id}/consentimiento-ia` | Estado: `pendiente`, `otorgada`, `revocada` o `denegada`, y si la IA está habilitada. Un paciente recién creado aparece `pendiente` |
| `POST` | `/pacientes/{id}/consentimiento-ia` | `{"medio", "soporte", "otorgado": true}`. Con `otorgado: false` registra que el paciente no lo otorgó |
| `POST` | `/pacientes/{id}/consentimiento-ia/retiro` | Retiro; la historia clínica no se borra |

Línea de comandos, sobre el expediente real:

```powershell
python -m privacidad.consentimiento_ia estado 6788
python -m privacidad.consentimiento_ia otorgar 6788 --medio escrito --soporte doc-6788
python -m privacidad.consentimiento_ia retirar 6788
```

**Roles (NFR-04).** Si se pasa `usuario`, registrar o retirar exige
`Accion.REGISTRAR_CONSENTIMIENTO_IA` (oncólogo, enfermería o administrativo),
y activar la política exige `Accion.CONFIGURAR_POLITICA_DATOS`
(administrador clínico).

## Pruebas y demo

```powershell
python -m pytest tests/privacidad/test_consentimiento_ia.py -q
python demo_seguridad_cumplimiento.py --solo sec03
```
