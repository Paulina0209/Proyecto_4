# Demo del módulo de pacientes (PAC-02, PAC-03, HC-02, HC-04)

`python -m patients.demo` es un cliente de consola que usa la API de
pacientes como lo haría el oncólogo:

- buscar pacientes;
- abrir su resumen 360;
- registrar y revisar laboratorios (HC-02);
- registrar biopsias y biomarcadores, y confirmar los pendientes (HC-04).

Trabaja sobre pacientes reales desidentificados de cBioPortal (MSK-CHORD).
Para ver todo el copiloto de una vez está la demo unificada
(`docs/DEMO_UNIFICADA.md`); esta se centra en el módulo de pacientes.

## Demo guiada (automática y luego interactiva)

```powershell
python demo_laboratorios_biomarcadores.py              # con pausa (Enter) entre pasos
python demo_laboratorios_biomarcadores.py --sin-pausa  # de corrido
python demo_laboratorios_biomarcadores.py --solo-auto  # sin el menú al final
python demo_laboratorios_biomarcadores.py --sin-ia     # sin la pregunta al agente (GPT)
```

**No hace falta levantar la API aparte.** La demo:

1. **Prepara una copia.** Copia la base real a `%TEMP%\copiloto_demo_hc02_hc04`, la deja como recién importada de cBioPortal (descarta lo registrado a mano en pruebas anteriores) y levanta la API sobre esa copia. La base real no se modifica.
2. **Ejecuta solo el guion de este documento:**
   - HC-02: valor crítico, doble validación, HL7, conflicto, alertas en el 360, revisión y tendencia;
   - HC-04: biopsia vinculada, confirmación del EGFR, PD-L1 manual y validación estricta;
   - la pregunta al agente de TX con GPT.

   En cada criterio de aceptación verifica el resultado (**CUMPLE** / **NO CUMPLE**) y al final muestra un resumen (`17/17 verificaciones cumplen`).

   Los resultados se resaltan en negrilla y color, sin íconos: verde (CUMPLE, GUARDADO, ACCIONABLE), rojo (RECHAZADO, VALOR CRÍTICO, NO CUMPLE) y amarillo (CONFLICTO, POR CONFIRMAR, SIN REGISTRAR). Si la salida se redirige a un archivo, sale como texto plano.
3. **Abre el menú normal** de `python -m patients.demo` sobre esa copia, con todo lo anterior cargado, para seguir interactuando.

El resto de este documento describe la demo manual (`python -m patients.demo` con la API aparte).

## Cómo funciona por dentro

```text
python -m patients.demo  ──HTTP──▶  uvicorn patients.api:app
                                        │
                     ┌──────────────────┴───────────────────┐
                     ▼                                      ▼
       patients/db/pacientes.db                   data/copiloto.db (expediente)
       búsqueda (PAC-02), 360 (PAC-03)    laboratorios, alertas, conflictos (HC-02)
                                          biopsias, biomarcadores (HC-04)
                                          ── lo mismo que lee TX-01
```

- La demo no guarda nada por su cuenta: todo pasa por la API, que actúa como el **oncólogo 1** y solo le muestra sus pacientes.
- Lo que la demo registra queda en las bases reales (no en una copia, a diferencia de la demo unificada).

## 1. Preparar los datos (una vez)

La demo usa la base real del copiloto, la misma que prepara la demo unificada.
Si todavía no existe `data/copiloto.db`, ejecute una vez (necesita internet):

```powershell
python demo.py --solo pac
```

Eso trae de cBioPortal el índice de MSK-CHORD (13.159 pacientes de mama y
pulmón) y el detalle de los tres pacientes de la demo:

| Id en la demo | Paciente | Qué tiene para mostrar |
|---|---|---|
| 7328 | P-0016350 | Adenocarcinoma de pulmón metastásico, con EGFR L858R importado (pendiente de confirmar) y una biopsia por muestra secuenciada |
| 741 | P-0008538 | Carcinoma de mama estadio IV, con series largas de CA 15-3 y CEA. Trae 5 conflictos reales de cBioPortal: el mismo día con valores distintos |
| 6788 | P-0012063 | Adenocarcinoma de pulmón metastásico, sin mutación impulsora en el panel |

Los ids salen del índice, así que son los mismos en cualquier equipo que
prepare la base con la misma versión de cBioPortal. Si no coinciden, busque al
paciente por nombre (opción 2, por ejemplo `P-0016350`).

> No borre ni mueva `patients/db/pacientes.db`: se perdería la base preparada.
> Solo si la API responde 500 al listar pacientes (base creada con una versión
> anterior del importador, con el tipo `cbioportal`), renómbrela y vuelva a
> ejecutar `python demo.py --solo pac`.

## 2. Arrancar

```powershell
uvicorn patients.api:app --reload        # terminal 1
python -m patients.demo                  # terminal 2
```

## 3. Guion

**1. Buscar (opción 2 → `P-0016350`).** Aparece entre 13.159 pacientes reales, con su diagnóstico y estado.

**2. Resumen 360 del paciente 7328 (opción 4 → `7328`):**
- diagnóstico y tratamiento salen de cBioPortal;
- **Biomarcadores clave:** `POR CONFIRMAR EGFR … L858R → Inhibidor de tirosina quinasa de EGFR`;
- en las alertas, "Biomarcador por confirmar".

Punto para comentar: una variante importada nunca se usa como "positiva" sin que la confirme el oncólogo.

**3. Valor crítico (opción 5 → `7328` → `R`).** Registre:

