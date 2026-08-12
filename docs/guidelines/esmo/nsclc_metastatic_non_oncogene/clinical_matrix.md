# Matriz clínica: ESMO NSCLC metastásico sin oncogén conductor

## Estado

Borrador computable pendiente de validación clínica.

## Inventario de reglas relacionadas con pembrolizumab

| ID | Escenario | Consecuente | Evidencia nativa | Efecto de auditoría |
|---|---|---|---|---|
| FL-001 | Primera línea, ECOG 0-1, PD-L1 >=50, no nunca fumador | Pembrolizumab monoterapia | I, A; MCBS 5 | Respalda |
| FL-002 | Primera línea, no escamoso, ECOG 0-1 | Pembro + pemetrexed + platino, luego mantenimiento | I, A; MCBS 4 | Respalda |
| FL-003 | Primera línea, escamoso, ECOG 0-1 | Pembro + carboplatino + taxano, luego mantenimiento | I, A; MCBS 4 | Respalda |
| FL-004 | Primera línea, ECOG 2, PD-L1 >=50 | ICI monoterapia puede considerarse | III, B | Respalda condicional |
| FL-005A/B | PD-L1 >=50 y necesidad de reducción rápida | Preferir combinación según histología | IV, B | Preferencia contextual |
| SL-001 | Segunda línea o posterior, ECOG 0-2, sin ICI previa, PD-L1 >=1 | Pembrolizumab monoterapia | I, A; MCBS 5 | Respalda |
| SL-002 | Beneficio sustancial previo y suspensión no debida a progresión/toxicidad grave | Reexposición anti-PD-(L)1 puede considerarse | III, B | Respalda condicional |
| EXC-001 | Primera línea, PD-L1 <50 y monoterapia prescrita | Monoterapia no recomendada | I, D | Posible desviación |
| EXC-002 | Nunca fumador y monoterapia prescrita | Monoterapia no recomendada | I, D | Posible desviación |
| EXC-003 | ECOG 2 y combinación quimio-ICI | Revisión experta | Sin gradación explícita | Revisión |
| EXC-004 | ECOG 3-4 y pembrolizumab prescrito | Ruta no respaldada; BSC recomendado | III, A | Posible desviación |
| CONT-001 | 24 meses o más de ICI | Revisar posible discontinuación | I, A | Aviso |
| CONT-002 | Durante tratamiento | Ajustar duración a eficacia/tolerabilidad | IV, A | Aviso |

## Decisiones metodológicas

- Las reglas de clase se identifican como `class_level`.
- Los límites inferidos no reciben grados inventados.
- La recomendación positiva no se invierte automáticamente.
- La prioridad de la alerta se deriva después de establecer concordancia.
- Las reglas deben validarse con oncología antes de usarse sobre historias reales.
