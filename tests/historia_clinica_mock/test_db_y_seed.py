def test_esquema_crea_todas_las_tablas(conn):
    tablas = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert {"pacientes", "consultas", "laboratorios", "imagenologia", "biomarcadores"} <= tablas


def test_seed_inserta_los_pacientes_base(conn_sembrada):
    conn, ids = conn_sembrada
    total = conn.execute("SELECT COUNT(*) AS n FROM pacientes").fetchone()["n"]
    # El seed ha crecido con el proyecto; se fija el mínimo y las invariantes,
    # no un número exacto que hay que editar en cada historia nueva.
    assert total >= 2
    assert ids["paciente_maria"] != ids["paciente_carlos"]


def test_maria_tiene_dos_consultas(conn_sembrada):
    conn, ids = conn_sembrada
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM consultas WHERE paciente_id = ?", (ids["paciente_maria"],)
    ).fetchone()["n"]
    assert total == 2


def test_segunda_consulta_de_maria_no_tiene_labs_ni_imagenes_vinculados(conn_sembrada):
    conn, ids = conn_sembrada
    labs = conn.execute(
        "SELECT COUNT(*) AS n FROM laboratorios WHERE consulta_id = ?", (ids["consulta_maria_2"],)
    ).fetchone()["n"]
    imagenes = conn.execute(
        "SELECT COUNT(*) AS n FROM imagenologia WHERE consulta_id = ?", (ids["consulta_maria_2"],)
    ).fetchone()["n"]
    assert labs == 0
    assert imagenes == 0
