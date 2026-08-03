# Backlog de Producto — Copiloto Clínico para Oncología

> Documento base para planificación de sprints. Importable a Jira/Azure DevOps/Trello usando el ID como clave de cada ítem.
> Principio rector transversal: la IA **recomienda y respalda con evidencia**, el oncólogo **decide**. Ninguna historia debe implicar automatización de la decisión clínica final.

---

## 1. Mapa del Producto (Épicas)

| Código | Épica |
|---|---|
| PAC | Gestión de Pacientes |
| HC | Historia Clínica Unificada |
| IA | Asistente de IA Clínica |
| DX | Diagnóstico y Diagnóstico Diferencial |
| EST | Estadificación |
| TX | Tratamientos y Recomendaciones Terapéuticas |
| EV | Evidencia Científica |
| DOC | Gestión Documental |
| SEC | Seguridad y Privacidad |
| AUD | Auditoría y Trazabilidad |
| CFG | Configuración |
| ADM | Administración |
| NFR | Requisitos No Funcionales (transversal) |

Se agregaron **AUD** (Auditoría/Trazabilidad) y **NFR** como épicas independientes en lugar de dejarlas diluidas dentro de Seguridad, porque en software clínico regulado la trazabilidad de decisiones y el cumplimiento normativo suelen auditarse por separado (y así se pueden reportar como avance independiente).

---

## 2. Historias de Usuario (resumen Como/Quiero/Para)

### Épica PAC — Gestión de Pacientes
- **PAC-01**: Como oncólogo, quiero registrar un nuevo paciente con sus datos demográficos y antecedentes básicos, para iniciar su expediente clínico digital.
- **PAC-02**: Como oncólogo, quiero buscar y filtrar pacientes (por nombre, diagnóstico, estado de tratamiento, fecha de última consulta), para encontrar rápidamente al paciente que necesito atender.
- **PAC-03**: Como oncólogo, quiero ver un panel resumen (dashboard 360°) del paciente al abrir su expediente, para tener contexto clínico completo en segundos sin buscar en múltiples pantallas.

### Épica HC — Historia Clínica Unificada
- **HC-01**: Como oncólogo, quiero integrar la historia clínica previa del paciente (de otros sistemas o en PDF/HL7), para no reconstruir manualmente sus antecedentes.
- **HC-02**: Como oncólogo, quiero que los resultados de laboratorio se integren automáticamente al expediente, para monitorear tendencias sin pedir el dato al paciente o a otro sistema.
- **HC-03**: Como oncólogo, quiero integrar imágenes diagnósticas (idealmente vía DICOM/PACS), para revisarlas junto con el resto del expediente.
- **HC-04**: Como oncólogo, quiero integrar resultados de biopsias y biomarcadores, para contar con la información molecular relevante al decidir tratamiento.
- **HC-05**: Como oncólogo, quiero que el sistema me indique qué información clínica falta para tomar una decisión (diagnóstico, estadificación o tratamiento), para no avanzar con datos incompletos.
- **HC-06**: Como oncólogo, quiero ver una línea de tiempo cronológica de eventos clínicos del paciente, para entender la evolución del caso de un vistazo.

### Épica IA — Asistente de IA Clínica
- **IA-01**: Como oncólogo, quiero preguntarle al asistente en lenguaje natural sobre el estado del paciente (ej. "¿cuál fue el último valor de CA-125?"), para obtener respuestas rápidas sin navegar manualmente.
- **IA-02**: Como oncólogo, quiero que el sistema genere automáticamente una nota clínica a partir de la consulta, para reducir el tiempo de documentación administrativa.
- **IA-03**: Como oncólogo, quiero generar un resumen médico del caso completo, para compartirlo en juntas médicas o interconsultas.
- **IA-04**: Como oncólogo, quiero que cada recomendación de la IA muestre el razonamiento y las fuentes que la sustentan, para poder confiar (o refutar) la sugerencia antes de decidir.

### Épica DX — Diagnóstico
- **DX-01**: Como oncólogo, quiero que el sistema recomiende únicamente los estudios necesarios según el caso, para evitar exámenes redundantes o costosos.
- **DX-02**: Como oncólogo, quiero recibir una lista de diagnósticos diferenciales con su probabilidad relativa y evidencia asociada, para orientar mi criterio diagnóstico.

### Épica EST — Estadificación
- **EST-01**: Como oncólogo, quiero que el sistema proponga una estadificación (TNM u otro sistema aplicable) con base en los datos disponibles, para agilizar esta etapa del proceso.
- **EST-02**: Como oncólogo, quiero poder revisar, ajustar y confirmar manualmente la estadificación sugerida, para que el registro final refleje mi criterio médico.

### Épica TX — Tratamientos
- **TX-01**: Como oncólogo, quiero recibir recomendaciones de tratamiento basadas en guías clínicas actualizadas (NCCN, ESMO, etc.), para fundamentar mejor mi decisión terapéutica.
- **TX-02**: Como oncólogo, quiero ver el nivel de evidencia (ej. escala GRADE o categorías NCCN) que respalda cada recomendación de tratamiento, para ponderar su fortaleza clínica.
- **TX-03**: Como oncólogo, quiero que el sistema detecte interacciones farmacológicas y contraindicaciones antes de confirmar un tratamiento, para prevenir eventos adversos evitables.
- **TX-04**: Como oncólogo, quiero registrar formalmente mi decisión final de tratamiento (aceptando, modificando o rechazando la sugerencia de la IA), para dejar constancia de que la responsabilidad clínica es mía.

### Épica EV — Evidencia Científica
- **EV-01**: Como oncólogo, quiero consultar la evidencia científica relacionada (papers, guías) sin salir de la plataforma, para verificar una recomendación en el mismo flujo de trabajo.
- **EV-02**: Como administrador clínico, quiero que las guías y bases de evidencia se actualicen periódicamente, para que el sistema no recomiende con información desactualizada.

