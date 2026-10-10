"""HC-03 — Integración de imágenes diagnósticas (DICOM/PACS).

Agrupadas por criterio de aceptación:

    AC1: el paciente tiene un estudio en el PACS -> al abrir su expediente se
         ve el estudio o su informe.
    AC2: no hay conexión con el PACS -> el sistema avisa que la integración
         no está disponible, sin fallar en silencio.
"""

import pytest

from expediente.repository import imagenologia_de_paciente
from historia_clinica import imagenes_pacs as pacs
from historia_clinica.imagenes_pacs import (
    ErrorConfiguracionVisor,
    ErrorPACS,
    EstudioDICOM,
    FuenteDICOMweb,
    abrir_visor,
    construir_url_visor,
    estudio_desde_dicom_json,
    estudios_del_expediente,
    historial_consultas,
    listar_estudios,
    sincronizar_estudios,
    validar_plantilla_visor,
)
from tests.historia_clinica.conftest import insertar_imagen, insertar_paciente

UID_1 = "1.2.840.113619.2.55.3.604688119.969.1268071829.6"
UID_2 = "1.2.840.113619.2.55.3.604688119.969.1268071829.7"
VISOR = "https://visor.hospital.example/viewer?StudyInstanceUIDs={study_uid}"
NOMBRE = "María Fernanda Ríos"


# --------------------------------------------------------------------------
# Dobles de prueba
# --------------------------------------------------------------------------


def _dicom(uid=UID_1, patient_id="SINT-0001", nombre="Ríos^María Fernanda", fecha="20260114", modalidad=("US",)):
    dataset = {
        "0020000D": {"vr": "UI", "Value": [uid]},
        "00100020": {"vr": "LO", "Value": [patient_id]},
        "00080020": {"vr": "DA", "Value": [fecha]},
        "00081030": {"vr": "LO", "Value": ["Ecografía mamaria"]},
        "00201206": {"vr": "IS", "Value": [3]},
        "00201208": {"vr": "IS", "Value": [120]},
    }
    if nombre is not None:
        dataset["00100010"] = {"vr": "PN", "Value": [{"Alphabetic": nombre}]}
    if modalidad:
        dataset["00080061"] = {"vr": "CS", "Value": list(modalidad)}
    return dataset


class _Respuesta:
    def __init__(self, status=200, datos=None, json_invalido=False):
        self.status_code = status
        self._datos = datos
        self._json_invalido = json_invalido

    def json(self):
        if self._json_invalido:
            raise ValueError("no es json")
        return self._datos


class _Sesion:
    """Doble de ``requests.Session``: devuelve una respuesta o lanza."""

    def __init__(self, respuesta=None, error=None):
        self.respuesta = respuesta
        self.error = error
        self.llamadas = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.llamadas.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        if self.error:
            raise self.error
        return self.respuesta


class _FuenteFalsa:
    """Fuente que cumple el Protocol ``FuentePACS`` sin HTTP."""

    def __init__(self, estudios=None, error=None, nombre="PACS-Prueba"):
        self.nombre = nombre
        self._estudios = estudios or []
        self._error = error

    def buscar_estudios(self, identificacion):
        if self._error:
            raise self._error
        return list(self._estudios)


def _estudio(uid=UID_1, patient_id="SINT-0001", nombre="Ríos^María Fernanda", fecha="2026-01-14", modalidad="US"):
    return EstudioDICOM(
        study_uid=uid, patient_id=patient_id, patient_name=nombre, fecha=fecha, modalidad=modalidad,
        descripcion="Ecografía mamaria", series=3, instancias=120,
    )


@pytest.fixture
def paciente(conn_sembrada):
    conn, ids = conn_sembrada
    return conn, ids["paciente_maria"], ids  # SINT-0001 con una ecografía del 2026-01-14


# --------------------------------------------------------------------------
# AC1 — se ve el estudio o su informe
# --------------------------------------------------------------------------


