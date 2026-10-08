"""HC-01 — Integración de historia clínica externa (tres criterios de aceptación)."""

import json

import pytest

from documentos_clinicos.carga_documentos import crear_conexion as crear_conexion_documentos
from documentos_clinicos.carga_documentos import listar_documentos_de_paciente
from historia_clinica.integracion_externa import (
    FORMATO_FHIR,
    FORMATO_HL7V2,
    FuenteFHIR,
    antecedentes_externos_de_paciente,
    cargar_historia_pdf,
    importar_bundle_fhir,
    importar_mensaje_hl7,
    listar_sincronizaciones,
    sincronizar_paciente,
)
from expediente.repository import (
    imagenologia_de_paciente,
    laboratorios_de_paciente,
    obtener_paciente,
)

from .conftest import insertar_paciente

IDENTIFICACION = "EXT-1"


def _bundle(identificacion=IDENTIFICACION):
    # Trae laboratorios: el nombre es obligatorio (doble validación de HC-02).
    paciente = {
        "resourceType": "Patient",
        "id": "p1",
        "identifier": [{"value": identificacion}],
        "name": [{"family": "Prueba", "given": ["Paciente"]}],
    }
    return {
        "resourceType": "Bundle",
        "type": "searchset",
        "entry": [
            {"resource": paciente},
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "lab-1",
                    "category": [{"coding": [{"code": "laboratory"}]}],
                    "code": {"text": "Hemoglobina"},
                    "effectiveDateTime": "2025-11-03T08:00:00Z",
                    "valueQuantity": {"value": 10.2, "unit": "g/dL"},
                    "referenceRange": [{"low": {"value": 12.0}, "high": {"value": 16.0}}],
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "lab-2",
                    "category": [{"coding": [{"code": "laboratory"}]}],
                    "code": {"coding": [{"code": "2160-0", "display": "Creatinina"}]},
                    "effectiveDateTime": "2025-11-03",
                    "valueQuantity": {"value": 0.9, "unit": "mg/dL"},
                    "referenceRange": [{"low": {"value": 0.6}, "high": {"value": 1.2}}],
                }
            },
            {
                "resource": {
                    "resourceType": "DiagnosticReport",
                    "id": "rx-1",
                    "category": [{"coding": [{"code": "RAD"}]}],
                    "code": {"text": "TAC tórax"},
                    "effectiveDateTime": "2025-10-20",
                    "conclusion": "Nódulo pulmonar de 12 mm en lóbulo superior derecho.",
                }
            },
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "c-1",
                    "code": {"text": "Hipertensión arterial"},
                    "onsetDateTime": "2015-06-01",
                }
            },
            {
                "resource": {
                    "resourceType": "MedicationStatement",
                    "id": "m-1",
                    "medicationCodeableConcept": {"text": "Losartán 50 mg"},
                    "effectivePeriod": {"start": "2015-06-10"},
                }
            },
            # Tipo que no se importa: se cuenta como omitido, no rompe nada.
            {"resource": {"resourceType": "Encounter", "id": "e-1"}},
        ],
    }


HL7 = "\r".join(
    [
        "MSH|^~\\&|LIS|HOSP_ORIGEN|COPILOTO|ONCO|20251103080000||ORU^R01|MSG0001|P|2.5",
        f"PID|1||{IDENTIFICACION}^^^HOSP~OTRA-ID^^^REG||Prueba^Paciente||19700101|F",
        "OBR|1|||CBC^Hemograma|||20251103073000",
        "OBX|1|NM|718-7^Hemoglobina||10.2|g/dL|12.0-16.0|L|||F",
        "OBX|2|NM|777-3^Plaquetas||250|10\\S\\3/uL|150-450|N|||F|||20251103074500",
    ]
)


class _Respuesta:
    def __init__(self, status_code, cuerpo):
        self.status_code = status_code
        self._cuerpo = cuerpo

    def json(self):
        return self._cuerpo


class _SesionFHIR:
    """Doble de requests.Session para un servidor FHIR."""

    def __init__(self, bundle, pacientes=1):
        self.bundle = bundle
        self.pacientes = pacientes
        self.urls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.urls.append(url)
        if url.endswith("/Patient"):
            entradas = [{"resource": {"resourceType": "Patient", "id": f"p{i}"}} for i in range(self.pacientes)]
            return _Respuesta(200, {"resourceType": "Bundle", "entry": entradas})
        return _Respuesta(200, self.bundle)


class _FuenteCaida:
    nombre = "HIS externo"
    formato = FORMATO_FHIR

    def obtener_historia(self, identificacion):
        raise ConnectionError("tiempo de espera agotado")


# --- AC1: con integración FHIR/HL7 -> la historia se carga sola ---


