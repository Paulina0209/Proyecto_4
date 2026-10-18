"""Interfaz web del copiloto oncológico (núcleo clínico).

    python -m frontend.demo            # con datos sintéticos, en https://127.0.0.1:8443
    python -m seguridad.servidor_tls --app frontend.servidor:app --cert cert.pem --key clave.pem

Es una pasarela (``frontend.servidor``) que sirve páginas estáticas (HTML + JS sin paso de
compilación) y deja pasar a las APIs existentes (pacientes y administración) SOLO después de
autenticar con SEC-01 y de comprobar permisos por rol. Ver ``docs/frontend.md``.
"""