### Épica DOC — Gestión Documental
- **DOC-01**: Como oncólogo, quiero cargar documentos clínicos (PDF, imágenes, DICOM) al expediente del paciente, para centralizar toda la documentación.
- **DOC-02**: Como oncólogo, quiero exportar un resumen o expediente en PDF, para compartirlo con el paciente, otro especialista o la aseguradora.

### Épica SEC — Seguridad y Privacidad
- **SEC-01**: Como administrador del sistema, quiero controlar el acceso mediante autenticación segura y roles (oncólogo, enfermería, administrativo), para que cada usuario vea solo lo que le corresponde.
- **SEC-02**: Como responsable de seguridad, quiero que los datos estén cifrados en tránsito y en reposo, para proteger la confidencialidad de la información clínica.
- **SEC-03**: Como paciente/institución, quiero que el sistema gestione el consentimiento informado sobre el uso de datos e IA, para cumplir con la normativa de protección de datos en salud.

### Épica AUD — Auditoría y Trazabilidad
- **AUD-01**: Como administrador, quiero un registro de auditoría de accesos y acciones sobre cada expediente, para poder reconstruir quién hizo qué y cuándo.
- **AUD-02**: Como responsable regulatorio, quiero que cada recomendación de IA quede trazada (versión del modelo, fuentes usadas, decisión del médico), para fines de auditoría clínica y legal.

### Épica CFG — Configuración
- **CFG-01**: Como administrador clínico, quiero configurar qué guías clínicas usa la institución por defecto, para adaptar el sistema a su protocolo interno.
- **CFG-02**: Como oncólogo, quiero configurar notificaciones y alertas (ej. resultados críticos, estudios pendientes), para no perder información relevante.

### Épica ADM — Administración
- **ADM-01**: Como administrador del sistema, quiero gestionar usuarios, roles y permisos, para mantener el control de acceso institucional.
- **ADM-02**: Como director médico, quiero un panel de métricas de uso del sistema (adopción, tiempos ahorrados, alertas generadas), para evaluar el impacto de la herramienta.

### Épica NFR — Requisitos No Funcionales
- **NFR-01**: Como usuario del sistema, quiero tiempos de respuesta bajos (consultas <2s, generación de notas <10s), para que la herramienta no interrumpa mi flujo de consulta.
- **NFR-02**: Como institución, quiero alta disponibilidad del sistema (SLA ≥99.5%), para que esté accesible durante horario clínico.
- **NFR-03**: Como usuario con alguna limitación visual o motriz, quiero que la interfaz cumpla estándares de accesibilidad (WCAG 2.1 AA), para poder usarla sin barreras.
- **NFR-04**: Como institución, quiero que el sistema cumpla normativa de datos de salud aplicable (HIPAA, GDPR, Habeas Data/Ley 1581 según jurisdicción), para operar legalmente.
- **NFR-05**: Como administrador, quiero que la arquitectura escale horizontalmente, para soportar el crecimiento en número de pacientes e instituciones sin degradar el rendimiento.

---

## 3–6. Criterios de aceptación, Priorización, Story Points y Dependencias (vista compacta)

> Detalle narrativo completo de cada historia en la **sección 10**. Esta tabla es la vista rápida para planificación.

| ID | Prioridad (MoSCoW) | Story Points | Dependencias |
|---|---|---|---|
| PAC-01 | Must Have | 3 | — |
| PAC-02 | Must Have | 3 | PAC-01 |
| PAC-03 | Must Have | 5 | PAC-01, HC-01 |
| HC-01 | Must Have | 8 | PAC-01 |
| HC-02 | Must Have | 8 | HC-01 |
| HC-03 | Should Have | 13 | HC-01 |
| HC-04 | Must Have | 8 | HC-01 |
| HC-05 | Must Have | 8 | HC-01, HC-02, HC-04 |
| HC-06 | Must Have | 5 | HC-01, HC-02, HC-04 |
| IA-01 | Must Have | 13 | HC-01, HC-02, HC-04, HC-06 |
| IA-02 | Must Have | 13 | IA-01 |
| IA-03 | Should Have | 8 | IA-02, HC-06 |
| IA-04 | Must Have | 8 | IA-01 |
| DX-01 | Should Have | 8 | HC-05, IA-01 |
| DX-02 | Must Have | 13 | HC-02, HC-04, IA-01, IA-04 |
| EST-01 | Must Have | 13 | DX-02, HC-04 |
| EST-02 | Must Have | 5 | EST-01 |
| TX-01 | Must Have | 21 | EST-02, EV-01, IA-04 |
| TX-02 | Must Have | 5 | TX-01 |
| TX-03 | Must Have | 8 | TX-01 |
| TX-04 | Must Have | 5 | TX-01, TX-03, AUD-02 |
| EV-01 | Must Have | 8 | — |
| EV-02 | Should Have | 5 | EV-01 |
| DOC-01 | Must Have | 5 | PAC-01 |
| DOC-02 | Should Have | 5 | HC-06, TX-04 |
| SEC-01 | Must Have | 8 | — |
| SEC-02 | Must Have | 8 | — |
| SEC-03 | Must Have | 5 | SEC-01 |
| AUD-01 | Must Have | 8 | SEC-01 |
| AUD-02 | Must Have | 8 | IA-04, AUD-01 |
| CFG-01 | Should Have | 5 | EV-01 |
| CFG-02 | Could Have | 3 | HC-02, SEC-01 |
| ADM-01 | Must Have | 5 | SEC-01 |
| ADM-02 | Could Have | 8 | AUD-01 |
| NFR-01 | Must Have | 8 | — (aplica a todo el sistema) |
| NFR-02 | Must Have | 8 | — |
| NFR-03 | Should Have | 5 | — |
| NFR-04 | Must Have | 13 | SEC-01, SEC-02, SEC-03, AUD-01 |
| NFR-05 | Won't Have (por ahora) | 13 | NFR-02 |

**Nota de honestidad en la estimación:** los Story Points de IA-01 en adelante asumen que ya existe una capa de integración de datos funcional (HC-01/02/04) y acceso a un modelo con capacidades clínicas razonables; si eso no está resuelto, TX-01 y DX-02 fácilmente superan 21 puntos y deberían partirse en sub-historias técnicas (ingesta, prompt/orquestación, validación clínica, UI).