def test_sincronizar_desde_fhir_carga_la_historia_en_el_expediente(conn):
    paciente_id = insertar_paciente(conn, identificacion=IDENTIFICACION)
    sesion = _SesionFHIR(_bundle())
    fuente = FuenteFHIR("HIS Hospital Origen", "https://fhir.origen.test/R4", session=sesion)

    resultado = sincronizar_paciente(conn, paciente_id, fuente)

    assert resultado.exito
    assert resultado.registros_importados == 5
    assert resultado.registros_omitidos == 1
    assert sesion.urls[-1] == "https://fhir.origen.test/R4/Patient/p0/$everything"

    labs = {lab.prueba: lab for lab in laboratorios_de_paciente(conn, paciente_id)}
    assert labs["Hemoglobina"].valor == "10.2"
    assert labs["Hemoglobina"].alterado is True
    assert labs["Hemoglobina"].rango_referencia == "12.0-16.0"
    assert labs["Creatinina"].alterado is False
    imagen = imagenologia_de_paciente(conn, paciente_id)[0]
    assert (imagen.modalidad, imagen.region) == ("TAC", "tórax")
    antecedentes = {(a.tipo, a.descripcion) for a in antecedentes_externos_de_paciente(conn, paciente_id)}
    assert antecedentes == {("condicion", "Hipertensión arterial"), ("medicacion", "Losartán 50 mg")}


def test_bundle_fhir_como_texto_json(conn):
    paciente_id = insertar_paciente(conn, identificacion=IDENTIFICACION)

    resultado = importar_bundle_fhir(conn, paciente_id, json.dumps(_bundle()), "HIS")

    assert resultado.exito and resultado.registros_importados == 5


def test_resincronizar_no_duplica_datos(conn):
    paciente_id = insertar_paciente(conn, identificacion=IDENTIFICACION)
    importar_bundle_fhir(conn, paciente_id, _bundle(), "HIS")

    segunda = importar_bundle_fhir(conn, paciente_id, _bundle(), "HIS")

    assert segunda.exito
    assert segunda.registros_importados == 0
    assert len(laboratorios_de_paciente(conn, paciente_id)) == 2


def test_importar_hl7_oru_carga_los_laboratorios(conn):
    paciente_id = insertar_paciente(conn, identificacion=IDENTIFICACION)

    resultado = importar_mensaje_hl7(conn, paciente_id, HL7, "LIS Hospital Origen")

    assert resultado.exito
    assert resultado.registros_importados == 2
    labs = {lab.prueba: lab for lab in laboratorios_de_paciente(conn, paciente_id)}
    assert labs["Hemoglobina"].fecha == "2025-11-03"  # fecha del OBR
    assert labs["Hemoglobina"].alterado is True
    assert labs["Plaquetas"].unidad == "10^3/uL"
    assert labs["Plaquetas"].alterado is False


def test_hl7_acepta_saltos_de_linea_y_es_idempotente(conn):
    paciente_id = insertar_paciente(conn, identificacion=IDENTIFICACION)
    importar_mensaje_hl7(conn, paciente_id, HL7.replace("\r", "\n"), "LIS")

    segunda = importar_mensaje_hl7(conn, paciente_id, HL7, "LIS")

    assert segunda.registros_importados == 0


def test_mensaje_de_otro_paciente_se_rechaza_completo(conn):
    paciente_id = insertar_paciente(conn, identificacion=IDENTIFICACION)

    resultado = importar_bundle_fhir(conn, paciente_id, _bundle(identificacion="OTRA-PERSONA"), "HIS")

    assert not resultado.exito
    assert "otro paciente" in resultado.mensaje
    assert laboratorios_de_paciente(conn, paciente_id) == []


def test_hl7_de_otro_paciente_se_rechaza(conn):
    paciente_id = insertar_paciente(conn, identificacion="NO-COINCIDE")

    resultado = importar_mensaje_hl7(conn, paciente_id, HL7, "LIS")

    assert not resultado.exito
    assert laboratorios_de_paciente(conn, paciente_id) == []


def test_servidor_fhir_con_varios_pacientes_para_la_misma_identificacion_no_importa(conn):
    paciente_id = insertar_paciente(conn, identificacion=IDENTIFICACION)
    fuente = FuenteFHIR("HIS", "https://fhir.test", session=_SesionFHIR(_bundle(), pacientes=2))

    resultado = sincronizar_paciente(conn, paciente_id, fuente)

    assert not resultado.exito
    assert "ambigüedad" in resultado.mensaje


# --- AC2: sin integración -> PDF asociado al paciente ---


