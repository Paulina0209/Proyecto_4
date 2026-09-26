"""Datos ficticios para probar el dashboard 360 (PAC-03) de punta a punta,
sin depender de la base de datos real todavía.

Dos pacientes, a propósito:
  - "María Gómez": expediente COMPLETO -- ejercita AC1 (diagnóstico,
    estadio, tratamiento más reciente, alertas y accesos rápidos, todo
    presente).
  - "Carlos Ruiz": expediente INCOMPLETO (sin diagnóstico, sin estadio,
    sin tratamiento) -- ejercita AC2 (el indicador de información
    faltante debe encenderse, en vez de mostrar el dashboard como si
    estuviera completo).

Ambos bajo oncologo_id=1, mismo oncólogo demo que ya se usa en el resto
del proyecto (p. ej. paciente_de_prueba.sql de tx_clinica).
"""
from __future__ import annotations

import sqlite3


def sembrar_datos_ficticios(conn: sqlite3.Connection) -> dict[str, int]:
    """Devuelve los ids de los pacientes sembrados, por nombre clave --
    mismo patrón que historia_clinica_mock.seed.sembrar_datos_sinteticos."""

    cur = conn.execute(
        "INSERT INTO pacientes_360 "
        "(nombre, oncologo_id, diagnostico_principal, estadio, fecha_diagnostico) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            "María Gómez",
            1,
            "NSCLC metastásico no oncogénico",
            "IV",
            "2026-01-15",
        ),
    )
    id_completo = cur.lastrowid

    conn.execute(
        "INSERT INTO tratamientos_360 (paciente_id, regimen, estado, fecha_inicio) VALUES (?, ?, ?, ?)",
        (id_completo, "pembrolizumab + pemetrexed", "en_tratamiento", "2026-06-01"),
    )
    # Tratamiento previo, más antiguo -- confirma que el dashboard toma
    # el MÁS RECIENTE (fecha_inicio mayor), no el primero insertado.
    conn.execute(
        "INSERT INTO tratamientos_360 (paciente_id, regimen, estado, fecha_inicio) VALUES (?, ?, ?, ?)",
        (id_completo, "carboplatino + paclitaxel", "finalizado", "2026-02-10"),
    )

    conn.execute(
        "INSERT INTO alertas_360 (paciente_id, tipo, severidad, descripcion, fecha, resuelta) "
        "VALUES (?, ?, ?, ?, ?, 0)",
        (
            id_completo, "interaccion", "alta",
            "Interacción mayor: régimen actual + inductor fuerte de CYP3A4 concomitante.",
            "2026-09-10",
        ),
    )
    conn.execute(
        "INSERT INTO alertas_360 (paciente_id, tipo, severidad, descripcion, fecha, resuelta) "
        "VALUES (?, ?, ?, ?, ?, 0)",
        (id_completo, "estudio_pendiente", "media", "TAC de tórax de control pendiente de agendar.", "2026-09-05"),
    )
    # Alerta YA resuelta -- no debe aparecer en alertas_activas.
    conn.execute(
        "INSERT INTO alertas_360 (paciente_id, tipo, severidad, descripcion, fecha, resuelta) "
        "VALUES (?, ?, ?, ?, ?, 1)",
        (id_completo, "estudio_pendiente", "baja", "Laboratorio de control ya revisado.", "2026-08-01"),
    )

    conn.execute(
        "INSERT INTO labs_360 (paciente_id, fecha, prueba, resumen) VALUES (?, ?, ?, ?)",
        (id_completo, "2026-09-12", "Hemograma", "Sin alteraciones significativas."),
    )
    conn.execute(
        "INSERT INTO labs_360 (paciente_id, fecha, prueba, resumen) VALUES (?, ?, ?, ?)",
        (id_completo, "2026-08-20", "Función hepática", "Transaminasas levemente elevadas."),
    )
    conn.execute(
        "INSERT INTO imagenes_360 (paciente_id, fecha, modalidad, resumen) VALUES (?, ?, ?, ?)",
        (id_completo, "2026-09-01", "TAC tórax", "Enfermedad estable respecto al estudio previo."),
    )
    conn.execute(
        "INSERT INTO notas_360 (paciente_id, fecha, resumen) VALUES (?, ?, ?)",
        (id_completo, "2026-09-13", "Consulta de seguimiento: buena tolerancia al tratamiento actual."),
    )
    conn.execute(
        "INSERT INTO notas_360 (paciente_id, fecha, resumen) VALUES (?, ?, ?)",
        (id_completo, "2026-06-01", "Consulta de inicio de tratamiento de primera línea."),
    )

    # --- Paciente con información incompleta (AC2) ---------------------
    cur = conn.execute(
        "INSERT INTO pacientes_360 "
        "(nombre, oncologo_id, diagnostico_principal, estadio, fecha_diagnostico) "
        "VALUES (?, ?, ?, ?, ?)",
        ("Carlos Ruiz", 1, None, None, None),
    )
    id_incompleto = cur.lastrowid

    # Sin tratamientos, sin alertas -- recién remitido, expediente apenas
    # empezando. Sí tiene un laboratorio inicial, para probar que el
    # dashboard puede mostrar accesos rápidos parciales aunque falte lo
    # clínico clave (una cosa no bloquea a la otra).
    conn.execute(
        "INSERT INTO labs_360 (paciente_id, fecha, prueba, resumen) VALUES (?, ?, ?, ?)",
        (id_incompleto, "2026-09-14", "Hemograma inicial", "Pendiente de interpretación por oncología."),
    )

    conn.commit()
    return {"paciente_completo": id_completo, "paciente_incompleto": id_incompleto}