class TestAC1EstudioDisponible:
    def test_el_expediente_muestra_el_estudio_con_su_informe_y_el_enlace_al_visor(self, paciente):
        conn, paciente_id, ids = paciente
        fuente = _FuenteFalsa([_estudio()])
        vista = estudios_del_expediente(conn, paciente_id, fuente, plantilla_visor=VISOR)

        assert vista.integracion_disponible is True
        assert vista.desde_indice_local is False
        assert vista.mensaje == ""
        (estudio,) = vista.estudios
        assert estudio.study_uid == UID_1
        assert estudio.modalidad == "US"
        assert estudio.series == 3 and estudio.instancias == 120
        assert estudio.visor_url == VISOR.replace("{study_uid}", UID_1)
        # El informe es el que ya estaba en el expediente (misma fecha y modalidad).
        assert estudio.informe is not None
        assert estudio.informe.imagenologia_id == ids["imagen_maria_1"]
        assert "reducción del tamaño tumoral" in estudio.informe.texto
        assert vista.informes_sin_estudio == []

    def test_abrir_el_visor_devuelve_la_url_del_estudio_y_su_informe(self, paciente):
        conn, paciente_id, _ = paciente
        resultado = abrir_visor(conn, paciente_id, UID_1, _FuenteFalsa([_estudio()]), plantilla_visor=VISOR)
        assert resultado.disponible is True
        assert resultado.url == VISOR.replace("{study_uid}", UID_1)
        assert resultado.informe is not None

    def test_estudio_sin_informe_asociado_se_lista_igual(self, paciente):
        conn, paciente_id, _ = paciente
        # Tomografía el 2026-02-01: el expediente no tiene informe de ese día.
        fuente = _FuenteFalsa([_estudio(uid=UID_2, fecha="2026-02-01", modalidad="CT")])
        vista = estudios_del_expediente(conn, paciente_id, fuente)
        (estudio,) = vista.estudios
        assert estudio.informe is None
        assert estudio.visor_url is None  # sin visor configurado no hay enlace, pero sí estudio

    def test_el_informe_del_expediente_sin_estudio_en_pacs_sigue_visible(self, paciente):
        conn, paciente_id, ids = paciente
        vista = estudios_del_expediente(conn, paciente_id, _FuenteFalsa([]))
        assert vista.integracion_disponible is True
        assert vista.estudios == []
        assert [i.imagenologia_id for i in vista.informes_sin_estudio] == [ids["imagen_maria_1"]]

    def test_paciente_sin_estudios_en_el_pacs_no_es_un_error(self, paciente):
        conn, paciente_id, _ = paciente
        resultado = sincronizar_estudios(conn, paciente_id, _FuenteFalsa([]))
        assert resultado.exito is True and resultado.estudios_indexados == 0

    def test_resincronizar_no_duplica_estudios(self, paciente):
        conn, paciente_id, _ = paciente
        fuente = _FuenteFalsa([_estudio()])
        sincronizar_estudios(conn, paciente_id, fuente)
        sincronizar_estudios(conn, paciente_id, fuente)
        assert len(listar_estudios(conn, paciente_id)) == 1

    def test_estudios_ordenados_del_mas_reciente_al_mas_antiguo(self, paciente):
        conn, paciente_id, _ = paciente
        fuente = _FuenteFalsa([
            _estudio(uid=UID_1, fecha="2026-01-14"),
            _estudio(uid=UID_2, fecha="2026-03-01", modalidad="CT"),
        ])
        sincronizar_estudios(conn, paciente_id, fuente)
        assert [e.study_uid for e in listar_estudios(conn, paciente_id)] == [UID_2, UID_1]