---

## 7. MVP (Producto Mínimo Viable)

**Historias incluidas en el MVP:**
PAC-01, PAC-02, PAC-03, HC-01, HC-02, HC-04, HC-05, HC-06, IA-01, IA-02, IA-04, DX-02, EST-01, EST-02, TX-01, TX-02, TX-03, TX-04, EV-01, DOC-01, SEC-01, SEC-02, SEC-03, AUD-01, AUD-02, NFR-01, NFR-02, NFR-04.

**Por qué este corte y no otro:**
- El valor central declarado por el usuario (oncólogo) en las entrevistas es "reducir tiempo administrativo + apoyar diagnóstico/estadificación/tratamiento con evidencia, sin quitarme la decisión". Eso exige el flujo completo **HC → IA → DX → EST → TX**, no partes sueltas. Un MVP que solo centralice información pero no llegue hasta TX-04 (registro de decisión) no cierra el ciclo de valor ni el ciclo de responsabilidad clínica/legal.
- **HC-03 (imágenes/DICOM/PACS) se deja fuera del MVP**: es la integración técnicamente más costosa (13 pts, típicamente requiere visor DICOM y conectividad PACS institucional) y el resto del flujo de IA puede funcionar razonablemente con laboratorios + biomarcadores + notas, mientras se resuelve esa integración en paralelo.
- **IA-03 (resumen para junta médica), EV-02 (actualización automática de guías), DOC-02, CFG-01/02, ADM-02** se dejan para Should/Could: son valiosas pero no bloquean el ciclo diagnóstico-tratamiento.
- **SEC, AUD y NFR-04 (cumplimiento normativo) van completos en el MVP sin excepción**: en salud, lanzar sin esto no es "MVP reducido", es riesgo legal y clínico inaceptable. No es negociable aunque encarezca el sprint 0.
- **NFR-05 (escalabilidad horizontal) se marca explícitamente Won't Have por ahora**: para una primera institución piloto no es prioritario sobre-invertir en arquitectura de escala; se revisita cuando haya tracción real.

---

## 8. Riesgos por Épica

| Épica | Riesgo técnico | Riesgo clínico | Riesgo regulatorio | Riesgo de UX |
|---|---|---|---|---|
| PAC | Duplicidad de registros de pacientes | Datos demográficos incorrectos afectan dosificación (peso/edad) | Manejo de datos de identificación personal | Formularios largos que el oncólogo no completa en consulta |
| HC | Formatos heterogéneos (HL7, PDF, DICOM) dificultan integración | Información desactualizada o mal mapeada genera decisiones erróneas | Interoperabilidad con sistemas externos sin cumplir estándares (HL7 FHIR) | Sobrecarga de información no priorizada ("info overload") |
| IA | Alucinaciones del modelo o respuestas no verificables | El médico confía ciegamente en una sugerencia incorrecta (automation bias) | Falta de trazabilidad de qué generó la IA vs. el humano | Lenguaje ambiguo que se malinterpreta como orden clínica |
| DX | Falsos negativos/positivos en diagnóstico diferencial | Omisión de un diagnóstico relevante por sesgo de los datos de entrenamiento | Uso de IA diagnóstica puede requerir clasificación regulatoria como software médico (SaMD) | Presentar probabilidades sin contexto puede confundir en vez de ayudar |
| EST | Mapeo incorrecto de reglas TNM/versión de guía | Estadificación errónea impacta directamente el tratamiento | Estadificación es un acto médico regulado; delegarla sin supervisión es riesgoso | Difícil visualizar "por qué" llegó a ese estadio |
| TX | Base de conocimiento de guías desactualizada | Recomendación no ajustada a comorbilidades o contexto local | Recomendar tratamiento puede acercarse a "practicar medicina" si no se enmarca como apoyo | Exceso de alertas de interacción reduce su efectividad (alert fatigue) |
| EV | Falta de acceso a bases pagas (paywalls) | Evidencia de baja calidad presentada al mismo nivel que evidencia robusta | Uso de contenido con derechos de autor de journals | Resultados poco filtrados o irrelevantes al caso |
| DOC | Corrupción o pérdida de archivos grandes (imágenes/DICOM) | Documentos mal asociados al paciente equivocado | Retención y borrado de documentos según normativa de historia clínica | Proceso de carga lento o poco claro |
| SEC | Brechas en cifrado o gestión de llaves | Acceso indebido a datos sensibles de salud | Incumplimiento de HIPAA/GDPR/normativa local con sanciones severas | Fricción de login excesiva reduce adopción |
| AUD | Volumen de logs afecta rendimiento | Imposibilidad de reconstruir una decisión clínica en caso de disputa | Requisitos de retención de auditoría varían por jurisdicción | Logs no consultables de forma amigable para auditores no técnicos |
| CFG | Configuraciones inconsistentes entre instituciones | Guía clínica mal configurada afecta a todos los pacientes de esa institución | Cambios de configuración no versionados dificultan trazabilidad | Configuración expuesta a usuarios sin perfil técnico |
| ADM | Errores en asignación de roles/permisos | N/A directo, pero mal manejo de accesos afecta indirectamente la atención | Gestión de identidad debe alinearse con políticas institucionales | Paneles de métricas sin contexto generan interpretaciones erróneas |

---

## 9. Requisitos No Funcionales (detalle)

Ya listados como historias NFR-01 a NFR-05 en la sección 2. Se agrupan también aquí por categoría para trazabilidad directa con la sección 10 de tu prompt original:

- **Seguridad de la información** → SEC-01, SEC-02
- **Privacidad de datos** → SEC-03, NFR-04
- **Auditoría** → AUD-01
- **Trazabilidad** → AUD-02
- **Rendimiento** → NFR-01
- **Escalabilidad** → NFR-05 (diferida)
- **Disponibilidad** → NFR-02
- **Accesibilidad** → NFR-03
- **Cumplimiento normativo** → NFR-04
- **Explicabilidad de la IA** → IA-04
- **Registro de decisiones clínicas** → TX-04, AUD-02

