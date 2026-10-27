# Skills del agente de tratamiento (`skills/` + `tx_clinica/skills.py`)

El agente de tratamiento (`tx_clinica`) recomienda siempre a partir de las guías clínicas cargadas. Esa
capacidad se reparte en tres piezas con funciones distintas:

| Pieza | Qué es | Dónde está |
|---|---|---|
| **Conocimiento** | Las guías: módulos YAML con reglas, regímenes y evidencia, más su índice vectorial | `guidelines/`, índice de `asistente/` |
| **Acciones** | Las tools: consultar datos, evaluar el caso contra una guía, chequear interacciones, registrar | `tx_clinica/tools/` |
| **Procedimiento** | Cómo trazar la ruta: qué preguntar, en qué orden, cómo leer cada resultado, cuándo parar | `skills/ruta-recomendacion-guias/` |

Una guía no sabe cómo conversar con el oncólogo y una tool no sabe en qué orden usarse. Ese «cómo» antes vivía
mezclado con las reglas de seguridad dentro de un prompt de 146 líneas; ahora es una **skill** en el formato
abierto de [agentskills.io](https://agentskills.io/specification): una carpeta con un `SKILL.md` (frontmatter
YAML + instrucciones) y, si hace falta, `references/`, `scripts/` y `assets/`.

## Cómo la usa el agente (divulgación progresiva)

```
arranque      el prompt trae solo el catálogo:   <skills_disponibles> nombre: descripción </skills_disponibles>
                │
petición      el oncólogo pide una recomendación
                │   el modelo llama  activar_skill("ruta-recomendacion-guias")
                ▼
activación    recibe el cuerpo de SKILL.md (pasos 1 a 8) y la lista de archivos de apoyo
                │   sigue el procedimiento: módulo → variables → tool de recomendación → interacciones
                ▼
recurso       al llegar a «registrar la decisión», carga references/registro-de-decision.md
              con  activar_skill("ruta-recomendacion-guias", recurso="references/registro-de-decision.md")
```

Así el contexto del modelo no carga el procedimiento completo en conversaciones que solo consultan un dato, y
el detalle de registrar decisiones solo se carga cuando se llega a ese paso.

## Qué quedó en el prompt y qué pasó a la skill

El criterio: **lo que protege al paciente y al expediente se queda en el prompt y en los middlewares**, porque
tiene que valer aunque el modelo no active ninguna skill. **Lo que ordena el trabajo pasa a la skill.** El
historial del proyecto muestra por qué (el modelo no siempre sigue el prompt: reutilizaba turnos anteriores,
inventaba variables), así que ninguna regla de seguridad depende de que la skill se cargue.

| Se queda en `system_prompt.py` (siempre vigente) | Pasa a la skill |
|---|---|
| La decisión es del oncólogo; esto es apoyo, no prescripción | Paciente registrado o caso del chat (paso 1) |
| Prohibido inventar o asumir valores clínicos | Identificar el módulo y desambiguar (paso 2) |
| Recomendar solo con la tool; citar solo lo que devolvió; no reutilizar turnos anteriores | Mapear valores, derivaciones válidas, tratamiento planificado frente a recibido, variables `obligatoria_para_elegibilidad` (paso 3) |
| `requiere_mas_datos` no es «sin guía aplicable» | Qué tool llamar en cada situación (paso 4) |
| Mencionar `advertencia_comorbilidad` | Cómo leer cada resultado y cómo completar los datos que faltan (paso 5) |
| Chequear interacciones antes de decidir; nunca decir «sin interacciones» si falta conciliación o contenido; `blocks_confirmation` y `requires_justification` | Cómo presentar los candidatos (paso 6) y qué hacer con cada resultado de interacciones (paso 7) |
| No registrar nada sin decisión explícita; las escrituras pasan por aprobación humana | `accept` frente a `modify` frente a `reject`, qué se guarda y qué no (paso 8 y `references/registro-de-decision.md`) |

Algunas reglas aparecen en las dos columnas a propósito: el prompt dice el **qué nunca**, la skill dice el
**cómo**. Si alguna vez chocan, el prompt indica que prevalecen las reglas obligatorias.

## Tres garantías que no dependen del modelo

