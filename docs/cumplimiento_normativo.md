# NFR-04 — Cumplimiento normativo (HIPAA / GDPR / norma local)

> Como institución, quiero que los datos personales y clínicos se manejen con
> controles de privacidad y seguridad alineados con la normativa aplicable,
> para proteger la información sensible de los pacientes durante su
> almacenamiento, procesamiento y transmisión.

Regla de negocio: los datos clínicos son información sensible, y su acceso y
tratamiento se limita a finalidades y usuarios autorizados, con
minimización y mínimo privilegio. Como en NFR-06, la norma concreta la define
la institución: el sistema aplica y verifica los controles técnicos, pero no
certifica el cumplimiento legal.

## Controles por criterio de aceptación

La nota técnica pide integrar SEC-01, SEC-02, SEC-03 y AUD-01, y documentar los
mecanismos. Esto es lo que responde a cada criterio:

| AC | Criterio | Mecanismo | Dónde |
|---|---|---|---|
| AC1 | Lo que se persiste se protege con los mecanismos definidos | AES-256-GCM para documentos y respaldos de las bases; clave fuera del repositorio | SEC-02, `seguridad/cifrado.py`, `docs/seguridad_cifrado.md` |
| AC2 | La transmisión es segura y cifrada | TLS ≥ 1.2; las APIs rechazan HTTP (403) y envían HSTS; las integraciones solo van por HTTPS | SEC-02, `seguridad/tls.py` |
| AC3 | El acceso depende de la identidad, el rol y los permisos | Tabla `PERMISOS_POR_ROL` (fail-closed). Nuevas acciones `REGISTRAR_CONSENTIMIENTO_IA` y `CONFIGURAR_POLITICA_DATOS`. El administrador del sistema no tiene acceso clínico | SEC-01, ADM-01, `seguridad/autorizacion.py` |
| AC4 | Toda acción relevante sobre datos sensibles deja traza (AUD-01) | `eventos_acceso`, que ahora es de **solo inserción también en la base** (triggers nuevos). Consentimientos, autorizaciones, solicitudes de derechos, accesos al expediente, gestión de usuarios y guías | AUD-01, `auditoria/schema_auditoria.sql` |
| AC5 | A la IA solo llega lo estrictamente necesario y autorizado | **Autorizado:** sin consentimiento vigente no se arma contexto (SEC-03). **Necesario:** el texto libre sale seudonimizado (nombre, documento, teléfono, correo → marcadores), el agente ya no recibe el nombre y el paciente se referencia por su id interno | `privacidad/minimizacion.py`, `expediente/adapters.py`, `tx_clinica/tools/patients_tools.py` |

### AC5 en detalle

```
Nota dictada:            María Fernanda Ríos refiere fatiga leve. Documento SINT-0001,
                         teléfono 300 123 4567, correo maria.rios@correo.example. Hemoglobina 11.2 g/dL.
Lo que recibe el modelo: [PACIENTE] refiere fatiga leve. Documento [DOCUMENTO],
                         teléfono [TELÉFONO], correo [CORREO]. Hemoglobina 11.2 g/dL.
```

`seudonimizar_texto` reemplaza el nombre del propio paciente (completo y cada
palabra), sus documentos (incluido el id corto de cBioPortal) y cualquier
correo o teléfono. Los valores clínicos no se tocan: el patrón de teléfono
exige 10 dígitos o un prefijo para no confundirse con resultados de
laboratorio. La máscara de Langfuse (`tx_clinica/observability.py`) sigue como
segunda barrera.

## Informe de cumplimiento

```powershell
python -m privacidad.cumplimiento           # sobre la instalación real (solo lectura)
python -m privacidad.cumplimiento --json
python -m privacidad.cumplimiento --documentos ruta/documentos.db
```

Revisa cada control contra la instalación concreta y lo marca como `cumple`,
`atención` o `falla`. El código de salida es 1 si algo falla, así que sirve
también en un pipeline de despliegue.

| Control | Falla si… |
|---|---|
| Clave de cifrado | no hay clave (`atención` si está en un archivo local en vez del gestor de secretos) |
| Documentos cifrados | hay documentos en claro en disco |
| Certificado TLS | falta, no carga o venció (`atención` si vence en menos de 30 días) |
| APIs solo HTTPS | alguna API no tiene `SoloHTTPSMiddleware` |
| Integraciones | `COPILOTO_PACS_URL`, `COPILOTO_VISOR_URL`, `OPENAI_BASE_URL` o `LANGFUSE_HOST` usan `http://` hacia la red |
| Permisos por rol | el administrador del sistema tiene alguna acción clínica |
| Auditoría | falta `eventos_acceso` o no está protegida contra cambios |
| Consentimiento de IA | la exigencia no está activada en el expediente |
| Minimización | un caso sintético deja pasar algún identificador al prompt |

## Riesgos que quedan

- La API de pacientes todavía recibe el `oncologo_id` como parámetro, sin
  sesión autenticada (`TODO(SEC-01)` en `patients/api.py`). El control por
  rol se aplica en los módulos (`usuario=`) y en ADM-01, pero no en cada
  endpoint de esa API.
- El cifrado de las bases SQLite en uso depende del volumen (ver SEC-02).

## Pruebas y demo

```powershell
python -m pytest tests/privacidad/test_cumplimiento.py -q
python demo_seguridad_cumplimiento.py --solo nfr04
```