def test_pdf_de_historia_queda_asociado_y_consultable(conn, tmp_path):
    paciente_id = insertar_paciente(conn, identificacion=IDENTIFICACION)
    conn_docs = crear_conexion_documentos()

    resultado = cargar_historia_pdf(
        conn, conn_docs, paciente_id, "historia_hospital_origen.pdf",
        b"%PDF-1.4\n contenido no estructurado", "oncologo-7", tmp_path,
    )

    assert resultado.exito
    documentos = listar_documentos_de_paciente(conn_docs, paciente_id)
    assert [d.id for d in documentos] == [resultado.documento_id]
    assert documentos[0].tipo_documento == "PDF"
    assert listar_sincronizaciones(conn, paciente_id)[0].estado == "documento_no_estructurado"


def test_archivo_que_no_es_pdf_no_se_acepta_como_historia(conn, tmp_path):
    paciente_id = insertar_paciente(conn, identificacion=IDENTIFICACION)
    conn_docs = crear_conexion_documentos()

    renombrado = cargar_historia_pdf(conn, conn_docs, paciente_id, "historia.pdf", b"texto plano", "o", tmp_path)
    imagen = cargar_historia_pdf(conn, conn_docs, paciente_id, "foto.png", b"\x89PNG\r\n\x1a\n", "o", tmp_path)

    assert not renombrado.exito and not imagen.exito
    assert listar_documentos_de_paciente(conn_docs, paciente_id) == ()


# --- AC3: fallo de sincronización -> se notifica sin bloquear el expediente ---


def test_fallo_de_la_fuente_se_notifica_sin_bloquear_el_expediente(conn_sembrada):
    conn, ids = conn_sembrada
    paciente_id = ids["paciente_maria"]
    labs_antes = laboratorios_de_paciente(conn, paciente_id)

    resultado = sincronizar_paciente(conn, paciente_id, _FuenteCaida())

    assert not resultado.exito
    assert "tiempo de espera agotado" in resultado.mensaje
    assert "resto del expediente sigue disponible" in resultado.mensaje
    # El expediente sigue accesible e intacto.
    assert obtener_paciente(conn, paciente_id) is not None
    assert laboratorios_de_paciente(conn, paciente_id) == labs_antes
    historial = listar_sincronizaciones(conn, paciente_id)
    assert historial[0].estado == "fallida"
    assert historial[0].mensaje == resultado.mensaje


def test_http_con_error_se_registra_como_fallo(conn):
    paciente_id = insertar_paciente(conn, identificacion=IDENTIFICACION)

    class _Sesion500:
        def get(self, *a, **k):
            return _Respuesta(503, {})

    resultado = sincronizar_paciente(conn, paciente_id, FuenteFHIR("HIS", "https://x", session=_Sesion500()))

    assert not resultado.exito
    assert "HTTP 503" in resultado.mensaje


@pytest.mark.parametrize(
    "contenido",
    [{"resourceType": "Patient"}, "{no es json", {"resourceType": "Bundle", "entry": []}],
)
def test_contenido_fhir_invalido_se_registra_como_fallo(conn, contenido):
    paciente_id = insertar_paciente(conn, identificacion=IDENTIFICACION)

    resultado = importar_bundle_fhir(conn, paciente_id, contenido, "HIS")

    assert not resultado.exito
    assert listar_sincronizaciones(conn, paciente_id)[0].estado == "fallida"


def test_hl7_de_tipo_no_soportado_se_registra_como_fallo(conn):
    paciente_id = insertar_paciente(conn, identificacion=IDENTIFICACION)

    resultado = importar_mensaje_hl7(conn, paciente_id, HL7.replace("ORU^R01", "ADT^A01"), "LIS")

    assert not resultado.exito
    assert "ORU^R01" in resultado.mensaje


def test_error_a_mitad_de_importacion_no_deja_datos_a_medias(conn, monkeypatch):
    import historia_clinica.integracion_externa as modulo

    paciente_id = insertar_paciente(conn, identificacion=IDENTIFICACION)
    original = modulo._insertar_registro
    llamadas = {"n": 0}

    def _falla_en_la_tercera(*args):
        llamadas["n"] += 1
        if llamadas["n"] == 3:
            raise RuntimeError("disco lleno")
        return original(*args)

    monkeypatch.setattr(modulo, "_insertar_registro", _falla_en_la_tercera)

    resultado = importar_bundle_fhir(conn, paciente_id, _bundle(), "HIS")

    assert not resultado.exito
    assert laboratorios_de_paciente(conn, paciente_id) == []
    assert [s.estado for s in listar_sincronizaciones(conn, paciente_id)] == ["fallida"]


def test_formato_hl7_declarado_por_la_fuente(conn):
    paciente_id = insertar_paciente(conn, identificacion=IDENTIFICACION)

    class _FuenteHL7:
        nombre = "LIS"
        formato = FORMATO_HL7V2

        def obtener_historia(self, identificacion):
            return HL7

    assert sincronizar_paciente(conn, paciente_id, _FuenteHL7()).registros_importados == 2