---

## 10. Tabla Final + Detalle por Historia

### 10.1 Tabla resumen (para importación directa)

| ID | Épica | Historia de Usuario | Prioridad | Story Points | Dependencias | MVP |
|---|---|---|---|---|---|---|
| PAC-01 | Gestión de Pacientes | Registro de nuevo paciente | Must Have | 3 | — | Sí |
| PAC-02 | Gestión de Pacientes | Búsqueda y filtrado de pacientes | Must Have | 3 | PAC-01 | Sí |
| PAC-03 | Gestión de Pacientes | Dashboard 360° del paciente | Must Have | 5 | PAC-01, HC-01 | Sí |
| HC-01 | Historia Clínica | Integración de historia clínica externa | Must Have | 8 | PAC-01 | Sí |
| HC-02 | Historia Clínica | Integración de laboratorios | Must Have | 8 | HC-01 | Sí |
| HC-03 | Historia Clínica | Integración de imágenes (DICOM/PACS) | Should Have | 13 | HC-01 | No |
| HC-04 | Historia Clínica | Integración de biopsias y biomarcadores | Must Have | 8 | HC-01 | Sí |
| HC-05 | Historia Clínica | Detección de información faltante | Must Have | 8 | HC-01, HC-02, HC-04 | Sí |
| HC-06 | Historia Clínica | Línea de tiempo cronológica | Must Have | 5 | HC-01, HC-02, HC-04 | Sí |
| IA-01 | IA Clínica | Consulta en lenguaje natural | Must Have | 13 | HC-01, HC-02, HC-04, HC-06 | Sí |
| IA-02 | IA Clínica | Generación automática de notas clínicas | Must Have | 13 | IA-01 | Sí |
| IA-03 | IA Clínica | Resumen médico para junta/interconsulta | Should Have | 8 | IA-02, HC-06 | No |
| IA-04 | IA Clínica | Explicabilidad de recomendaciones | Must Have | 8 | IA-01 | Sí |
| DX-01 | Diagnóstico | Recomendación de estudios necesarios | Should Have | 8 | HC-05, IA-01 | No |
| DX-02 | Diagnóstico | Apoyo al diagnóstico diferencial | Must Have | 13 | HC-02, HC-04, IA-01, IA-04 | Sí |
| EST-01 | Estadificación | Estadificación automática asistida | Must Have | 13 | DX-02, HC-04 | Sí |
| EST-02 | Estadificación | Ajuste manual de estadificación | Must Have | 5 | EST-01 | Sí |
| TX-01 | Tratamientos | Recomendación de tratamiento por guías | Must Have | 21 | EST-02, EV-01, IA-04 | Sí |
| TX-02 | Tratamientos | Nivel de evidencia por recomendación | Must Have | 5 | TX-01 | Sí |
| TX-03 | Tratamientos | Detección de interacciones/contraindicaciones | Must Have | 8 | TX-01 | Sí |
| TX-04 | Tratamientos | Registro de decisión clínica final | Must Have | 5 | TX-01, TX-03, AUD-02 | Sí |
| EV-01 | Evidencia Científica | Consulta de evidencia sin salir de la plataforma | Must Have | 8 | — | Sí |
| EV-02 | Evidencia Científica | Actualización periódica de guías | Should Have | 5 | EV-01 | No |
| DOC-01 | Gestión Documental | Carga de documentos clínicos | Must Have | 5 | PAC-01 | Sí |
| DOC-02 | Gestión Documental | Exportación de expediente en PDF | Should Have | 5 | HC-06, TX-04 | No |
| SEC-01 | Seguridad | Autenticación y control de acceso por rol | Must Have | 8 | — | Sí |
| SEC-02 | Seguridad | Cifrado en tránsito y en reposo | Must Have | 8 | — | Sí |
| SEC-03 | Seguridad | Consentimiento informado y privacidad | Must Have | 5 | SEC-01 | Sí |
| AUD-01 | Auditoría | Registro de auditoría de accesos/acciones | Must Have | 8 | SEC-01 | Sí |
| AUD-02 | Auditoría | Trazabilidad de recomendaciones de IA | Must Have | 8 | IA-04, AUD-01 | Sí |
| CFG-01 | Configuración | Configuración de guías clínicas institucionales | Should Have | 5 | EV-01 | No |
| CFG-02 | Configuración | Notificaciones y alertas | Could Have | 3 | HC-02, SEC-01 | No |
| ADM-01 | Administración | Gestión de usuarios y roles | Must Have | 5 | SEC-01 | Sí |
| ADM-02 | Administración | Panel de métricas de uso | Could Have | 8 | AUD-01 | No |
| NFR-01 | No Funcional | Rendimiento y tiempos de respuesta | Must Have | 8 | — | Sí |
| NFR-02 | No Funcional | Disponibilidad (SLA) | Must Have | 8 | — | Sí |
| NFR-03 | No Funcional | Accesibilidad WCAG 2.1 AA | Should Have | 5 | — | No |
| NFR-04 | No Funcional | Cumplimiento normativo (HIPAA/GDPR/local) | Must Have | 13 | SEC-01, SEC-02, SEC-03, AUD-01 | Sí |
| NFR-05 | No Funcional | Escalabilidad horizontal | Won't Have (por ahora) | 13 | NFR-02 | No |

---

### 10.2 Detalle por historia

A continuación, el desglose completo. Por espacio, se agrupan las historias con estructura similar y se profundiza especialmente en las de mayor riesgo clínico/regulatorio (IA, DX, EST, TX, SEC, AUD), que es donde un equipo de desarrollo suele necesitar más contexto para no subestimar el trabajo.

---

#### PAC-01 — Registro de nuevo paciente
**Descripción:** Formulario de alta de paciente con datos demográficos (nombre, edad, sexo, identificación, contacto), antecedentes personales/familiares básicos y motivo de consulta inicial.

