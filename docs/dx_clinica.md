# DX-02 — Apoyo al diagnóstico diferencial

## Alcance

Implementa la historia **DX-02** del backlog (épica Diagnóstico):

> Como oncólogo, quiero recibir una lista priorizada de diagnósticos
> diferenciales sustentados en los datos clínicos del paciente y en
> evidencia disponible, para apoyar mi razonamiento diagnóstico.

DX-02 depende formalmente de HC-02, HC-04, IA-01 e IA-04. Ninguna de esas
cuatro historias existe todavía como implementación completa en este
repositorio, así que se resolvió así:

- **HC-02 (laboratorios) y HC-04 (biomarcadores):** cubiertas por
  `historia_clinica_mock`, ya construido para IA-02. Se le agregaron
  funciones a nivel de paciente completo (`laboratorios_de_paciente`,
  `imagenologia_de_paciente`, `biomarcadores_de_paciente`,
  `obtener_hallazgos_de_paciente`), porque DX-02 necesita combinar *todo*
  el expediente disponible, no una sola consulta (a diferencia de IA-02).
- **IA-01 (consulta en lenguaje natural):** no es una dependencia dura de
  la lógica de DX-02 en sí — DX-02 no *pregunta* nada en lenguaje natural,
  solo consume los hallazgos ya estructurados del expediente. Cuando IA-01
  exista, podría ser una de las formas en que el oncólogo *dispara* la
  consulta de diagnóstico diferencial, pero el motor de DX-02 no necesita
  a IA-01 para funcionar.
- **IA-04 (explicabilidad/evidencia):** todavía no existe como historia
  propia. Se construyó una implementación **mínima** de lo que
  necesitaría cubrir para DX-02: un catálogo de evidencia consultable y
  trazable (`dx_clinica/evidence.py`). Cuando IA-04 se implemente como
  historia independiente, este catálogo puede convertirse en su fuente de
  datos en vez de duplicarse.

## Cómo se satisface cada criterio de aceptación

| Criterio de aceptación | Mecanismo en el código |
|---|---|
| Lista priorizada de diagnósticos diferenciales | `builder.construir_diagnosticos_diferenciales` devuelve `candidatos` ordenados por número de criterios clínicos sustentados (nunca por una probabilidad calculada). |
| Puedo identificar los datos clínicos que sustentan cada alternativa | Cada `DiagnosticoDiferencialCandidato` expone `criterios_sustentados` (con los ids reales de `HallazgoClinico` que los respaldan) y `criterios_sin_sustento` (qué falta para reforzar esa alternativa). |
| Puedo consultar la evidencia asociada (mecanismo de IA-04) | `candidato.evidencia` es un `EvidenceReference` con organización, título, año, DOI y estado de validación clínica, leído directamente de `guidelines/<módulo>/metadata.yaml`. `evidencia.resumen_citable()` es la "funcionalidad de consulta". |
| Indica explícitamente que es apoyo a la decisión, no diagnóstico definitivo | `ResultadoDiagnosticoDiferencial.disclaimer` (fijo) y `es_apoyo_a_decision_clinica = True`. No existe ningún método `confirmar`/`aceptar` en el resultado ni en los candidatos. |
| No inventa datos clínicos ni evidencia sin sustento | Un perfil del catálogo solo se incluye si **al menos un criterio** tiene un hallazgo real que lo sustente (`matcher.coincide_sin_negacion`); si ninguno lo sustenta, no aparece. Si ningún perfil tiene sustento, el resultado queda vacío con `advertencia_sin_sustento` explícita en vez de forzar candidatos. La evidencia dinámica solo se resuelve contra una tabla explícita `diagnóstico → guía`; si no hay asociación registrada, `evidencia` es `None`, nunca una guía inventada. |

## Por qué nunca se muestra un porcentaje o probabilidad

La observación técnica de DX-02 es explícita: "Se debe evitar presentar
porcentajes o probabilidades numéricas salvo que exista un modelo
específico, validado y calibrado para dicha estimación." Este repositorio
no tiene ese modelo. Por eso la priorización es puramente ordinal (1º, 2º,
3º...) y explicada por conteos legibles ("2 de 2 criterios clínicos
sustentados"), nunca por un número que pueda leerse como una probabilidad
clínica calibrada.

## El riesgo de negación en el emparejamiento de texto

Un motor de diagnóstico diferencial que use coincidencia de subcadenas
ingenuamente tiene un problema serio: el hallazgo de imagen de María dice
literalmente *"sin hallazgos de progresión"*. Buscar la palabra
"progresión" como subcadena la encontraría igual, sugiriendo
incorrectamente progresión de enfermedad cuando el estudio dice lo
contrario. `dx_clinica/matcher.py` implementa una detección de negación
simple (mirar si hay una palabra de negación — "sin", "no", "descarta",
etc. — inmediatamente antes de la palabra clave) para evitar exactamente
este caso. Está probado explícitamente con este ejemplo real de los datos
sintéticos. No es un detector de negación clínico completo (para
producción convendría algo como el algoritmo NegEx); es deliberadamente
simple y su límite está documentado aquí.

## Sobre la evidencia dinámica

Cuando un perfil diagnóstico no es específico de una patología concreta
(por ejemplo, "progresión de la enfermedad de base" o "toxicidad
hepática", que pueden aplicar a cualquier tipo de cáncer), la evidencia
citada es la guía clínica que gobierna el contexto oncológico general del
paciente (según su `diagnostico_principal`), **no** una afirmación de que
esa guía específicamente respalda esa alternativa diagnóstica puntual.
Es, literalmente, "aquí está la guía de referencia de este caso para que
la consultes", no "esta guía dice que debe sospecharse esto". Esta
distinción importa para no sobre-representar lo que la evidencia
realmente afirma.

## Catálogo diagnóstico: qué es y qué no es

`dx_clinica/knowledge_base.py` tiene, a propósito, muy pocos perfiles
(4), pensados para poder evaluarse contra los dos pacientes sintéticos de
`historia_clinica_mock`. **No es un catálogo diagnóstico clínicamente
validado ni con pretensión de cobertura real** — es un punto de partida
para poder probar DX-02 de punta a punta. Ampliarlo con criterios
clínicamente revisados es trabajo pendiente, no algo que deba inferirse
automáticamente por IA en este momento (eso reintroduciría exactamente el
riesgo de alucinación que la historia busca evitar).

## Cómo probarlo

```
python -m dx_clinica.demo
```

Muestra el diagnóstico diferencial de los dos pacientes sintéticos ya
usados en IA-02, incluyendo el caso donde "progresión de enfermedad" NO
aparece para María (por la negación en su hallazgo de imagen) y el caso
donde "proceso infeccioso respiratorio" aparece para Carlos pero sin
evidencia externa asociada (porque ninguna guía del repositorio cubre ese
escenario).

## Continúa en DX-03

`dx_clinica.incertidumbre` (nuevo, ver `docs/dx_clinica_incertidumbre.md`)
analiza el `ResultadoDiagnosticoDiferencial` que produce este módulo para
detectar cuándo la priorización no es lo suficientemente confiable como
para presentarse sin una advertencia explícita de incertidumbre —
distinguiendo información faltante, ambigüedad entre alternativas
empatadas, e incertidumbre inherente a un perfil poco específico.
`dx_clinica.juicio_clinico` permite que el médico registre su propio
juicio diagnóstico, que prevalece sobre esta priorización sin que el
sistema pueda bloquearlo ni sobreescribirlo. Ninguno de los dos módulos
modifica `construir_diagnosticos_diferenciales`.
