# SEC-01 — Autenticación y control de acceso por rol

## Historia de usuario

Como administrador del sistema, quiero controlar el acceso mediante
autenticación segura y roles (oncólogo, enfermería, administrativo,
auditor), para que cada usuario vea solo lo que le corresponde.

## Qué implementa

- `seguridad/models.py`: `Rol` (oncólogo, enfermería, administrativo,
  auditor), `Usuario`, `ResultadoAutenticacion`, `ResultadoAutorizacion`.
- `seguridad/autenticacion.py`: alta de usuarios (`registrar_usuario`) y
  login (`autenticar`), con hash de contraseña PBKDF2-HMAC-SHA256 con sal
  por usuario (biblioteca estándar, sin dependencias nuevas) y bloqueo
  temporal tras intentos fallidos.
- `seguridad/autorizacion.py`: modelo de permisos por rol
  (`PERMISOS_POR_ROL`) y `verificar_permiso(usuario, accion)`. Una acción
  sin reglas explícitas se deniega a todos los roles (fail-closed).

## Criterios de aceptación

```
Dado un usuario con rol "enfermería"
Cuando intenta acceder a la función de confirmar tratamiento (TX-04)
Entonces el sistema le deniega el acceso porque esa acción está
restringida al rol oncólogo

Dado múltiples intentos fallidos de login
Cuando se supera el umbral configurado (5 intentos)
Entonces la cuenta se bloquea temporalmente (15 minutos) y se notifica al
usuario
```

El segundo criterio se cubre en `seguridad/autenticacion.py`:
`UMBRAL_INTENTOS_FALLIDOS` y `DURACION_BLOQUEO_MINUTOS`. Un intento más
durante el bloqueo se rechaza sin importar si la contraseña es correcta, y
no reinicia el contador. Este prototipo no tiene canal de mensajería
propio (correo/SMS): "notificar al usuario" se resuelve devolviendo el
mensaje explícito en `ResultadoAutenticacion.motivo_rechazo`, que es lo
que la capa que llame (API, CLI, demo) debe mostrarle a quien intenta
iniciar sesión.

## Integración real con TX-04

`clinical_decision.registro.registrar_decision_tratamiento` acepta un
parámetro opcional `usuario: Optional[Usuario] = None`. Si se provee, se
exige `verificar_permiso(usuario, Accion.CONFIRMAR_TRATAMIENTO)` antes de
registrar cualquier decisión (accept/modify/reject). Si se omite (valor
por defecto), no se aplica ningún control de acceso — así las llamadas
existentes (p. ej. la tool de `tx_clinica` usada por el agente) siguen
funcionando exactamente igual que antes de esta historia. Ver
`tests/clinical_decision/test_registro_control_de_acceso.py`.

## Cómo probarlo

```
python -m pytest tests/seguridad tests/clinical_decision -q
python -m seguridad.demo
```

## Alcance y limitaciones

- La gestión de usuarios (alta, cambio de rol, baja, restablecer contraseña)
  es **ADM-01**: ver `docs/administracion_usuarios.md`. El rol
  `administrador` que la ejecuta no tiene permisos clínicos.
- No incluye MFA (mencionado como "ideal" en el backlog, no obligatorio en
  los criterios de aceptación).
- No hay todavía una capa HTTP de login (endpoint `/login`) ni gestión de
  sesiones/tokens: `autenticar` devuelve un `Usuario` en memoria, que es lo
  que consume `verificar_permiso`. Conectar esto a la API real de
  `patients/` (o a un futuro `sesiones/`) queda fuera del alcance de esta
  historia tal como está redactada.
- La integración por rol solo se conectó explícitamente a TX-04, que es el
  caso citado literalmente en el criterio de aceptación de SEC-01. El
  mismo mecanismo (`verificar_permiso`) ya modela `Accion.CONFIRMAR_ESTADIFICACION`
  (EST-02) y `Accion.REGISTRAR_JUICIO_DIAGNOSTICO` (DX-03) para conectarlos
  de la misma forma cuando se priorice.
