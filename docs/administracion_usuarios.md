# ADM-01 — Gestión de usuarios, roles y permisos

## Historia de usuario

Como administrador del sistema, quiero gestionar usuarios, roles y permisos,
para mantener el control de acceso institucional.

El backlog solo trae la descripción ("CRUD de usuarios institucionales y
asignación de roles/permisos"), sin criterios de aceptación. Los siguientes
son los que se propusieron para implementarla; confírmalos o ajústalos.

## Criterios de aceptación propuestos

```
AC1  Dado un administrador
     Cuando crea, edita, cambia de rol o desactiva un usuario
     Entonces el cambio se refleja en su inicio de sesión y en sus permisos (SEC-01)

AC2  Dado un usuario que no es administrador
     Cuando intenta gestionar usuarios
     Entonces el sistema lo deniega y el intento queda registrado

AC3  Dada cualquier operación de gestión
     Cuando se ejecuta
     Entonces queda en la auditoría (AUD-01), nunca se pierde el último
     administrador activo y nadie se borra (baja lógica)
```

## Qué implementa

- `administracion/usuarios.py`: `crear_usuario`, `obtener_usuario`,
  `listar_usuarios` (filtros por rol, estado y texto), `actualizar_usuario`,
  `asignar_rol`, `desactivar_usuario` / `reactivar_usuario`,
  `restablecer_contrasena`, `matriz_de_permisos`, `eventos_de_administracion`
  y `crear_primer_administrador`.
- `administracion/api.py`: la misma gestión por HTTP (ver abajo).
- Cambios en SEC-01 y AUD-01, todos aditivos: `Rol.ADMINISTRADOR`,
  `Accion.GESTIONAR_USUARIOS`, `permisos_del_rol`, `insertar_usuario` y
  `establecer_contrasena` en `seguridad/`, y `TipoAccion.GESTIONAR_USUARIOS`
  en `auditoria/`.
- Tabla `perfiles_usuario` (nombre completo, correo, quién creó, baja): una
  tabla lateral de `usuarios`, así el esquema de login de SEC-01 no cambia y
  los usuarios dados de alta solo con `registrar_usuario` siguen existiendo
  (sin perfil).

## Decisiones de diseño

- **Permisos = permisos del rol.** `PERMISOS_POR_ROL` sigue siendo la única
  tabla; asignar un rol es asignar sus permisos y `matriz_de_permisos` los
  muestra. No hay permisos sueltos por usuario: revisarlos persona por
  persona no escala y complica la auditoría. Si la institución necesita
  perfiles intermedios, la vía es un rol nuevo, no excepciones por usuario.
- **Solo el rol `administrador`** (nuevo) gestiona usuarios. Es un rol de
  administración: no tiene acceso clínico a los expedientes (ver
  `docs/seguridad.md`). El `administrador_clinico` de CFG-01 es otro rol y no
  puede gestionar usuarios.
- **El actor se vuelve a leer de la base** en cada operación. Un
  administrador desactivado, degradado, o un objeto `Usuario` con el rol
  alterado a mano, no puede operar.
- **No se borra a nadie**: "eliminar" es desactivar (baja lógica). AUD-01 y
  las decisiones clínicas guardan el id del usuario y deben seguir
  resolviéndose. No existe función de borrado.
- **Nunca sin administrador**: nadie cambia su propio rol ni se desactiva, y
  no se puede quitar el rol ni desactivar al último administrador activo. El
  primero se crea con `python -m administracion crear-admin`, que solo
  funciona mientras no haya ninguno.
- **Auditoría completa**: cada operación y cada intento denegado queda en
  `eventos_acceso` (`accion = gestionar_usuarios`) con quién, qué y sobre
  quién; los cambios de rol y las bajas guardan su motivo. Nunca se guarda
  una contraseña ni su hash. El cambio y su evento se confirman juntos o
  ninguno.
- **Motivo obligatorio** al cambiar de rol y al desactivar.
- **El nombre de usuario no se edita** (lo referencian los registros
  históricos). Se guarda en minúsculas; la unicidad no distingue mayúsculas.
- **Política de contraseña** (alta y restablecimiento): mínimo 10
  caracteres, letras y números, y sin el nombre de usuario. Restablecer la
  contraseña también levanta el bloqueo por intentos fallidos.

## API

`uvicorn administracion.api:app` (base: `COPILOTO_USUARIOS_DB`, por defecto
`data/usuarios.db`, ya ignorada por git).

Autenticación: **HTTP Basic sobre el login de SEC-01** en cada petición, así
que el bloqueo por intentos fallidos también aplica. 401 si faltan
credenciales o son incorrectas (el mensaje no revela si el usuario existe) y
403 si el usuario no es administrador.

| Método y ruta | Qué hace |
|---|---|
| `POST /usuarios` | Crear (201). 400 con todos los errores; 409 si el usuario o el correo ya existen |
| `GET /usuarios?rol=&activo=&texto=` | Listar con filtros |
| `GET /usuarios/{id}` | Ver uno (404 si no existe) |
| `PATCH /usuarios/{id}` | Editar nombre completo y/o correo |
| `PUT /usuarios/{id}/rol` | Asignar rol (`{"rol", "motivo"}`) |
| `POST /usuarios/{id}/desactivar` · `/reactivar` | Baja lógica y su reversa |
| `POST /usuarios/{id}/contrasena` | Restablecer contraseña |
| `GET /roles` | Permisos que da cada rol |
| `GET /auditoria/usuarios?usuario_id=` | Historial de gestión (AUD-01) |

## Límites conocidos

- **No hay sesiones ni tokens** (SEC-01 los dejó fuera): por eso Basic en cada
  petición. Debe servirse solo detrás de TLS (SEC-02, pendiente).
- Los intentos de inicio de sesión fallidos no se auditan en AUD-01 (SEC-01
  solo los cuenta para el bloqueo).
- El resto de la API (`patients/api.py`) todavía recibe `oncologo_id` por
  parámetro (TODO SEC-01): esta historia gestiona quién existe y qué rol
  tiene, pero no conecta esa identidad a las demás rutas.
- No hay autoservicio de "olvidé mi contraseña" ni MFA.
- La base de usuarios es independiente de las de `patients` y `expediente`.

## Cómo probarlo

```
python -m pytest tests/administracion tests/seguridad tests/auditoria -q
python -m administracion.demo
python -m administracion crear-admin     # primer administrador (base real)
uvicorn administracion.api:app
```