**Criterios de aceptación:**
```
Dado que soy un oncólogo autenticado
Cuando completo los campos obligatorios y guardo
Entonces el paciente queda registrado y aparece en mi listado

Dado que dejo un campo obligatorio vacío
Cuando intento guardar
Entonces el sistema me indica qué campo falta y no guarda el registro

Dado que intento registrar un paciente con un número de identificación ya existente
Cuando guardo
Entonces el sistema me alerta de posible duplicado antes de crear un registro nuevo
```
**Reglas de negocio:** El número de identificación (o equivalente) es único por paciente en la institución.
**Casos de excepción:** Paciente sin documento de identidad (menor, extranjero, indocumentado) — debe permitir un identificador alterno temporal.
**Consideraciones UX:** Formulario corto para uso en consulta con tiempo limitado; posibilidad de completarlo después.
**Riesgos:** Duplicidad de pacientes (técnico); dato demográfico erróneo que afecte dosificación posterior (clínico).
**Observaciones técnicas:** Definir desde ya el modelo de identidad del paciente porque de él dependen HC-01 y todo el resto del sistema.

---

#### PAC-02 — Búsqueda y filtrado de pacientes
**Descripción:** Buscador con filtros por nombre, diagnóstico, estado de tratamiento y fecha de última consulta.

**Criterios de aceptación:**
```
Dado que tengo pacientes registrados
Cuando busco por nombre parcial
Entonces el sistema muestra coincidencias en tiempo real

Dado que aplico un filtro combinado (ej. diagnóstico + estado de tratamiento)
Cuando no hay resultados
Entonces el sistema muestra un mensaje claro de "sin resultados" y no un listado vacío sin explicación
```
**Reglas de negocio:** Un oncólogo solo ve pacientes bajo su cuidado o de su institución, según el modelo de permisos (ligado a SEC-01).
**Riesgos:** UX — listas largas sin buena paginación/búsqueda generan frustración real en consulta.

---

#### PAC-03 — Dashboard 360° del paciente
**Descripción:** Vista única al abrir el expediente con: diagnóstico actual, estadio, último tratamiento, alertas activas (interacciones, estudios pendientes), y accesos directos a labs/imágenes/notas.

**Criterios de aceptación:**
```
Dado que abro el expediente de un paciente con historia completa
Cuando carga el dashboard
Entonces veo diagnóstico, estadio y último tratamiento sin necesidad de navegar a otra pantalla

Dado que el paciente tiene información clínica incompleta
Cuando abro el dashboard
Entonces veo un indicador claro de "información faltante" (ligado a HC-05)
```
**Consideraciones UX:** Es la pantalla más usada del sistema; requiere jerarquía visual clara y evitar sobrecarga de datos.
**Riesgos:** UX — mostrar demasiada información sin priorizar reduce en vez de aumentar la eficiencia.

---

#### HC-01 — Integración de historia clínica externa
**Descripción:** Ingesta de historia clínica previa desde sistemas externos (HL7/FHIR si están disponibles) o carga manual/PDF cuando no hay integración posible.

**Criterios de aceptación:**
```
Dado que existe una integración HL7/FHIR con el sistema de origen
Cuando se sincroniza el paciente
Entonces sus antecedentes se cargan automáticamente en su expediente

Dado que no existe integración disponible
Cuando el oncólogo carga un PDF de historia clínica
Entonces el documento queda asociado al paciente y disponible para consulta (aunque no estructurado)

Dado que la sincronización falla
Cuando ocurre el error
Entonces el sistema notifica el fallo sin bloquear el resto del expediente
```
**Riesgos:** Técnico — heterogeneidad de formatos entre instituciones; regulatorio — la interoperabilidad con terceros debe respetar acuerdos de intercambio de datos vigentes.
**Observaciones técnicas:** Es la historia más subestimada del backlog en la práctica: cada hospital tiene un HCE distinto. Recomendable dividir en sub-historias técnicas por tipo de fuente antes de sprint planning real.

---

#### HC-02 — Integración de laboratorios
**Descripción:** Recepción e integración de resultados de laboratorio (manual o vía interfaz de laboratorio), con visualización de tendencias históricas por marcador.

**Criterios de aceptación:**
```
Dado que llega un nuevo resultado de laboratorio
Cuando se procesa
Entonces se asocia automáticamente al paciente correcto y a la fecha correspondiente

Dado que un valor está fuera de rango crítico
Cuando se registra
Entonces el sistema genera una alerta visible en el dashboard del paciente

Dado que dos resultados llegan con el mismo timestamp para el mismo marcador
Cuando se procesan
Entonces el sistema no sobreescribe silenciosamente, sino que marca el conflicto para revisión
```
**Riesgos:** Clínico — asociar un resultado al paciente equivocado es un riesgo grave; debe haber doble validación (ID + nombre).

---

#### HC-03 — Integración de imágenes diagnósticas (DICOM/PACS)
**Descripción:** Conexión con PACS institucional para visualizar imágenes (o al menos sus reportes) desde el expediente.

**Criterios de aceptación:**
```
Dado que el paciente tiene un estudio de imagen en el PACS
Cuando abro su expediente
Entonces puedo visualizar el estudio o su reporte asociado

Dado que no hay conexión con el PACS institucional
Cuando intento ver la imagen
Entonces el sistema informa que la integración no está disponible, sin fallar silenciosamente
```
**Riesgos:** Técnico — visor DICOM completo es un desarrollo no trivial (frecuentemente se resuelve embebiendo un visor de terceros en vez de construir uno propio). Se recomienda evaluar esto explícitamente antes de comprometer el punto.

---

#### HC-04 — Integración de biopsias y biomarcadores
**Descripción:** Registro estructurado de resultados de patología, biomarcadores moleculares (ej. HER2, EGFR, PD-L1) relevantes para diagnóstico y elección de tratamiento.

**Criterios de aceptación:**
```
Dado que se registra un resultado de biopsia
Cuando se guarda
Entonces queda vinculado al episodio diagnóstico correspondiente

Dado que un biomarcador es relevante para una terapia dirigida disponible
Cuando se registra
Entonces el sistema lo resalta como dato clave para decisión de tratamiento (input para TX-01)
```
**Riesgos:** Clínico — un biomarcador mal capturado (ej. positivo/negativo invertido) puede llevar a un tratamiento incorrecto; requiere validación estricta de formato de entrada.

