# Demo unificada

Muestra todo lo implementado hasta ahora con un solo comando, siguiendo el
recorrido de un paciente: acceso seguro, registro y búsqueda, historia
clínica, asistente de IA, diagnóstico, estadificación, tratamiento, evidencia,
documentos, auditoría y privacidad.

```powershell
python demo.py                  # todo, con pausa (Enter) entre secciones
python demo.py --sin-pausa      # de corrido (~20 s)
python demo.py --lista          # secciones disponibles
python demo.py --solo ia tx     # solo algunas secciones
python demo.py --sin-red        # sin OpenAI ni cBioPortal
```

## Secciones

| Clave | Historias | Qué se ve |
|---|---|---|
| `sec` | SEC-01 | Login, permisos por rol y bloqueo tras 5 intentos fallidos |
| `pac` | PAC-01/02/03 | Registro (duplicado y datos inválidos), búsqueda con filtros y dashboard 360, por la API HTTP real |
| `hc` | HC-01, HC-05, DOC-01 | Importación FHIR (y rechazo de un mensaje de otro paciente), información faltante y carga de documentos |
| `cbio` | HC-01 + cBioPortal | Un paciente real desidentificado de MSK-CHORD, importado en vivo |
| `ia` | IA-01 a IA-06 | Preguntas en lenguaje natural (con aclaraciones), recomendaciones explicables, nota SOAP con revisión y aprobación, y resumen para junta médica con GPT |
| `dx` | DX-01/02/03 | Estudios sugeridos, diagnóstico diferencial e incertidumbre |
| `est` | EST-01/02/03 | Estadificación propuesta, ajuste manual y completitud |
| `tx` | TX-01 a TX-04 | Opciones según la guía con nivel de evidencia, interacciones, y el agente conversacional con GPT |
| `ev` | EV-01, CFG-01 | Evidencia para el paciente y guías institucionales por rol |
| `doc` | DOC-02 | Resumen y expediente exportados a PDF |
| `aud` | AUD-01/02 | Log de accesos y trazabilidad de sugerencias de IA frente a decisiones del médico |
| `priv` | NFR-06 | Autorización de tratamiento de datos por finalidad (otorgar y revocar) |

## Qué necesita

- Las dependencias de `requirements.txt`.
- Para GPT: `OPENAI_API_KEY` en el `.env` (ver `docs/llm_openai.md`). Sin llave,
  las secciones de IA usan el cliente por reglas y lo avisan; el agente de
  tratamiento se omite.
- Para `cbio`: internet. Sin conexión, la sección lo avisa y la demo sigue.

## Datos y archivos

Todo corre en bases SQLite en memoria o en una carpeta temporal
(`%TEMP%\copiloto_demo`, donde quedan los PDFs y documentos cargados). No
modifica `data/` ni `patients/db/`. Si una sección falla, se muestra el error
y la demo continúa con las demás.

Las demos individuales de cada historia siguen existiendo; `demo.py` las
reutiliza y agrega guiones fijos para las que eran interactivas
(`demo_ia01.py` y `demo_tx.py`, que siguen disponibles para explorar a mano).
