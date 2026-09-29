# AUD-01 y AUD-02 — Auditoría y trazabilidad

## AUD-01 — Registro de auditoría de accesos y acciones

### Historia de usuario

Como administrador, quiero un registro de auditoría de accesos y acciones
sobre cada expediente, para poder reconstruir quién hizo qué y cuándo.

### Qué implementa

- `auditoria/models.py`: `TipoAccion` (ver/editar/exportar, más las acciones de privacidad de
  NFR-06: `configurar_politica_datos`, `registrar_autorizacion`,
  `gestionar_derechos_titular`), `EventoAcceso`.
- `auditoria/registro_acceso.py`: `registrar_acceso` (solo-inserción) y
  las consultas `obtener_eventos_de_paciente` / `obtener_eventos_de_usuario`.

Mismo patrón que el resto de tablas de auditoría del proyecto
(`confirmaciones_estadificacion` de EST-02, `juicios_clinicos_dx` de
DX-03, `decisiones_tratamiento` de TX-04): la tabla `eventos_acceso` es de
solo-inserción y el módulo, a propósito, **no expone ninguna función de
UPDATE ni DELETE** — es lo que sostiene el criterio de aceptación "de
forma no editable" (`tests/auditoria/test_registro_acceso.py` verifica
explícitamente que esas funciones no existen en el módulo).

### Criterio de aceptación

```
Dado cualquier acceso a un expediente
Cuando ocurre
Entonces queda registrado con usuario, fecha/hora, y acción realizada, de
forma no editable
```

### Integración real

`patients/api.py` — `GET /pacientes/{paciente_id}` acepta un query param
opcional `usuario_id`. Si se provee, el acceso queda registrado en
`eventos_acceso` (misma base de datos que `patients`). Si se omite (valor
por defecto), no se registra nada — así los tests y clientes existentes de
esa API no se ven afectados. Ver
`tests/patients/test_api.py::test_leer_paciente_con_usuario_id_registra_el_acceso_en_auditoria`.

## AUD-02 — Trazabilidad de recomendaciones de IA

### Historia de usuario

Como responsable regulatorio, quiero que cada recomendación de IA quede
trazada (versión del modelo, fuentes usadas, decisión del médico), para
fines de auditoría clínica y legal.

### Qué implementa

`auditoria/trazabilidad_ia.py` — `obtener_trazabilidad_ia_paciente`.

**No persiste nada nuevo.** DX-03, EST-02 y TX-04 ya registraban, cada uno
por su lado, un snapshot de lo que sugería el sistema junto con la
decisión del médico:

| Dominio | Módulo | Función de lectura ya existente |
|---|---|---|
| DX-03 | `dx_clinica.juicio_clinico` | `obtener_historial_juicios` |
| EST-02 | `estadificacion.confirmacion` | `obtener_historial_confirmaciones` |
| TX-04 | `clinical_decision.registro` | `obtener_historial_decisiones` (nueva, ver Notas) |

Lo que faltaba —y que las tres implementaciones señalaban explícitamente
en sus propios comentarios como pendiente— era un punto único donde
consultar los tres a la vez por paciente. `obtener_trazabilidad_ia_paciente`
es ese punto único: recibe una conexión opcional por dominio y devuelve
una lista unificada de `RegistroTrazabilidadIA` (recomendación del
sistema + decisión del médico + si difirió), ordenada del más reciente al
más antiguo.

### Criterio de aceptación

```
Dado que la IA genera una recomendación
Cuando el médico toma una decisión al respecto (acepta/modifica/rechaza)
Entonces ambos elementos (recomendación y decisión) quedan vinculados y
son consultables posteriormente para auditoría
```

### Notas

- `clinical_decision/registro.py` tenía función de escritura
  (`registrar_decision_tratamiento`) pero **ninguna función de lectura**.
  Se agregaron `obtener_decision_por_id`, `obtener_historial_decisiones`,
  `obtener_decision_vigente` y `crear_conexion` (mismo patrón que los
  otros dos dominios) — sin tocar el comportamiento de escritura existente.
- Cada dominio calcula `difiere_de_sugerencia` con su propia semántica
  (DX-03 nunca lo calcula porque el juicio médico nunca se compara contra
  el sistema); se documenta como `Optional[bool]` en vez de forzar un
  valor.

## Cómo probarlo

```
python -m pytest tests/auditoria -q
python -m auditoria.demo
```