class TestFuenteDICOMweb:
    def test_consulta_qido_por_patient_id_y_traduce_dicom_json(self):
        sesion = _Sesion(_Respuesta(200, [_dicom()]))
        fuente = FuenteDICOMweb("Orthanc", "https://pacs.example/dicom-web/", session=sesion, token="abc")
        (estudio,) = fuente.buscar_estudios("SINT-0001")

        llamada = sesion.llamadas[0]
        assert llamada["url"] == "https://pacs.example/dicom-web/studies"
        assert llamada["params"]["PatientID"] == "SINT-0001"
        assert llamada["headers"]["Accept"] == "application/dicom+json"
        assert llamada["headers"]["Authorization"] == "Bearer abc"
        assert estudio.study_uid == UID_1
        assert estudio.fecha == "2026-01-14"  # 20260114 -> ISO
        assert estudio.modalidad == "US"
        assert estudio.patient_name == "Ríos^María Fernanda"
        assert (estudio.series, estudio.instancias) == (3, 120)

    def test_autenticacion_basica_para_pacs_con_usuario_y_contrasena(self):
        sesion = _Sesion(_Respuesta(200, []))
        FuenteDICOMweb("Orthanc", "https://p.example", session=sesion, usuario="orthanc", password="clave").buscar_estudios("X")
        # base64("orthanc:clave")
        assert sesion.llamadas[0]["headers"]["Authorization"] == "Basic b3J0aGFuYzpjbGF2ZQ=="

    def test_el_token_tiene_prioridad_sobre_usuario_y_contrasena(self):
        sesion = _Sesion(_Respuesta(200, []))
        FuenteDICOMweb("O", "https://p.example", session=sesion, token="t", usuario="u", password="p").buscar_estudios("X")
        assert sesion.llamadas[0]["headers"]["Authorization"] == "Bearer t"

    def test_204_significa_sin_estudios(self):
        fuente = FuenteDICOMweb("Orthanc", "https://pacs.example", session=_Sesion(_Respuesta(204)))
        assert fuente.buscar_estudios("SINT-0001") == []

    def test_varias_modalidades_se_unen(self):
        estudio = estudio_desde_dicom_json(_dicom(modalidad=("PT", "CT")))
        assert estudio.modalidad == "PT/CT"

    def test_estudio_sin_uid_valido_se_rechaza(self):
        with pytest.raises(ErrorPACS):
            estudio_desde_dicom_json(_dicom(uid="no-es-un-uid"))
        with pytest.raises(ErrorPACS):
            estudio_desde_dicom_json(_dicom(uid="1." + "2" * 70))

    def test_estudio_sin_patient_id_se_rechaza(self):
        dataset = _dicom()
        del dataset["00100020"]
        with pytest.raises(ErrorPACS, match="PatientID"):
            estudio_desde_dicom_json(dataset)

    def test_fuente_desde_entorno(self, monkeypatch):
        monkeypatch.delenv(pacs.ENV_PACS_URL, raising=False)
        assert pacs.fuente_desde_entorno() is None
        monkeypatch.setenv(pacs.ENV_PACS_URL, "https://pacs.example/dicom-web")
        monkeypatch.setenv(pacs.ENV_PACS_NOMBRE, "PACS Central")
        monkeypatch.setenv(pacs.ENV_PACS_USUARIO, "orthanc")
        monkeypatch.setenv(pacs.ENV_PACS_PASSWORD, "clave")
        fuente = pacs.fuente_desde_entorno(session=_Sesion())
        assert fuente.nombre == "PACS Central"
        assert (fuente.usuario, fuente.password) == ("orthanc", "clave")


class TestVincularInforme:
    def test_dos_informes_candidatos_no_se_adivinan(self, paciente):
        conn, paciente_id, _ = paciente
        # Segunda ecografía el mismo día: el enlace sería ambiguo.
        conn.execute(
            "INSERT INTO imagenologia (paciente_id, fecha, modalidad, region, hallazgos) VALUES (?, ?, ?, ?, ?)",
            (paciente_id, "2026-01-14", "Ecografía", "axila izquierda", "Sin adenopatías."),
        )
        conn.commit()
        sincronizar_estudios(conn, paciente_id, _FuenteFalsa([_estudio()]))
        (estudio,) = listar_estudios(conn, paciente_id)
        assert estudio.informe is None
        assert len(estudios_del_expediente(conn, paciente_id, _FuenteFalsa([_estudio()])).informes_sin_estudio) == 2

    def test_misma_fecha_pero_otra_modalidad_no_se_enlaza(self, paciente):
        conn, paciente_id, _ = paciente
        sincronizar_estudios(conn, paciente_id, _FuenteFalsa([_estudio(modalidad="CT")]))
        (estudio,) = listar_estudios(conn, paciente_id)
        assert estudio.informe is None

    def test_nombres_de_modalidad_en_espanol_y_siglas(self, paciente):
        conn, paciente_id, _ = paciente
        conn.execute(
            "INSERT INTO imagenologia (paciente_id, fecha, modalidad, region, hallazgos) VALUES (?, ?, ?, ?, ?)",
            (paciente_id, "2026-02-01", "TC de tórax con contraste", "tórax", "Nódulo de 8 mm."),
        )
        conn.commit()
        sincronizar_estudios(conn, paciente_id, _FuenteFalsa([_estudio(uid=UID_2, fecha="2026-02-01", modalidad="CT")]))
        (estudio,) = listar_estudios(conn, paciente_id, pacs="PACS-Prueba")[:1]
        assert estudio.informe is not None and "Nódulo" in estudio.informe.texto