---

#### HC-05 — Detección de información clínica faltante
**Descripción:** El sistema evalúa, contra un checklist clínico (configurable por tipo de cáncer), qué datos faltan para poder diagnosticar/estadificar/tratar con confianza.

**Criterios de aceptación:**
```
Dado un paciente con sospecha de cáncer de mama
Cuando reviso su expediente
Entonces el sistema me indica si falta, por ejemplo, el estado de receptores hormonales o HER2

Dado que toda la información necesaria está disponible
Cuando reviso el expediente
Entonces no se muestra ninguna alerta de información faltante

Dado que el checklist clínico no está definido para un tipo de cáncer específico
Cuando reviso el expediente
Entonces el sistema indica que no puede evaluar completitud para ese caso, en vez de asumir que está completo
```
**Riesgos:** Clínico — un falso "completo" es peor que no tener la función, porque genera falsa confianza.

---

#### HC-06 — Línea de tiempo cronológica del paciente
**Descripción:** Vista tipo timeline con todos los eventos clínicos relevantes (diagnóstico, estudios, tratamientos, consultas) ordenados cronológicamente.

**Criterios de aceptación:**
```
Dado que el paciente tiene múltiples eventos clínicos registrados
Cuando abro la línea de tiempo
Entonces los veo ordenados cronológicamente con posibilidad de filtrar por tipo de evento

Dado que un evento no tiene fecha exacta (solo mes/año)
Cuando se muestra en la timeline
Entonces se indica visualmente que la fecha es aproximada
```

---

#### IA-01 — Consulta en lenguaje natural sobre el paciente
**Descripción:** Interfaz conversacional que responde preguntas sobre el expediente del paciente activo, citando la fuente del dato (ej. "según el laboratorio del 15/03").

**Criterios de aceptación:**
```
Dado que pregunto por un dato existente en el expediente
Cuando el asistente responde
Entonces la respuesta incluye la fuente y fecha del dato citado

Dado que pregunto por un dato que no existe en el expediente
Cuando el asistente responde
Entonces indica explícitamente que no tiene esa información, en vez de inferir o inventar un valor

Dado que la pregunta es ambigua o puede referirse a más de un paciente/episodio
Cuando el asistente responde
Entonces pide aclaración en vez de asumir
```
**Reglas de negocio:** El asistente nunca debe responder con un dato que no pueda trazar a una fuente concreta del expediente.
**Riesgos:** IA — alucinación (técnico/clínico) es el riesgo central de toda la épica; requiere mecanismo de verificación contra la fuente de datos antes de mostrar la respuesta, no solo "confianza" del modelo.
**Observaciones técnicas:** Considerar arquitectura tipo RAG (retrieval-augmented generation) sobre el expediente estructurado, no generación libre.

---

#### IA-02 — Generación automática de notas clínicas
**Descripción:** A partir de la consulta (dictado, transcripción o resumen de interacción), el sistema genera un borrador de nota clínica en formato estándar (ej. SOAP).

**Criterios de aceptación:**
```
Dado que finaliza una consulta registrada en el sistema
Cuando solicito la generación de la nota
Entonces obtengo un borrador editable en formato SOAP (o el estándar configurado)

Dado que el borrador generado contiene un dato incorrecto
Cuando lo reviso
Entonces puedo editarlo manualmente antes de firmarlo

Dado que no firmo/aprobo la nota
Cuando cierro la sesión
Entonces la nota queda marcada como "borrador no confirmado", no como nota oficial
```
**Reglas de negocio:** Ninguna nota generada por IA queda como definitiva sin aprobación explícita del médico (firma digital o equivalente).
**Riesgos:** Clínico/regulatorio — una nota no revisada que se considere "oficial" es un riesgo legal serio.

---

#### IA-03 — Resumen médico para junta/interconsulta
**Descripción:** Generación de un resumen ejecutivo del caso (diagnóstico, estadio, tratamientos previos, estado actual) para compartir en juntas de tumores o interconsultas.

**Criterios de aceptación:**
```
Dado un paciente con historia clínica suficiente
Cuando solicito el resumen
Entonces obtengo un documento estructurado listo para presentar en junta médica

Dado que el paciente tiene información incompleta
Cuando genero el resumen
Entonces el documento indica explícitamente las secciones con datos faltantes
```

---

#### IA-04 — Explicabilidad de recomendaciones
**Descripción:** Cada output de la IA (diagnóstico diferencial, estadificación sugerida, tratamiento) debe mostrar: qué datos se usaron, qué guía/evidencia respalda la sugerencia, y nivel de confianza.

**Criterios de aceptación:**
```
Dado que la IA genera una recomendación
Cuando la visualizo
Entonces puedo ver qué datos del paciente y qué fuente de evidencia la sustentan

Dado que la IA no tiene suficiente evidencia o datos para una recomendación confiable
Cuando genera la salida
Entonces lo indica explícitamente en vez de presentar la sugerencia con falsa seguridad
```
**Riesgos:** Este es, junto con TX-01, el corazón regulatorio del producto: sin explicabilidad verificable, el sistema puede caer bajo clasificación de software médico de alto riesgo en varias jurisdicciones.

---

#### DX-01 — Recomendación de estudios necesarios
**Descripción:** Basado en la sospecha diagnóstica, el sistema sugiere solo los estudios clínicamente relevantes (evitando sobre-pedido).

**Criterios de aceptación:**
```
Dado un caso con sospecha diagnóstica definida
Cuando solicito recomendación de estudios
Entonces recibo una lista priorizada con justificación de cada estudio sugerido

Dado que ya existen estudios equivalentes recientes en el expediente
Cuando se genera la recomendación
Entonces el sistema no vuelve a sugerir un estudio redundante
```

---

#### DX-02 — Apoyo al diagnóstico diferencial
**Descripción:** Lista de diagnósticos diferenciales posibles con probabilidad relativa estimada y la evidencia/datos que los sustentan.

