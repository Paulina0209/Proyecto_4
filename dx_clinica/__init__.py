"""Apoyo al diagnóstico diferencial (DX-02).

Como oncólogo, quiero recibir una lista priorizada de diagnósticos
diferenciales sustentados en los datos clínicos del paciente y en
evidencia disponible, para apoyar mi razonamiento diagnóstico.

Este paquete **no** decide ni presenta un diagnóstico definitivo: genera
una lista de alternativas, cada una sustentada explícitamente en
hallazgos reales del expediente (`historia_clinica_mock`) y, cuando
corresponde, en una guía clínica ya existente en `guidelines/`. Si no hay
sustento real para una alternativa, esa alternativa simplemente no se
incluye — nunca se inventa un hallazgo ni una fuente de evidencia para
justificarla.

Diseño deliberado en línea con las reglas de negocio de DX-02:

    - Nunca se presentan porcentajes ni probabilidades numéricas: la
      priorización es un orden explicable por el número de criterios
      clínicos que cada alternativa tiene sustentados, no un puntaje
      calibrado (no existe, en este repositorio, un modelo validado para
      eso).
    - El emparejamiento de hallazgos contra criterios detecta negaciones
      simples ("sin hallazgos de progresión" no cuenta como progresión),
      para reducir el riesgo de usar mal un dato clínico.
    - La evidencia citada proviene de los módulos de `guidelines/` ya
      existentes en el repositorio (con su organización, título, año, DOI
      y estado de validación clínica) — nunca de una fuente inventada en
      tiempo de ejecución. Esto también sirve como una implementación
      mínima de "consultar la evidencia asociada" (IA-04), que todavía no
      existe como historia propia en este repositorio.

Componentes:
    - ``evidence``: catálogo de evidencia derivado de ``guidelines/``.
    - ``knowledge_base``: perfiles diagnósticos sintéticos y sus criterios.
    - ``matcher``: emparejamiento de hallazgos contra criterios, con
      detección de negación.
    - ``builder``: ``construir_diagnosticos_diferenciales``, el punto de
      entrada de la historia.
"""
