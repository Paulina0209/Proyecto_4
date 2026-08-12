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