| Campo | Valor |
|---|---|
| Identificación | `P-0016350` (también acepta la completa `CBIO:msk_chord_2024:P-0016350`) |
| Nombre | `Paciente P-0016350` |
| Prueba / valor / unidad | `Potasio` / `7.1` / `mmol/L` |
| Fecha / hora / rango | la de hoy / `07:30` / `3.5-5.1` |

Resultado: `VALOR CRÍTICO: > 6.5 mmol/L (crítico alto)`.

**4. Conflicto (`R` otra vez).** Registre el mismo momento con otro valor y otro nombre de la prueba: `K`, `4.4`, `mmol/L`, la misma fecha, `07:30`.

Resultado: `CONFLICTO: … (7.1 y 4.4). Ninguno se sobrescribió`. "K" y "Potasio" se reconocen como la misma prueba.

**5. Doble validación (`R` con el nombre `Juan Perez`).**

Resultado: `RECHAZADO identificacion: … no coincide … No se guardó el resultado.`

**6. Tendencia con datos reales (opción 5 → `741` → número del marcador).**
- La serie de CEA o CA 15-3 de P-0008538, con barras.
- Arriba aparece `Advertencia: Hay resultados en conflicto pendientes de revisión`, y algunos puntos están marcados "en conflicto". cBioPortal solo da el día, no la hora, así que HC-02 compara por día y no puede descartar que dos valores distintos del mismo día sean del mismo momento.

**7. El 360 otra vez (opción 4 → `7328`).** Ahora hay tres alertas, ordenadas por severidad:
- **Laboratorio crítico** (alta);
- **Conflicto de laboratorio** (media);
- **Biomarcador por confirmar** (media).

En el acceso rápido, los dos potasios aparecen "(en conflicto)".

**8. Revisar (opción 6 → `7328`):**
- `A` + el número de la alerta (p. ej. `A1`) y quien revisa → la alerta deja el 360;
- `C` + el número del conflicto (p. ej. `C11`) → `1` (válido A), quien resuelve y una nota → el conflicto queda resuelto, y los dos resultados se conservan.

Use los números que muestra la lista: no son consecutivos.

**9. Confirmar el biomarcador (opción 7 → `7328`):**
- se ve la biopsia de la muestra secuenciada, vinculada a su episodio, y el EGFR pendiente;
- escriba `C` seguido del **número `#` que aparece junto al EGFR** (por ejemplo `C16`), quien confirma y `detectada`;
- respuesta: `LISTO. Ahora: ACCIONABLE`;
- desde ese momento TX-01 recibe `egfr_status=sensitizing_mutation`.

Abra el 360 otra vez: el EGFR aparece como CONFIRMADO y la alerta de "por confirmar" ya no está.

**10. Registrar un biomarcador (opción 7 → `7328` → `M`):**
- elija la biopsia que aparece en la lista; la de otro paciente se rechaza;
- ejemplo válido: `PD-L1`, `cuantificado`, método `22C3`, valor `60`, y en la confirmación `60`. Queda accionable y TX-01 recibe `pdl1_tps=60`;
- ejemplo inválido: `HER2`, `negativo`, método `IHC`, IHC `3+`. Se rechaza con `Con IHC 3+ el estado de HER2 es 'positivo', no 'negativo'` y no se guarda nada.

**11. Biopsia propia (opción 7 → `B`).** Registre un episodio diagnóstico y luego la biopsia: si el paciente tiene un solo episodio, se vincula sola.

> Lo que registre en esta demo queda en la base real. Para volver a empezar,
> restaure una copia de `data/copiloto.db` y `patients/db/pacientes.db`.

## Opciones del menú

| Opción | Historia | Qué permite |
|---|---|---|
| 1 | PAC-02 | Lista de pacientes del oncólogo |
| 2 | PAC-02 | Búsqueda por nombre parcial (sin importar tildes ni mayúsculas) |
| 3 | PAC-02 | Filtros combinables: nombre, diagnóstico, estado de tratamiento y fechas de última consulta |
| 4 | PAC-03 | Resumen 360 |
| 5 | HC-02 | Marcadores; tendencia (número del marcador en la lista) y registro manual (`R`) |
| 6 | HC-02 | Alertas críticas (`A` + número, p. ej. `A1`) y conflictos (`C` + número, p. ej. `C11`) |
| 7 | HC-04 | Biopsia (`B`), biomarcador (`M`), confirmar (`C` + número, p. ej. `C16`) o descartar (`D` + número) |

## Problemas frecuentes

| Síntoma | Causa | Solución |
|---|---|---|
| `ERROR: No se pudo conectar con la API` | La API no está corriendo | `uvicorn patients.api:app` en otra terminal |
| Error 500 al listar o buscar | Base de pacientes de una versión anterior (tipo `cbioportal`) | Renómbrela y ejecute `python demo.py --solo pac` (paso 1) |
| `0 marcador(es)` en un paciente importado | cBioPortal no trae laboratorios de ese paciente | Registre uno (`R`) o use el 741, que tiene CEA y CA 15-3 |
| Al confirmar o resolver: "no tiene el biomarcador/conflicto" | Se usó un número que no es el de la lista | Use el número que aparece en pantalla (`#16` → `C16`, `A1`, `C11`…) |
| `La biopsia N no es del paciente` | Se eligió una biopsia de otro paciente | Use la biopsia que lista la demo para ese paciente |
| `episodio_id: … indique a cuál corresponde` | El paciente tiene varios episodios | La demo pide elegir el episodio |