**Criterios de aceptación:**
```
Dado un caso con datos clínicos suficientes
Cuando solicito el diagnóstico diferencial
Entonces recibo una lista ordenada con el respaldo de evidencia de cada opción (ligado a IA-04)

Dado que los datos son insuficientes para diferenciar con confianza
Cuando solicito el diagnóstico diferencial
Entonces el sistema indica qué información adicional reduciría la incertidumbre, en vez de forzar una lista poco confiable

Dado que el médico no está de acuerdo con el orden de probabilidad sugerido
Cuando revisa la lista
Entonces puede registrar su propio criterio sin que el sistema lo bloquee
```
**Riesgos:** Este es probablemente el punto de mayor exposición clínica y regulatoria de todo el backlog — vale la pena validarlo con un comité clínico/ético antes de llevarlo a producción, no solo con QA de software.

---

#### EST-01 — Estadificación automática asistida
**Descripción:** Propuesta de estadio (TNM u otro sistema aplicable según el tipo de cáncer) con base en los datos disponibles del paciente.

**Criterios de aceptación:**
```
Dado un paciente con diagnóstico confirmado y datos suficientes
Cuando se solicita la estadificación
Entonces el sistema propone un estadio con la justificación de cada componente (T, N, M)

Dado que falta un componente para determinar el estadio con precisión
Cuando se solicita la estadificación
Entonces el sistema indica el rango posible y qué dato falta para precisar
```
**Observaciones técnicas:** El motor de reglas de estadificación debe versionarse explícitamente (ej. "AJCC 8th edition"), porque estos sistemas cambian de versión y eso afecta comparabilidad histórica de datos.

---

#### EST-02 — Ajuste manual de estadificación
**Descripción:** El oncólogo puede modificar y confirmar el estadio sugerido antes de que quede registrado como definitivo.

**Criterios de aceptación:**
```
Dado un estadio sugerido por el sistema
Cuando el médico lo modifica y confirma
Entonces el estadio final registrado es el confirmado por el médico, y queda registro de que difirió de la sugerencia (ligado a AUD-02)
```

---

#### TX-01 — Recomendación de tratamiento basada en guías clínicas
**Descripción:** Sugerencia de esquema(s) de tratamiento según guía clínica configurada (NCCN, ESMO u otra), considerando estadio, biomarcadores y comorbilidades registradas.

**Criterios de aceptación:**
```
Dado un caso estadificado y con biomarcadores registrados
Cuando se solicita la recomendación de tratamiento
Entonces el sistema sugiere una o más opciones alineadas a la guía configurada, con su justificación

Dado que el paciente tiene una comorbilidad que contraindica una opción de primera línea
Cuando se genera la recomendación
Entonces esa opción no se presenta como primera línea, o se presenta con la advertencia correspondiente

Dado que no hay guía aplicable clara para el caso (enfermedad rara o presentación atípica)
Cuando se solicita la recomendación
Entonces el sistema lo indica explícitamente en vez de forzar una sugerencia genérica
```
**Riesgos:** Es la historia de mayor story points del backlog (21) por buena razón: combina motor de reglas clínicas + biomarcadores + comorbilidades + guías versionadas. Se recomienda explícitamente partirla en sub-historias técnicas antes de estimarla en un sprint real.

---

#### TX-02 — Nivel de evidencia por recomendación
**Descripción:** Cada opción de tratamiento sugerida muestra su nivel de evidencia (ej. categoría 1/2A/2B NCCN, o GRADE).

**Criterios de aceptación:**
```
Dado una recomendación de tratamiento
Cuando la visualizo
Entonces veo el nivel de evidencia asociado y la fuente exacta (guía y versión)
```

---

#### TX-03 — Detección de interacciones farmacológicas y contraindicaciones
**Descripción:** Antes de confirmar un tratamiento, el sistema valida contra la medicación actual del paciente y sus contraindicaciones conocidas.

**Criterios de aceptación:**
```
Dado un tratamiento propuesto que interactúa con medicación actual del paciente
Cuando se intenta confirmar
Entonces el sistema muestra la alerta de interacción antes de permitir avanzar

Dado que el médico decide continuar pese a la alerta
Cuando confirma
Entonces debe justificar explícitamente la decisión, y esta justificación queda registrada (ligado a AUD-02)

Dado que no hay interacciones conocidas
Cuando se confirma el tratamiento
Entonces no se muestran alertas innecesarias (evitar alert fatigue)
```
**Riesgos:** UX — el riesgo real de esta historia no es técnico sino de "fatiga de alertas": si el sistema alerta demasiado, el médico empieza a ignorarlas.

---

#### TX-04 — Registro de decisión clínica final
**Descripción:** El médico registra explícitamente si acepta, modifica o rechaza la recomendación de tratamiento, dejando esto como el registro oficial.

**Criterios de aceptación:**
```
Dado una recomendación de tratamiento generada por el sistema
Cuando el médico decide
Entonces puede registrar: aceptar tal cual, modificar y registrar el esquema final, o rechazar con motivo

Dado que el médico rechaza la recomendación
Cuando registra su decisión
Entonces el sistema no bloquea el flujo, solo deja constancia del criterio médico aplicado
```
**Reglas de negocio:** Este registro es el que sostiene, ante cualquier auditoría o disputa, que la decisión fue médica y no automatizada.

---

#### EV-01 — Consulta de evidencia científica dentro de la plataforma
**Descripción:** Buscador integrado de evidencia (papers, guías) relacionado al caso o a una pregunta libre, sin salir del flujo de trabajo.

**Criterios de aceptación:**
```
Dado que quiero verificar una recomendación
Cuando busco evidencia relacionada
Entonces obtengo resultados relevantes con su fuente y fecha de publicación, sin salir de la plataforma
```
**Riesgos:** Regulatorio — verificar licenciamiento de contenido de journals/bases de evidencia antes de indexarlo o mostrarlo íntegro.

---

#### EV-02 — Actualización periódica de guías y evidencia
**Descripción:** Proceso (automático o semi-automático) para mantener actualizada la base de guías clínicas y evidencia usada por el sistema.

