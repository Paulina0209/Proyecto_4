# CFG-01 — Configuración de guías clínicas institucionales

> Como administrador clínico, quiero configurar qué guías clínicas usa la
> institución por defecto, para adaptar el sistema a sus protocolos internos.

Módulo: `configuracion/guias_institucionales.py`. Esquema:
`configuracion/schema_configuracion.sql`. Dependencia: EV-01
(`evidencia_clinica`).

## Uso

```python
from configuracion.guias_institucionales import (
    ProtocoloInterno, configurar_guias, obtener_configuracion_vigente,
    modulos_habilitados, buscar_evidencia_institucional,
)

resultado = configurar_guias(
    conn, administrador_clinico, ["NCCN", "ESMO"],        # orden = prioridad
    motivo="Acta del comité de oncología 2026-09",
    protocolo_interno=ProtocoloInterno("Protocolo de mama v3", "DOC-ONC-017"),
)
resultado.advertencias          # p. ej. "NCCN no tiene módulos computables..."

obtener_configuracion_vigente(conn)   # organizaciones, protocolo, versión, módulos
modulos_habilitados(conn)             # carpetas de guidelines/ habilitadas
buscar_evidencia_institucional(conn, "cáncer de mama triple negativo")   # EV-01 filtrado
```

## Comportamiento

- **Opciones de la historia: NCCN, ESMO o protocolo propio.** Las
  organizaciones reconocidas están en `ORGANIZACIONES_RECONOCIDAS`. El
  protocolo interno se registra con nombre y referencia a su documento
  oficial.
- **Por defecto.** Mientras nadie configure nada, se usan todas las
  organizaciones con módulos disponibles y la configuración se marca
  `es_por_defecto_del_sistema`.
- **Guías conjuntas.** Una guía como "ESMO–EURACAN" (melanoma uveal) cuenta
  como ESMO.
- **EV-01.** `EvidenceSearchService.search(..., organizations=[...])` busca
  solo en las organizaciones indicadas y, a igual puntaje, pone primero la
  preferida. Sin ese parámetro se comporta exactamente como antes.
- **TX-01 y demás consumidores.** `modulos_habilitados()` devuelve las carpetas
  de `guidelines/` que corresponden. `tx_clinica` no se modificó en esta
  historia; puede filtrar su selección de módulo con esta función.

## Salvaguardas (riesgos CFG del backlog)

| Riesgo | Mitigación |
|---|---|
| Una guía mal configurada afecta a todos los pacientes | Las organizaciones desconocidas o repetidas se rechazan. Guardar una configuración sin ningún módulo computable exige `confirmar_sin_modulos=True`. Si una organización elegida no tiene módulos, se emite una advertencia |
| Los cambios de configuración sin versionar dificultan la trazabilidad | Cada cambio es una versión nueva (solo inserción, con triggers) con autor, fecha y motivo obligatorio. Se consultan con `historial_configuracion` y `configuracion_en_fecha` |
| Configuración expuesta a usuarios sin el perfil adecuado | Solo el rol nuevo `administrador_clinico` tiene `Accion.CONFIGURAR_GUIAS_INSTITUCIONALES` (SEC-01). Los intentos denegados también quedan auditados |
| Auditoría | Cada cambio y cada intento denegado genera un evento `configurar_guias` en `eventos_acceso` (AUD-01) |

## Límite conocido

`guidelines/` solo tiene hoy módulos computables de ESMO; NCCN está documentada
en `docs/guidelines/nccn` pero sin reglas cargadas. Por eso elegir solo NCCN deja
al sistema sin módulos, y eso exige confirmación explícita.
