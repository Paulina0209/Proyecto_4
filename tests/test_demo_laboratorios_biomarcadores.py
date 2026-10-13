"""La demo guiada de HC-02/HC-04 parte siempre del estado recién importado:
`restablecer_estado_inicial` descarta lo manual y conserva lo importado."""

from datetime import date, time

from demo_laboratorios_biomarcadores import restablecer_estado_inicial
from historia_clinica.biopsias_biomarcadores import (
    biomarcadores_clave,
    confirmar_biomarcador,
    marcar_potencialmente_accionables,
    registrar_biomarcador,
    registrar_biopsia,
    registrar_episodio,
)
from historia_clinica.db import crear_conexion
from historia_clinica.laboratorios import registrar_recepcion, registrar_resultado_laboratorio


def test_descarta_lo_manual_y_conserva_lo_importado(tmp_path):
    ruta = tmp_path / "copiloto.db"
    conn = crear_conexion(str(ruta))
    pid = conn.execute(
        "INSERT INTO pacientes (nombre, fecha_nacimiento, sexo, identificacion) VALUES ('Paciente Prueba', '1960-01-01', 'otro', 'X-1')"
    ).lastrowid
    # Lo "importado": un laboratorio de cBioPortal y un biomarcador pendiente con su cancer_type.
    lab_importado = conn.execute(
        "INSERT INTO laboratorios (paciente_id, fecha, prueba, valor) VALUES (?, '2025-01-01', 'CEA', '3.1')", (pid,)
    ).lastrowid
    registrar_recepcion(conn, lab_importado, pid, None, "cbioportal")
    sinc = conn.execute(
        "INSERT INTO sincronizaciones_externas (paciente_id, fuente, formato, estado, fecha) VALUES (?, 'cbioportal', 'cbioportal', 'exitosa', '2025-01-01')",
        (pid,),
    ).lastrowid
    dato = conn.execute(
        "INSERT INTO datos_clinicos_estructurados (paciente_id, fecha, variable, valor) VALUES (?, '2025-01-01', 'cancer_type', 'NSCLC')",
        (pid,),
    ).lastrowid
    conn.execute(
        "INSERT INTO registros_importados (sincronizacion_id, fuente, identificador_externo, tabla_destino, fila_id) "
        "VALUES (?, 'cbioportal', 'x:dato', 'datos_clinicos_estructurados', ?)",
        (sinc, dato),
    )
    conn.execute(
        "INSERT INTO biomarcadores (paciente_id, fecha, biomarcador, resultado) VALUES (?, '2025-01-01', 'ALK', "
        "'fusión detectada: EML4-ALK (Protein fusion: in frame) — muestra S1')",
        (pid,),
    )
    conn.commit()
    (pendiente,) = marcar_potencialmente_accionables(conn, pid)

    # Lo "manual" de una prueba anterior.
    registrar_resultado_laboratorio(conn, pid, identificacion="X-1", nombre="Paciente Prueba", prueba="Potasio",
                                    valor="7.1", unidad="mmol/L", fecha=date(2026, 1, 1), hora=time(7, 30))
    confirmar_biomarcador(conn, pid, pendiente, "dra.ruiz", "reordenado")
    registrar_episodio(conn, pid, "Adenocarcinoma de pulmón", "NSCLC")
    biopsia = registrar_biopsia(conn, pid, fecha=date(2026, 1, 2), sitio="Pulmón", procedimiento="Biopsia")
    registrar_biomarcador(conn, pid, biopsia_id=biopsia.id, biomarcador="EGFR", estado="detectada",
                          confirmacion="detectada", metodo="NGS", variante="L858R")
    conn.close()

    assert restablecer_estado_inicial(ruta) > 0

    conn = crear_conexion(str(ruta))
    assert [f[0] for f in conn.execute("SELECT prueba FROM laboratorios")] == ["CEA"]
    assert conn.execute("SELECT COUNT(*) FROM alertas_laboratorio").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM biopsias").fetchone()[0] == 0
    assert [(b.biomarcador, b.relevancia) for b in biomarcadores_clave(conn, pid)] == [("ALK", "pendiente_confirmacion")]
    assert [f[0] for f in conn.execute("SELECT variable FROM datos_clinicos_estructurados")] == ["cancer_type"]
    conn.close()

    # Es idempotente: una segunda vez no hay nada que descartar.
    assert restablecer_estado_inicial(ruta) == 0
