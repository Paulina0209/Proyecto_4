# Demo unificada (datos reales)

Muestra todo lo implementado con un solo comando, sobre **pacientes reales
desidentificados de cBioPortal** (estudio MSK-CHORD). No usa datos
inventados.

```powershell
python demo.py                  # todo, con pausa (Enter) entre secciones
python demo.py --sin-pausa      # de corrido (~45 s la primera vez, ~40 s después)
python demo.py --lista          # secciones disponibles
python demo.py --solo ia tx     # solo algunas secciones
python demo.py --sin-red        # sin OpenAI ni cBioPortal (la base ya debe estar preparada)
```

## Qué hace

1. **Prepara la base real si falta.** Trae de cBioPortal el índice de
   MSK-CHORD (13.159 pacientes de mama y pulmón) a `data/copiloto.db` y
   `patients/db/pacientes.db`, y el detalle de los tres pacientes de la
   demo. Necesita internet solo la primera vez.
2. **Trabaja sobre una copia** en `%TEMP%\copiloto_demo\bd`: lo que la demo
   registra (un paciente nuevo, una nota, decisiones) no queda en la base real.
3. **Pacientes de la demo** (vivos, con historial coherente):

| Paciente | Caso |
|---|---|
| P-0012063 | Adenocarcinoma de pulmón metastásico, sin mutación impulsora en el panel |
| P-0016350 | Adenocarcinoma de pulmón metastásico con EGFR L858R, en osimertinib, con progresión por imagen |
| P-0008538 | Carcinoma de mama estadio IV tratado con quimioterapia |

cBioPortal no trae notas de consulta ni variables que requieren juicio
clínico (T/N/M, entorno de la enfermedad, línea de tratamiento, conciliación
de medicamentos). En la demo las registra el oncólogo y se muestran con el
símbolo ✎.

## Secciones

| Clave | Historias | Qué se ve |
|---|---|---|
| `sec` | SEC-01 | Registro de usuarios, login, permisos por rol y bloqueo tras 5 intentos |
| `pac` | PAC-01/02/03, HC-01 | Búsqueda entre 13.159 pacientes reales, registro (duplicado e inválido), dashboard 360 y detalle traído de cBioPortal al abrir un paciente |
| `hc` | HC-01, HC-05 | Historia importada e información faltante para decidir |
| `ia` | IA-01 a IA-06 | Preguntas en lenguaje natural (con aclaraciones), recomendación explicable, nota SOAP con GPT a partir de la consulta del oncólogo (revisión y aprobación) y resumen para junta con GPT |
| `dx` | DX-01/02/03 | Estudios sugeridos, diferencial sustentado en la imagen de progresión y juicio del médico |
| `est` | EST-01/02/03 | Estadificación incompleta con datos de cBioPortal; el oncólogo registra M1 y confirma IV |
| `tx` | TX-01 a TX-04 | La guía pide los datos que faltan, el oncólogo los registra, opciones con nivel de evidencia, interacciones, decisión registrada, caso con EGFR sin guía computable y el agente con GPT |
| `ev` | EV-01, CFG-01 | Evidencia para el paciente y guías institucionales por rol |
| `doc` | DOC-02, DOC-01 | Resumen y expediente exportados a PDF; carga del PDF al expediente |
| `aud` | AUD-01/02 | Accesos registrados y trazabilidad IA vs. médico de lo que hizo la demo |
| `priv` | NFR-06 | Autorización de tratamiento de datos por finalidad (otorgar y revocar) |

Para explorar a mano:

- `python demo_ia01.py`: preguntas, recomendaciones y evidencia.
- `python demo_tx.py`: agente de tratamiento.
- `python -m patients.demo`: búsqueda, 360, laboratorios (HC-02: valores críticos, conflictos y tendencias) y biopsias y biomarcadores (HC-04). Ver `docs/PACIENTES_DEMO.md`.

Las tres trabajan sobre la base real.

### Qué esperar de `demo_tx.py`

El agente usa GPT y trabaja sobre los pacientes con historia cargada (por
ejemplo 6788 = P-0012063, 7328 = P-0016350). Preguntas que funcionan:

- *"¿Qué biomarcadores clave tiene el paciente 7328 y están confirmados?"*: distingue un biomarcador pendiente (HC-04) de uno confirmado.
- *"Para el paciente 6788: disease_setting metastatic, molecular_pathway_status non_oncogene_addicted, treatment_line 1, immunotherapy_contraindication no, major_comorbidity_precluding_ici no, prior_ici no. Dame las opciones de tratamiento con su nivel de evidencia."*: las opciones de la guía con su evidencia (TX-01/02).

**Guardar datos, revisar interacciones y registrar la decisión (TX-03/TX-04).**
El agente puede guardar en el expediente los datos que le da el oncólogo, pero
solo con su aprobación. Cada vez que va a guardar algo, la demo muestra la
acción y pregunta *"¿Aprobar (a) o rechazar (r)?"*. Flujo de ejemplo:

1. *"Para el paciente 6788 guarda estos datos: disease_setting metastatic, molecular_pathway_status non_oncogene_addicted, treatment_line 1, immunotherapy_contraindication no, major_comorbidity_precluding_ici no, prior_ici no."* → pausa, aprobar (`a`).
2. *"El paciente no toma ninguna medicación concomitante, guárdalo. Luego dame las opciones de tratamiento y revisa interacciones de la primera opción."* → pausa por la conciliación, aprobar; después muestra las opciones y las interacciones.
3. *"Registra como decisión final que acepto la primera opción."* → pausa; aprobar la registra y rechazar (`r`, con un motivo) no guarda nada.

Lo que se aprueba queda en la base real. Los biomarcadores no se guardan por
chat: se registran con su biopsia (HC-04, `python -m patients.demo`).

## Qué necesita

- Las dependencias de `requirements.txt`.
- Para GPT: `OPENAI_API_KEY` en el `.env` (modelo por defecto `gpt-6-luna`;
  ver `docs/llm_openai.md`). Sin llave, las secciones de IA usan el cliente
  por reglas y el agente se omite.
- Internet la primera vez (cBioPortal). Después, `--sin-red` funciona sin conexión.
