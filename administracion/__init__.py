"""Épica Administración.

    - ``usuarios``: ADM-01 — gestión de usuarios institucionales, roles y
      permisos (CRUD con baja lógica, asignación de rol, restablecimiento de
      contraseña), solo para el rol ``administrador`` y siempre auditada.
    - ``api``: la misma gestión por HTTP (autenticación HTTP Basic sobre el
      login de SEC-01).
"""