class TestIdentidad:
    def test_estudio_de_otro_paciente_se_rechaza_y_no_se_muestra(self, paciente):
        conn, paciente_id, _ = paciente
        fuente = _FuenteFalsa([
            _estudio(uid=UID_1),
            _estudio(uid=UID_2, patient_id="OTRO-999", nombre="Pérez^Juan Carlos"),
        ])
        resultado = sincronizar_estudios(conn, paciente_id, fuente)
        assert resultado.exito is True
        assert (resultado.estudios_indexados, resultado.estudios_rechazados) == (1, 1)
        assert "no coincide" in resultado.mensaje
        assert [e.study_uid for e in listar_estudios(conn, paciente_id)] == [UID_1]

    def test_misma_identificacion_con_nombre_distinto_se_rechaza(self, paciente):
        conn, paciente_id, _ = paciente
        resultado = sincronizar_estudios(
            conn, paciente_id, _FuenteFalsa([_estudio(nombre="Gómez^Pedro Luis")])
        )
        assert resultado.estudios_indexados == 0 and resultado.estudios_rechazados == 1

    def test_estudio_sin_nombre_se_acepta_por_identificacion(self, paciente):
        conn, paciente_id, _ = paciente
        resultado = sincronizar_estudios(conn, paciente_id, _FuenteFalsa([_estudio(nombre=None)]))
        assert resultado.estudios_indexados == 1

    def test_un_estudio_no_se_reasigna_a_otro_paciente(self, conn_sembrada):
        """Si el índice ya tiene ese UID para otro paciente, no se pisa."""
        conn, ids = conn_sembrada
        otro = insertar_paciente(conn, identificacion="EXT-2", nombre="Juan Carlos Pérez (sintético)")
        sincronizar_estudios(conn, otro, _FuenteFalsa([_estudio(patient_id="EXT-2", nombre="Pérez^Juan Carlos")]))
        sincronizar_estudios(conn, ids["paciente_maria"], _FuenteFalsa([_estudio()]))  # mismo UID, otro paciente
        assert [e.paciente_id for e in listar_estudios(conn, otro)] == [otro]
        assert listar_estudios(conn, ids["paciente_maria"]) == []

    def test_paciente_inexistente(self, conn):
        with pytest.raises(ValueError):
            sincronizar_estudios(conn, 999, _FuenteFalsa([]))


# --------------------------------------------------------------------------
# AC2 — sin conexión: se informa, no se falla en silencio
# --------------------------------------------------------------------------


