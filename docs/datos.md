# Capas de datos: cBioPortal intocable + capa de trabajo

El copiloto trabaja con pacientes reales desidentificados de cBioPortal
(estudio MSK-CHORD). Esa información **no se modifica**: lo que el sistema
registra (consentimientos, consultas, decisiones, usuarios...) va en otra capa,
que se puede descartar y rehacer en cualquier momento.

```
data/cbioportal/copiloto.db      CAPA BASE — tal como llega de cBioPortal
data/cbioportal/pacientes.db     · índice: 13.159 pacientes de mama y pulmón
                                 · detalle completo de una cohorte de 60
                                   (laboratorios, biomarcadores, imágenes,
                                   tratamientos, episodios y biopsias de HC-04)
           │
           │  python -m datos preparar   (copia + escenario)
           ▼
data/copiloto.db                 CAPA DE TRABAJO — la que usa el sistema
patients/db/pacientes.db         (API, interfaz web, agente, demos)
data/usuarios.db
```

## Comandos

```powershell
python -m datos preparar              # la primera vez: arma la base desde cBioPortal (~2 min) y la capa de trabajo
python -m datos preparar --sin-red    # sin internet: adopta las bases actuales como base
python -m datos estado                # qué hay en cada capa y un paciente de ejemplo por cada caso
python -m datos reiniciar --confirmar # descarta lo registrado y vuelve a base + escenario
python -m datos base                  # completa la base (pacientes de la cohorte que fallaron)
```

- `preparar` no sobrescribe nada sin respaldo. Si había una capa de trabajo
  anterior (las bases de antes de separar capas), la copia primero a
  `data/respaldo_<fecha>/`. Si la capa de trabajo ya está armada, no la toca.
- `demo.py` corre `preparar` solo si hace falta, y trabaja sobre una copia de
  la capa de trabajo.

## El escenario (`datos/escenario.py`)

cBioPortal no trae nada de lo que registra la institución. El escenario lo
agrega siempre igual, usando las funciones del sistema, así que queda la
evidencia, la versión de la política y la auditoría, con fechas pasadas y a
nombre de quien lo haría:

| Qué | Cómo queda |
|---|---|
| **Usuarios** (ADM-01) | Uno por rol, con ids fijos. Contraseña de todos: `Demo-Clave-2026` (**solo para demostración**) |
| **Pacientes** | Los 13.159, repartidos entre los tres oncólogos. Los tres de la demo unificada son de la dra. Gómez |
| **Consentimiento de IA** (SEC-03) | Activado. En la cohorte: **otorgado** (la mayoría), **pendiente** (nunca se registró), **rechazado**, **retirado**, y **retirado y vuelto a otorgar**. Los pacientes del índice sin detalle quedan pendientes |
| **Autorizaciones** (NFR-06) | Política `co-pacientes`: investigación autorizada en una parte de la cohorte y revocada en otra |
| **Consulta de revisión** | Una por paciente de la cohorte (salvo los tres de la demo, que la registra el oncólogo en vivo). Resume lo que el expediente ya trae de cBioPortal; no inventa síntomas ni datos. Sin una consulta, IA-02 no tiene de qué redactar una nota |

| Usuario | Rol | id |
|---|---|---|
| `admin.copiloto` | administrador | 1 |
| `dra.gomez` | oncóloga (pacientes de la demo) | 2 |
| `dr.vega` | oncólogo | 3 |
| `dra.rios` | oncóloga | 4 |
| `enf.mora` | enfermería | 5 |
| `adm.lopez` | administrativo | 6 |
| `auditor` | auditor | 7 |
| `adm.clinico` | administrador clínico | 8 |
| `direccion` | director médico | 9 |

`python -m datos estado` muestra un paciente real de ejemplo para cada estado
de consentimiento (p. ej. `pendiente=P-0018269`), para mostrar en vivo cómo la
IA se bloquea o se habilita.

Lo que cBioPortal no trae y requiere juicio clínico (T/N/M, ECOG, línea de
tratamiento) **no se inventa**. Queda faltante, y el sistema lo maneja como tal
(EST-03, HC-05).

## Para el equipo

- La primera vez después de traer estos cambios: `python -m datos preparar`.
  Sus bases anteriores quedan en `data/respaldo_<fecha>/`.
- **Los pacientes ya no son todos del oncólogo 1.** Las demos usan la constante
  `datos.escenario.ONCOLOGO_DEMO_ID` (la dra. Gómez, id 2), en lugar de un 1
  fijo en el código.
- Para que el sistema no espere a internet al abrir un paciente (NFR-01): los
  60 de la cohorte ya tienen el detalle. Los demás se traen al abrirlos, salvo
  con `COPILOTO_DETALLE_BAJO_DEMANDA=0`.

## Pruebas

```powershell
python -m pytest tests/datos -q
```
