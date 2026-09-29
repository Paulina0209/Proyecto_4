"""Importación de pacientes desde cBioPortal (patients/cbioportal.py).

Sin red: un cliente falso devuelve respuestas con la misma forma que la
API real (estudio msk_chord_2024 y uno TCGA).
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from patients import cbioportal
from patients.busqueda import buscar_pacientes
from patients.cbioportal import ErrorCBioPortal, importar_estudio, traducir_paciente
from patients.models import EstadoTratamiento, FiltrosBusqueda
from patients.resumen_360 import obtener_resumen_360

ESTUDIO = "msk_chord_2024"


def _evento(tipo, inicio, fin=None, **atributos):
    evento = {
        "eventType": tipo,
        "startNumberOfDaysSinceDiagnosis": inicio,
        "attributes": [{"key": k, "value": v} for k, v in atributos.items()],
    }
    if fin is not None:
        evento["endNumberOfDaysSinceDiagnosis"] = fin
    return evento


def _mutacion(muestra, gen, cambio):
    return {"sampleId": muestra, "gene": {"hugoGeneSymbol": gen}, "proteinChange": cambio}


# P-1: pulmón, vivo, crizotinib en curso con una radioterapia corta encima.
# P-2: pulmón, fallecido, quimio terminada hace tiempo.
# P-3: mama (para el filtro por tipo de cáncer).
PACIENTES = {
    "P-1": {
        "tipo": "Non-Small Cell Lung Cancer",
        "clinicos": {"GENDER": "Female", "CURRENT_AGE_DEID": "68", "OS_STATUS": "0:LIVING"},
        "detallado": "Lung Adenocarcinoma",
        "eventos": [
            _evento("Diagnosis", -10, SUBTYPE="Primary", AJCC="IV", STAGE_CDM_DERIVED="Stage 4"),
            _evento("Treatment", 0, 90, SUBTYPE="Chemo", AGENT="CARBOPLATIN"),
            _evento("Treatment", 0, 90, SUBTYPE="Chemo", AGENT="PEMETREXED"),
            _evento("Treatment", 200, 500, SUBTYPE="Targeted", AGENT="CRIZOTINIB"),
            _evento("Treatment", 300, 310, SUBTYPE="Radiation Therapy"),
            _evento("Treatment", -30, SUBTYPE="Prior Medications to MSK"),
            _evento("Treatment", 400, 400, SUBTYPE="Bone Treatment", AGENT="ZOLEDRONIC ACID"),
            _evento("Lab_Test", 100, TEST="CEA", RESULT="1.4", LR_UNIT_MEASURE="ng/ml"),
            _evento("Diagnosis", 480, SUBTYPE="Progression", PROCEDURE_TYPE="CT", PROGRESSION="N"),
            _evento("Diagnosis", 500, SUBTYPE="Performance Status", ECOG="1"),
            _evento("Sequencing", 20, SAMPLE_ID="P-1-T01"),
        ],
        "mutaciones": [_mutacion("P-1-T01", "TP53", "Q331*"), _mutacion("P-1-T01", "ALK", "F1174L")],
    },
    "P-2": {
        "tipo": "Non-Small Cell Lung Cancer",
        "clinicos": {"GENDER": "Male", "OS_STATUS": "1:DECEASED"},
        "detallado": "Lung Squamous Cell Carcinoma",
        "eventos": [
            _evento("Treatment", 0, 60, SUBTYPE="Chemo", AGENT="CISPLATIN"),
            _evento("Diagnosis", 400, SUBTYPE="Performance Status", ECOG="3"),
        ],
        "mutaciones": [],
    },
    "P-3": {
        "tipo": "Breast Cancer",
        "clinicos": {"GENDER": "Female"},
        "detallado": "Breast Invasive Ductal Carcinoma",
        "eventos": [],
        "mutaciones": [],
    },
}


class ClienteFalso:
    def __init__(self, pacientes=PACIENTES):
        self.pacientes = pacientes
        self.eventos_pedidos: list[str] = []

    def tipo_cancer_por_muestra(self, estudio):
        return [
            {"sampleId": f"{p}-T01", "patientId": p, "value": datos["tipo"]}
            for p, datos in self.pacientes.items()
        ]

    def datos_clinicos(self, estudio, tipo, ids):
        filas = []
        for entidad in ids:
            if tipo == "PATIENT":
                atributos, clave = self.pacientes[entidad]["clinicos"], "patientId"
            else:
                atributos = {"CANCER_TYPE_DETAILED": self.pacientes[entidad.removesuffix("-T01")]["detallado"]}
                clave = "sampleId"
            filas += [{clave: entidad, "clinicalAttributeId": k, "value": v} for k, v in atributos.items()]
        return filas

    def eventos(self, estudio, paciente):
        self.eventos_pedidos.append(paciente)
        return self.pacientes[paciente]["eventos"]

    def mutaciones(self, estudio, muestras):
        return [m for p in self.pacientes.values() for m in p["mutaciones"] if m["sampleId"] in muestras]


def _importar(conn, **kwargs):
    kwargs.setdefault("cliente", ClienteFalso())
    return importar_estudio(conn, estudio=ESTUDIO, **kwargs)


def _id_local(conn, paciente_externo):
    return conn.execute(
        "SELECT paciente_id FROM pacientes_cbioportal WHERE paciente_externo_id = ?", (paciente_externo,)
    ).fetchone()[0]


# ---------------------------------------------------------------------------
# Importación de punta a punta
# ---------------------------------------------------------------------------

def test_importa_en_las_mismas_tablas_que_usan_busqueda_y_360(conn):
    resultado = _importar(conn, oncologo_id=7)
    assert len(resultado.importados) == 3

    busqueda = buscar_pacientes(conn, FiltrosBusqueda(oncologo_id=7, diagnostico="lung"))
    assert {p.nombre_completo for p in busqueda.items} == {"Paciente P-1", "Paciente P-2"}

    resumen = obtener_resumen_360(conn, _id_local(conn, "P-1"), oncologo_id=7)
    assert resumen.diagnostico_principal == "Lung Adenocarcinoma"
    assert resumen.estadio == "IV"
    assert resumen.tratamiento_mas_reciente.regimen == "Crizotinib + Radiation therapy"
    assert resumen.tratamiento_mas_reciente.estado == EstadoTratamiento.EN_TRATAMIENTO.value
    assert {e.titulo for e in resumen.labs_recientes} == {"CEA", "Secuenciación tumoral P-1-T01"}
    assert [(e.titulo, e.resumen) for e in resumen.imagenes_recientes] == [
        ("TC", "Sin progresión según el informe (NLP).")
    ]
    assert [n.resumen for n in resumen.notas_recientes] == ["Estado funcional ECOG 1."]
    assert resumen.campos_faltantes == ()


def test_identidad_desidentificada_sin_inventar_datos(conn):
    _importar(conn)
    fila = conn.execute("SELECT * FROM pacientes WHERE id = ?", (_id_local(conn, "P-1"),)).fetchone()

    assert fila["nombre_completo"] == "Paciente P-1"
    assert fila["tipo_identificacion"] == "cbioportal"
    assert fila["numero_identificacion"] == f"{ESTUDIO}:P-1"
    assert fila["sexo"] == "femenino"
    assert fila["fecha_nacimiento"] is None
    assert fila["telefono"] is None and fila["email"] is None
    assert "Edad desidentificada: 68 años" in fila["antecedentes_personales"]
    assert fila["registro_completo"] == 0


def test_volver_a_importar_no_duplica_y_trae_los_siguientes(conn):
    primera = _importar(conn, limite=2)
    assert len(primera.importados) == 2

    cliente = ClienteFalso()
    segunda = _importar(conn, limite=2, cliente=cliente)
    assert len(segunda.importados) == 1
    assert segunda.omitidos == 2
    assert cliente.eventos_pedidos == ["P-3"]
    assert conn.execute("SELECT COUNT(*) FROM pacientes").fetchone()[0] == 3


def test_filtra_por_tipo_de_cancer_sin_distinguir_mayusculas(conn):
    resultado = _importar(conn, tipo_cancer="breast")
    assert len(resultado.importados) == 1
    assert conn.execute("SELECT nombre_completo FROM pacientes").fetchone()[0] == "Paciente P-3"


def test_sin_pacientes_nuevos_no_llama_a_la_api_por_eventos(conn):
    _importar(conn)
    cliente = ClienteFalso()
    resultado = _importar(conn, cliente=cliente)
    assert resultado.importados == []
    assert cliente.eventos_pedidos == []


def test_error_de_red_no_deja_pacientes_a_medias(conn):
    class ClienteQueFalla(ClienteFalso):
        def eventos(self, estudio, paciente):
            raise ErrorCBioPortal("sin conexión")

    with pytest.raises(ErrorCBioPortal):
        _importar(conn, cliente=ClienteQueFalla())
    assert conn.execute("SELECT COUNT(*) FROM pacientes").fetchone()[0] == 0


def test_mutaciones_sin_perfil_no_rompen_la_importacion(conn):
    class ClienteSinMutaciones(ClienteFalso):
        def mutaciones(self, estudio, muestras):
            return []

    _importar(conn, cliente=ClienteSinMutaciones())
    resumen = conn.execute(
        "SELECT resumen FROM estudios WHERE paciente_id = ? AND nombre LIKE 'Secuenciación%'",
        (_id_local(conn, "P-1"),),
    ).fetchone()[0]
    assert resumen == "Sin mutaciones somáticas reportadas en el panel."


# ---------------------------------------------------------------------------
# Fechas
# ---------------------------------------------------------------------------

def test_fechas_ancladas_al_ultimo_evento_y_nunca_futuras(conn):
    _importar(conn)
    paciente_id = _id_local(conn, "P-1")
    hoy = date.today()

    fechas = [
        date.fromisoformat(f[0])
        for f in conn.execute(
            "SELECT fecha FROM estudios WHERE paciente_id = ? UNION ALL "
            "SELECT fecha FROM consultas WHERE paciente_id = ? UNION ALL "
            "SELECT fecha_inicio FROM tratamientos WHERE paciente_id = ?",
            (paciente_id,) * 3,
        )
    ]
    assert max(fechas) == hoy  # ECOG del día 500, el último evento
    # Los intervalos entre eventos se conservan: CEA fue el día 100.
    cea = conn.execute(
        "SELECT fecha FROM estudios WHERE paciente_id = ? AND nombre = 'CEA'", (paciente_id,)
    ).fetchone()[0]
    assert date.fromisoformat(cea) == hoy - timedelta(days=400)


# ---------------------------------------------------------------------------
# Traducción (sin base de datos)
# ---------------------------------------------------------------------------

def _traducir(eventos, clinicos=None, detallado="Lung Adenocarcinoma", mutaciones=None):
    return traducir_paciente(
        ESTUDIO, "P-9", clinicos or {}, {"P-9-T01": {"CANCER_TYPE_DETAILED": detallado}},
        eventos, {"P-9-T01": mutaciones or []},
    )


def test_tratamientos_solapados_forman_una_linea():
    expediente = _traducir([
        _evento("Treatment", 0, 90, SUBTYPE="Chemo", AGENT="CARBOPLATIN"),
        _evento("Treatment", 0, 90, SUBTYPE="Chemo", AGENT="PEMETREXED"),
        _evento("Treatment", 200, 210, SUBTYPE="Targeted", AGENT="ERLOTINIB"),
    ])
    assert [(dia, regimen) for dia, _, regimen in expediente.tratamientos] == [
        (0, "Carboplatin + Pemetrexed"),
        (200, "Erlotinib"),
    ]


def test_administraciones_separadas_son_cursos_distintos():
    expediente = _traducir([
        _evento("Treatment", 0, 10, AGENT="NIVOLUMAB"),
        _evento("Treatment", 30, 40, AGENT="NIVOLUMAB"),
        _evento("Treatment", 40 + cbioportal.DIAS_ENTRE_CURSOS + 1, 400, AGENT="NIVOLUMAB"),
    ])
    assert [dia for dia, _, _ in expediente.tratamientos] == [0, 40 + cbioportal.DIAS_ENTRE_CURSOS + 1]


@pytest.mark.parametrize(
    ("clinicos", "fin_tratamiento", "estado_esperado"),
    [
        ({"OS_STATUS": "0:LIVING"}, 500, EstadoTratamiento.EN_TRATAMIENTO),
        ({"OS_STATUS": "0:LIVING"}, 100, EstadoTratamiento.EN_SEGUIMIENTO),
        ({"OS_STATUS": "1:DECEASED"}, 500, EstadoTratamiento.FINALIZADO),
    ],
)
def test_estado_de_la_ultima_linea(clinicos, fin_tratamiento, estado_esperado):
    expediente = _traducir(
        [
            _evento("Treatment", 0, 50, AGENT="CISPLATIN"),
            _evento("Treatment", 80, fin_tratamiento, AGENT="OSIMERTINIB"),
            _evento("Diagnosis", 500, SUBTYPE="Performance Status", ECOG="0"),
        ],
        clinicos=clinicos,
    )
    estados = [estado for _, estado, _ in expediente.tratamientos]
    assert estados == [EstadoTratamiento.FINALIZADO.value, estado_esperado.value]


def test_excluye_eventos_que_no_son_lineas_oncologicas():
    expediente = _traducir([
        _evento("Treatment", -30, SUBTYPE="Prior Medications to MSK"),
        _evento("Treatment", 10, 20, SUBTYPE="Bone Treatment", AGENT="DENOSUMAB"),
    ])
    assert expediente.tratamientos == []


@pytest.mark.parametrize(
    ("eventos", "clinicos", "estadio"),
    [
        ([_evento("Diagnosis", 0, SUBTYPE="Primary", AJCC="iiia")], {}, "IIIA"),
        # Código de registro 99 = desconocido: se usa el estadio derivado.
        ([_evento("Diagnosis", 0, SUBTYPE="Primary", AJCC="99", STAGE_CDM_DERIVED="Stage 4")], {}, "Stage 4"),
        ([], {"AJCC_PATHOLOGIC_TUMOR_STAGE": "STAGE IIB"}, "IIB"),  # TCGA
        ([], {"STAGE_HIGHEST_RECORDED": "Stage 1-3"}, "Stage 1-3"),
        ([], {"AJCC_PATHOLOGIC_TUMOR_STAGE": "[Not Available]"}, None),
    ],
)
def test_estadio_segun_la_fuente(eventos, clinicos, estadio):
    expediente = _traducir(eventos, clinicos=clinicos)
    assert expediente.diagnosticos[0][2] == estadio


def test_sin_tratamientos_el_360_lo_reporta_como_faltante(conn):
    pacientes = {"TCGA-1": {
        "tipo": "Non-Small Cell Lung Cancer", "clinicos": {"SEX": "Male", "AGE": "60", "AJCC_PATHOLOGIC_TUMOR_STAGE": "STAGE IV"},
        "detallado": "Lung Adenocarcinoma", "eventos": [], "mutaciones": [],
    }}
    _importar(conn, cliente=ClienteFalso(pacientes))

    resumen = obtener_resumen_360(conn, _id_local(conn, "TCGA-1"), oncologo_id=1)
    assert resumen.campos_faltantes == ("tratamiento_mas_reciente",)


def test_resumen_de_mutaciones_se_recorta():
    total = cbioportal.MAX_MUTACIONES_RESUMEN + 3
    mutaciones = [_mutacion("P-9-T01", f"GEN{i:02d}", "X1Y") for i in range(total)]
    expediente = _traducir([], mutaciones=mutaciones)
    resumen = next(r for _, tipo, nombre, r in expediente.estudios if nombre.startswith("Secuenciación"))
    assert resumen.endswith("(+3 más)")
    assert resumen.count("X1Y") == cbioportal.MAX_MUTACIONES_RESUMEN


# ---------------------------------------------------------------------------
# API y línea de comandos
# ---------------------------------------------------------------------------

def test_no_se_puede_registrar_a_mano_con_tipo_cbioportal(client):
    r = client.post("/pacientes", json={
        "nombre_completo": "Intento Manual", "sexo": "otro", "tipo_identificacion": "cbioportal",
        "numero_identificacion": f"{ESTUDIO}:P-1", "contacto": {"telefono": "3000000000"}, "oncologo_id": 1,
    })
    assert r.status_code == 400
    assert r.json()["detail"]["errores"][0]["campo"] == "tipo_identificacion"


def test_cli_importa_en_la_base_indicada(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cbioportal, "ClienteCBioPortal", ClienteFalso)
    ruta = tmp_path / "cli.db"

    assert cbioportal.main(["--db", str(ruta), "--limite", "2", "--oncologo", "3"]) == 0
    assert "Listo: 2 paciente(s)" in capsys.readouterr().out

    conn = cbioportal.db.conectar(ruta)
    try:
        assert conn.execute("SELECT COUNT(*) FROM pacientes WHERE oncologo_id = 3").fetchone()[0] == 2
    finally:
        conn.close()


def test_cli_devuelve_error_si_cbioportal_no_responde(tmp_path, monkeypatch, capsys):
    class ClienteCaido(ClienteFalso):
        def tipo_cancer_por_muestra(self, estudio):
            raise ErrorCBioPortal("sin conexión")

    monkeypatch.setattr(cbioportal, "ClienteCBioPortal", ClienteCaido)
    assert cbioportal.main(["--db", str(tmp_path / "cli.db")]) == 1
    assert "sin conexión" in capsys.readouterr().err
