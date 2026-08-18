# Arquitectura del proyecto

## Versión

Arquitectura base v1.1.

## Decisión arquitectónica

El sistema separa cinco responsabilidades:

1. extracción y normalización de hechos clínicos;
2. navegación por rutas clínicas;
3. evaluación de reglas;
4. normalización de evidencia entre organizaciones;
5. auditoría y priorización de alertas.

El motor no contendrá nombres de patologías, medicamentos ni guías específicas.
El conocimiento clínico permanecerá en módulos independientes bajo `guidelines`.

## Componentes

### core

Contiene modelos, operadores, motor de inferencia, normalización de evidencia,
auditoría y derivación controlada de prioridad de alertas.

### standards

Contiene los cruces entre sistemas de gradación de organizaciones y las
políticas institucionales de priorización.

### guidelines

Contiene metadatos, variables, rutas, regímenes y reglas de cada escenario clínico.

### ia_clinica

Contiene las capacidades del agente copiloto de IA (épica IA del backlog:
IA-01 a IA-04). Es independiente del motor de reglas de `core`/`guidelines`:
no navega rutas clínicas ni evalúa reglas de tratamiento, y no usa el
contenido de `guidelines` como entrada. Cada historia de la épica IA se
implementa como un submódulo propio (por ejemplo, `ia_clinica/notes` para
IA-02 — generación automática de notas clínicas). Ver
`docs/ia_clinica_notas.md` para el detalle de IA-02.

### historia_clinica_mock

Base de datos SQLite pequeña con datos sintéticos (pacientes, consultas,
laboratorios, imagenología, biomarcadores), usada para probar `ia_clinica`
y `dx_clinica` de forma end-to-end. No implementa HC-01 a HC-06
(integración real con sistemas externos); es una herramienta de
prueba/demo. Ver `docs/historia_clinica_mock.md`.

### dx_clinica

Contiene las capacidades de la épica Diagnóstico (DX-01, DX-02...).
Implementa DX-02 — apoyo al diagnóstico diferencial: combina los
hallazgos clínicos de `historia_clinica_mock` con un catálogo diagnóstico
explícito y con evidencia leída de `guidelines/*/metadata.yaml` (una
implementación mínima de lo que después será IA-04). No usa las reglas de
tratamiento del motor `core`/`guidelines`; solo lee sus metadatos como
fuente de evidencia citable. Ver `docs/dx_clinica.md`.

### docs

Contiene la matriz clínica, el árbol de decisión y el modelo de evidencia.

### tests

Contiene casos sintéticos y pruebas automatizadas.

## Principios

1. Las reglas clínicas no se escriben directamente dentro del motor.
2. Cada regla conserva la gradación original de la organización.
3. La gradación original nunca se reemplaza por un único número universal.
4. La normalización produce dimensiones comparables, no una falsa equivalencia.
5. La aplicabilidad clínica de una regla no depende de su nivel de evidencia.
6. El nivel de evidencia influye únicamente en la explicación y prioridad de revisión.
7. Los datos ausentes no se interpretan como negativos.
8. La concordancia y la prioridad de alerta son procesos separados.
9. Toda regla debe tener fuente, versión, alcance y estado de validación.
10. Las reglas solo se consideran validadas después de revisión clínica.

## Política de estabilidad

No se renombrarán ni moverán carpetas o archivos sin una decisión explícita,
documentada en `CHANGELOG.md`.