**Criterios de aceptación:**
```
Dado que se publica una nueva versión de una guía clínica configurada
Cuando el proceso de actualización corre
Entonces el sistema usa la nueva versión y registra el cambio de versión (para trazabilidad histórica)
```

---

#### DOC-01 — Carga de documentos clínicos
**Descripción:** Carga de archivos (PDF, imágenes, DICOM) al expediente del paciente correcto.

**Criterios de aceptación:**
```
Dado un documento clínico en formato soportado
Cuando lo cargo al expediente de un paciente
Entonces queda asociado correctamente y visible en su historial documental

Dado un formato no soportado
Cuando intento cargarlo
Entonces el sistema rechaza el archivo con un mensaje claro del formato esperado
```

---

#### DOC-02 — Exportación de expediente/resumen en PDF
**Descripción:** Exportar el resumen del caso o el expediente completo en PDF para compartir externamente.

**Criterios de aceptación:**
```
Dado un expediente con información suficiente
Cuando solicito exportar el resumen
Entonces obtengo un PDF con formato profesional listo para compartir
```

---

#### SEC-01 — Autenticación y control de acceso por rol
**Descripción:** Login seguro (idealmente con MFA) y modelo de permisos por rol (oncólogo, enfermería, administrativo, auditor).

**Criterios de aceptación:**
```
Dado un usuario con rol "enfermería"
Cuando intenta acceder a la función de confirmar tratamiento (TX-04)
Entonces el sistema le deniega el acceso porque esa acción está restringida al rol oncólogo

Dado múltiples intentos fallidos de login
Cuando se supera el umbral configurado
Entonces la cuenta se bloquea temporalmente y se notifica al usuario
```

---

#### SEC-02 — Cifrado en tránsito y en reposo
**Descripción:** Todo dato clínico se transmite y almacena cifrado (TLS en tránsito, cifrado a nivel de base de datos/almacenamiento en reposo).

**Criterios de aceptación:**
```
Dado cualquier comunicación cliente-servidor
Cuando se transmite información clínica
Entonces se realiza exclusivamente sobre TLS vigente (sin fallback a conexiones no cifradas)
```

---

#### SEC-03 — Consentimiento informado y privacidad
**Descripción:** Gestión del consentimiento del paciente sobre el uso de sus datos y de la IA en su atención.

**Criterios de aceptación:**
```
Dado un paciente nuevo
Cuando se registra su expediente
Entonces el sistema exige el registro del consentimiento informado antes de habilitar funciones de IA sobre sus datos

Dado que un paciente retira su consentimiento
Cuando esto se registra
Entonces las funciones de IA dejan de aplicarse a su expediente, sin borrar el historial clínico existente
```

---

#### AUD-01 — Registro de auditoría de accesos y acciones
**Descripción:** Log inmutable de quién accedió, a qué expediente, y qué acción realizó (ver, editar, exportar).

**Criterios de aceptación:**
```
Dado cualquier acceso a un expediente
Cuando ocurre
Entonces queda registrado con usuario, fecha/hora, y acción realizada, de forma no editable
```

---

#### AUD-02 — Trazabilidad de recomendaciones de IA
**Descripción:** Cada recomendación de IA queda registrada con: versión del modelo/motor de reglas, datos de entrada usados, fuentes citadas, y la decisión final del médico frente a esa recomendación.

**Criterios de aceptación:**
```
Dado que la IA genera una recomendación
Cuando el médico toma una decisión al respecto (acepta/modifica/rechaza)
Entonces ambos elementos (recomendación y decisión) quedan vinculados y son consultables posteriormente para auditoría
```
**Observaciones técnicas:** Esta historia es la que sostiene legalmente todo el discurso de "la IA no reemplaza el criterio médico" — sin ella, esa afirmación no es verificable ante un tercero.

---

#### CFG-01 — Configuración de guías clínicas institucionales
**Descripción:** Permite a un administrador clínico elegir qué guía(s) usa la institución por defecto (NCCN, ESMO, protocolo propio).

---

#### CFG-02 — Notificaciones y alertas
**Descripción:** Configuración de qué eventos generan notificación (resultado crítico, estudio pendiente, interacción detectada) y por qué canal.

---

#### ADM-01 — Gestión de usuarios y roles
**Descripción:** CRUD de usuarios institucionales y asignación de roles/permisos.

---

#### ADM-02 — Panel de métricas de uso del sistema
**Descripción:** Dashboard administrativo con adopción, tiempo ahorrado estimado, alertas generadas, tasa de aceptación de recomendaciones de IA.

**Consideraciones UX:** Presentar "tasa de aceptación de recomendaciones de IA" con cuidado — un número bajo no necesariamente es negativo (puede reflejar buen criterio médico filtrando sugerencias), y debe evitarse que se use como métrica de desempeño individual del médico.

---

#### NFR-01 a NFR-05
Ya descritas como historias en la sección 2 y mapeadas por categoría en la sección 9. Se recomienda tratarlas como "historias técnicas" con criterios de aceptación medibles (ej. NFR-01: "el 95% de las consultas al asistente responden en menos de 2 segundos bajo carga normal") en vez de dejarlas como requisitos declarativos sin métrica verificable.

---

## Notas finales para planificación de sprints

1. **Sprint 0 recomendado**: SEC-01, SEC-02, SEC-03, HC-01 (base técnica), PAC-01. Sin esto, ninguna historia clínica posterior puede probarse de forma segura ni realista.
2. **El bloque IA-01 → TX-04 es secuencial por diseño**, no paralelizable entre equipos sin coordinación fuerte, porque cada eslabón consume el output validado del anterior (dato → diagnóstico → estadio → tratamiento → decisión → auditoría).
3. **Recomendación honesta**: antes de comprometer story points de TX-01, DX-02 y EST-01 en un sprint real, vale la pena una spike técnica de 1 sprint para validar con qué fuente de guías/evidencia se va a alimentar el motor — ese único hallazgo puede cambiar la estimación de todo el bloque clínico.