class TestAC2SinConexionConElPACS:
    @pytest.mark.parametrize(
        "error",
        [ConnectionError("conexión rechazada"), TimeoutError("tiempo de espera agotado"), RuntimeError()],
    )
    def test_el_visor_avisa_que_la_integracion_no_esta_disponible(self, paciente, error):
        conn, paciente_id, _ = paciente
        resultado = abrir_visor(conn, paciente_id, UID_1, _FuenteFalsa(error=error), plantilla_visor=VISOR)
        assert resultado.disponible is False
        assert resultado.url is None
        assert "integración con el PACS no está disponible" in resultado.mensaje
        assert "PACS-Prueba" in resultado.mensaje

    def test_el_fallo_queda_registrado_en_la_bitacora(self, paciente):
        conn, paciente_id, _ = paciente
        abrir_visor(conn, paciente_id, UID_1, _FuenteFalsa(error=ConnectionError("caído")), plantilla_visor=VISOR)
        (consulta,) = historial_consultas(conn, paciente_id)
        assert consulta["estado"] == "fallida"
        assert "caído" in consulta["mensaje"]

    def test_expediente_sin_conexion_avisa_y_conserva_lo_ultimo_sincronizado(self, paciente):
        conn, paciente_id, _ = paciente
        sincronizar_estudios(conn, paciente_id, _FuenteFalsa([_estudio()]))
        vista = estudios_del_expediente(
            conn, paciente_id, _FuenteFalsa(error=ConnectionError("sin red")), plantilla_visor=VISOR
        )
        assert vista.integracion_disponible is False
        assert vista.desde_indice_local is True
        assert "no está disponible" in vista.mensaje and "sin red" in vista.mensaje
        assert [e.study_uid for e in vista.estudios] == [UID_1]  # último índice, marcado como tal

    def test_sin_pacs_configurado_tambien_se_informa(self, paciente):
        conn, paciente_id, ids = paciente
        vista = estudios_del_expediente(conn, paciente_id, None)
        assert vista.integracion_disponible is False
        assert "no hay un PACS configurado" in vista.mensaje
        # Los informes del expediente siguen siendo accesibles.
        assert [i.imagenologia_id for i in vista.informes_sin_estudio] == [ids["imagen_maria_1"]]
        resultado = abrir_visor(conn, paciente_id, UID_1, None, plantilla_visor=VISOR)
        assert resultado.disponible is False and "no hay un PACS configurado" in resultado.mensaje

    def test_visor_no_disponible_devuelve_el_informe_para_leerlo_igual(self, paciente):
        conn, paciente_id, _ = paciente
        sincronizar_estudios(conn, paciente_id, _FuenteFalsa([_estudio()]))
        resultado = abrir_visor(conn, paciente_id, UID_1, _FuenteFalsa(error=TimeoutError("lento")), plantilla_visor=VISOR)
        assert resultado.disponible is False
        assert resultado.informe is not None
        assert "informe asociado sí está disponible" in resultado.mensaje

    @pytest.mark.parametrize(
        "sesion, causa",
        [
            (_Sesion(error=ConnectionError("DNS")), "DNS"),
            (_Sesion(_Respuesta(503)), "HTTP 503"),
            (_Sesion(_Respuesta(200, json_invalido=True)), "no es JSON"),
            (_Sesion(_Respuesta(200, {"error": "x"})), "formato inesperado"),
        ],
    )
    def test_fallos_http_de_dicomweb_se_explican(self, paciente, sesion, causa):
        conn, paciente_id, _ = paciente
        fuente = FuenteDICOMweb("Orthanc", "https://pacs.example", session=sesion)
        resultado = sincronizar_estudios(conn, paciente_id, fuente)
        assert resultado.exito is False
        assert causa in resultado.mensaje

    def test_un_estudio_malformado_hace_fallar_la_consulta_completa_con_mensaje(self, paciente):
        conn, paciente_id, _ = paciente
        sesion = _Sesion(_Respuesta(200, [_dicom(), _dicom(uid="x")]))
        resultado = sincronizar_estudios(conn, paciente_id, FuenteDICOMweb("O", "https://p.example", session=sesion))
        assert resultado.exito is False
        assert listar_estudios(conn, paciente_id) == []  # nada a medias

    def test_estudio_que_ya_no_esta_en_el_pacs(self, paciente):
        conn, paciente_id, _ = paciente
        resultado = abrir_visor(conn, paciente_id, UID_2, _FuenteFalsa([_estudio()]), plantilla_visor=VISOR)
        assert resultado.disponible is False
        assert "no figura en el PACS" in resultado.mensaje

    def test_sin_visor_configurado_se_dice_explicitamente(self, paciente):
        conn, paciente_id, _ = paciente
        resultado = abrir_visor(conn, paciente_id, UID_1, _FuenteFalsa([_estudio()]))
        assert resultado.disponible is False
        assert "No hay un visor" in resultado.mensaje

    def test_uid_invalido_no_llega_al_visor(self, paciente):
        conn, paciente_id, _ = paciente
        resultado = abrir_visor(conn, paciente_id, "1.2.3&evil=1", _FuenteFalsa([_estudio()]), plantilla_visor=VISOR)
        assert resultado.disponible is False and resultado.url is None

    def test_el_fallo_del_pacs_no_toca_el_resto_del_expediente(self, paciente):
        conn, paciente_id, _ = paciente
        antes = [i.id for i in imagenologia_de_paciente(conn, paciente_id)]
        sincronizar_estudios(conn, paciente_id, _FuenteFalsa(error=ConnectionError("caído")))
        assert [i.id for i in imagenologia_de_paciente(conn, paciente_id)] == antes

    def test_bitacora_de_solo_insercion(self):
        publicas = {n for n in dir(pacs) if not n.startswith("_")}
        assert not any(n.startswith(("borrar", "eliminar", "actualizar_consulta")) for n in publicas)


# --------------------------------------------------------------------------
# Visor incrustable (decisión de diseño: no construir uno propio)
# --------------------------------------------------------------------------


class TestPlantillaDelVisor:
    def test_sin_plantilla_no_hay_visor(self):
        assert validar_plantilla_visor(None) is None
        assert validar_plantilla_visor("  ") is None
        assert construir_url_visor(None, UID_1) is None

    def test_la_plantilla_debe_tener_el_marcador(self):
        with pytest.raises(ErrorConfiguracionVisor, match="study_uid"):
            validar_plantilla_visor("https://visor.example/viewer")

    @pytest.mark.parametrize("plantilla", ["javascript:alert({study_uid})", "ftp://x/{study_uid}", "file:///{study_uid}"])
    def test_solo_http_y_https(self, plantilla):
        with pytest.raises(ErrorConfiguracionVisor):
            validar_plantilla_visor(plantilla)

    def test_el_uid_se_escapa_en_la_url(self):
        assert construir_url_visor(VISOR, UID_1).endswith("StudyInstanceUIDs=" + UID_1)
        with pytest.raises(ErrorPACS):
            construir_url_visor(VISOR, "1.2/../x")

    def test_visor_mal_configurado_se_informa_al_abrir(self, paciente):
        conn, paciente_id, _ = paciente
        resultado = abrir_visor(conn, paciente_id, UID_1, _FuenteFalsa([_estudio()]), plantilla_visor="javascript:{study_uid}")
        assert resultado.disponible is False
        assert "mal configurado" in resultado.mensaje