1. **Control de activación** (`tx_clinica/middleware/exigir_skill.py`). Si el modelo llama una tool de la ruta
   (`listar_variables_requeridas`, las tres de recomendación y `chequear_interacciones_tratamiento`) sin haber activado
   la skill en esa conversación, la tool **no se ejecuta**: el modelo recibe un error que le dice qué activar y
   reintenta. Solo cubre tools de lectura; consultar los datos de un paciente no la exige. Leer únicamente un
   archivo de `references/`, o activar un nombre inventado, no cuenta como activar.
2. **Aprobación humana** (sin cambios, `human_in_the_loop.py`): las tres tools que escriben en el expediente se
   pausan hasta que el médico apruebe o rechace en pantalla.
3. **Arranque estricto** (`construir_agente`): si falta la skill requerida o está mal formada (nombre distinto de
   la carpeta, descripción vacía, frontmatter roto…), el agente **no se construye** y dice por qué, en vez de
   funcionar en silencio sin su procedimiento.

## Cómo agregar o cambiar una skill

1. Crea `skills/<nombre>/SKILL.md`. El `name` del frontmatter debe ser igual al nombre de la carpeta
   (minúsculas, dígitos y guiones; hasta 64 caracteres). La `description` (hasta 1024) debe decir **qué hace y
   cuándo usarla**: es lo único que ve el modelo para decidir si la activa.
2. Mantén `SKILL.md` por debajo de 500 líneas; el detalle que no hace falta siempre va a `references/` y se
   enlaza desde el cuerpo (los archivos de apoyo se enlazan a un solo nivel de profundidad).
3. Si debe ser obligatoria para el agente, agrégala a `SKILLS_REQUERIDAS` en `tx_clinica/skills.py`; si además
   gobierna tools, agrégalas a `TOOLS_QUE_EXIGEN_SKILL` en el middleware.
4. Valídala: `python -m pytest tests/tx_clinica/test_skills.py tests/tx_clinica/test_skill_agente.py`. Si quieres la
   comprobación del validador de referencia (necesita Python 3.11 o más; con `uv` no toca tu entorno):
   `uvx --python 3.12 --from skills-ref agentskills validate skills/<nombre>`. La skill actual la pasa.
5. Las skills se leen una vez por proceso: reinicia el servidor para que un cambio surta efecto.

`COPILOTO_SKILLS_DIR` reemplaza la carpeta de skills (pruebas, despliegues). Debe apuntar a una carpeta de
confianza: el contenido de una skill se entrega al modelo como instrucciones, igual que el prompt.

## Pruebas

```
python -m pytest tests/tx_clinica/test_skills.py tests/tx_clinica/test_skill_agente.py -q
```

- `test_skills.py`: validación contra la especificación (nombre, descripción, campos, tamaño), descubrimiento,
  catálogo sin cuerpo, activación, y que ningún recurso se pueda leer fuera de la skill (`..`, rutas absolutas,
  enlaces simbólicos, binarios, archivos enormes).
- `test_skill_agente.py`: que las reglas de seguridad siguen en el prompt; que **no se perdió ninguna instrucción**
  del prompt original (cada identificador sigue en el prompt o en la skill); que los textos no inventan tools; el
  control de activación dentro de un agente real de LangGraph con un modelo guionado; y la construcción del agente.

## Límites

- **No se verificó con un GPT real.** Las pruebas usan un modelo guionado: demuestran que el control bloquea, que la
  skill se carga y que nada se perdió, pero no que un modelo concreto decida activar la skill por su cuenta ni que
  siga bien sus pasos. Para eso hay que correr conversaciones reales (`python demo_tx.py` o la pantalla del
  expediente) y revisar la traza en Langfuse: debe verse `activar_skill` antes de la primera tool de recomendación.
  Con un modelo que se salte la activación, el control lo corrige con un intento extra.
- **Cuesta una llamada más** por conversación que pida una recomendación, y el cuerpo de la skill (unas 1 200 palabras)
  entra en el contexto de esa conversación.
- **Llamadas en paralelo:** si el modelo pide en el mismo turno `activar_skill` y una tool de recomendación, la
  segunda se rechaza (aún no hay activación en el historial) y el modelo la repite en el siguiente paso.
- **`allowed-tools`** se acepta y se valida como campo de la especificación, pero no se aplica: el control de tools
  lo hacen el middleware y la aprobación humana.
- Hay **una sola skill**. El mecanismo está listo para más (por ejemplo, una por tipo de apoyo a la decisión), pero
  no se crearon sin una necesidad real.
