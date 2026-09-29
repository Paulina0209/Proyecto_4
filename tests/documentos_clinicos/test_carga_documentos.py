"""Pruebas de aceptación de DOC-01 — Carga de documentos clínicos.

Criterios de aceptación de la historia:

    AC1 — Dado un documento clínico en un formato soportado, cuando lo
    cargo al expediente de un paciente, entonces queda correctamente
    asociado al paciente y visible en su historial de documentos.

    AC2 — Dado un formato de archivo no soportado, cuando intento
    cargarlo, entonces el sistema rechaza el archivo y muestra un
    mensaje claro que indica el formato esperado.

Una tercera clase cubre el comportamiento defensivo adicional de esta
implementación (no explícito en el AC, pero coherente con el resto del
proyecto): un archivo cuya extensión es soportada pero cuyo contenido
real no corresponde a ese formato también se rechaza, en vez de
aceptarse solo porque el nombre "dice" ser de un formato válido.
"""

import pytest

from expediente.adapters import PacienteNoEncontradoError

from documentos_clinicos.carga_documentos import (
    ContenidoNoCoincideConFormatoError,
    DocumentoInvalidoError,
    FormatoNoSoportadoError,
    cargar_documento_clinico,
    leer_contenido_documento,
    listar_documentos_de_paciente,
    obtener_documento_por_id,
)

_PDF_VALIDO = b"%PDF-1.4\n%contenido sintetico\n%%EOF"
_JPEG_VALIDO = b"\xff\xd8\xff\xe0" + b"\x00" * 16
_PNG_VALIDO = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
_DICOM_VALIDO = (b"\x00" * 128) + b"DICM" + b"\x00" * 8


# ---------------------------------------------------------------------------
# AC1 — formato soportado -> asociado al paciente y visible en su historial.
# ---------------------------------------------------------------------------
class TestCargaDocumentoEnFormatoSoportado:
    def test_pdf_queda_asociado_al_paciente_y_visible_en_su_historial(self, conn_documentos, conn_sembrada):
        conn, ids = conn_sembrada

        documento = cargar_documento_clinico(
            conn=conn_documentos,
            conn_historia=conn,
            paciente_id=ids["paciente_maria"],
            nombre_archivo="biopsia.pdf",
            contenido=_PDF_VALIDO,
            cargado_por="dra.rodriguez",
            directorio_almacenamiento=self._directorio(),
        )

        assert documento.paciente_id == ids["paciente_maria"]
        assert documento.tipo_documento == "PDF"
        historial = listar_documentos_de_paciente(conn_documentos, ids["paciente_maria"])
        assert documento.id in [d.id for d in historial]

    @pytest.mark.parametrize(
        "nombre_archivo,contenido,tipo_esperado",
        [
            ("radiografia.jpg", _JPEG_VALIDO, "Imagen"),
            ("radiografia.jpeg", _JPEG_VALIDO, "Imagen"),
            ("mamografia.png", _PNG_VALIDO, "Imagen"),
            ("resonancia.dcm", _DICOM_VALIDO, "DICOM"),
        ],
    )
    def test_cada_formato_soportado_se_carga_con_su_tipo_correcto(
        self, conn_documentos, conn_sembrada, nombre_archivo, contenido, tipo_esperado
    ):
        conn, ids = conn_sembrada

        documento = cargar_documento_clinico(
            conn=conn_documentos,
            conn_historia=conn,
            paciente_id=ids["paciente_maria"],
            nombre_archivo=nombre_archivo,
            contenido=contenido,
            cargado_por="dr.gomez",
            directorio_almacenamiento=self._directorio(),
        )

        assert documento.tipo_documento == tipo_esperado

    def test_el_contenido_guardado_en_disco_es_identico_al_original(self, conn_documentos, conn_sembrada):
        conn, ids = conn_sembrada

        documento = cargar_documento_clinico(
            conn=conn_documentos,
            conn_historia=conn,
            paciente_id=ids["paciente_maria"],
            nombre_archivo="biopsia.pdf",
            contenido=_PDF_VALIDO,
            cargado_por="dra.rodriguez",
            directorio_almacenamiento=self._directorio(),
        )

        assert leer_contenido_documento(documento) == _PDF_VALIDO

    def test_varios_documentos_del_mismo_paciente_quedan_todos_en_el_historial(self, conn_documentos, conn_sembrada):
        conn, ids = conn_sembrada
        for nombre, contenido in [("a.pdf", _PDF_VALIDO), ("b.jpg", _JPEG_VALIDO), ("c.dcm", _DICOM_VALIDO)]:
            cargar_documento_clinico(
                conn=conn_documentos,
                conn_historia=conn,
                paciente_id=ids["paciente_maria"],
                nombre_archivo=nombre,
                contenido=contenido,
                cargado_por="dra.rodriguez",
                directorio_almacenamiento=self._directorio(),
            )

        historial = listar_documentos_de_paciente(conn_documentos, ids["paciente_maria"])

        assert len(historial) == 3
        assert {d.nombre_archivo_original for d in historial} == {"a.pdf", "b.jpg", "c.dcm"}

    def test_documentos_de_pacientes_distintos_no_se_mezclan(self, conn_documentos, conn_sembrada):
        conn, ids = conn_sembrada
        cargar_documento_clinico(
            conn=conn_documentos,
            conn_historia=conn,
            paciente_id=ids["paciente_maria"],
            nombre_archivo="de_maria.pdf",
            contenido=_PDF_VALIDO,
            cargado_por="dra.rodriguez",
            directorio_almacenamiento=self._directorio(),
        )
        cargar_documento_clinico(
            conn=conn_documentos,
            conn_historia=conn,
            paciente_id=ids["paciente_carlos"],
            nombre_archivo="de_carlos.pdf",
            contenido=_PDF_VALIDO,
            cargado_por="dra.rodriguez",
            directorio_almacenamiento=self._directorio(),
        )

        historial_maria = listar_documentos_de_paciente(conn_documentos, ids["paciente_maria"])
        historial_carlos = listar_documentos_de_paciente(conn_documentos, ids["paciente_carlos"])

        assert [d.nombre_archivo_original for d in historial_maria] == ["de_maria.pdf"]
        assert [d.nombre_archivo_original for d in historial_carlos] == ["de_carlos.pdf"]

    def test_paciente_inexistente_no_permite_cargar_un_documento(self, conn_documentos, conn_sembrada):
        conn, _ids = conn_sembrada

        with pytest.raises(PacienteNoEncontradoError):
            cargar_documento_clinico(
                conn=conn_documentos,
                conn_historia=conn,
                paciente_id=99999,
                nombre_archivo="biopsia.pdf",
                contenido=_PDF_VALIDO,
                cargado_por="dra.rodriguez",
                directorio_almacenamiento=self._directorio(),
            )

    @staticmethod
    def _directorio():
        import tempfile

        return tempfile.mkdtemp()


# ---------------------------------------------------------------------------
# AC2 — formato no soportado -> rechazado con mensaje claro sobre el
# formato esperado.
# ---------------------------------------------------------------------------
class TestRechazaFormatoNoSoportado:
    def test_extension_no_reconocida_se_rechaza(self, conn_documentos, conn_sembrada, tmp_path):
        conn, ids = conn_sembrada

        with pytest.raises(FormatoNoSoportadoError):
            cargar_documento_clinico(
                conn=conn_documentos,
                conn_historia=conn,
                paciente_id=ids["paciente_maria"],
                nombre_archivo="notas.txt",
                contenido=b"texto plano",
                cargado_por="dra.rodriguez",
                directorio_almacenamiento=str(tmp_path),
            )

    def test_mensaje_de_rechazo_indica_los_formatos_esperados(self, conn_documentos, conn_sembrada, tmp_path):
        conn, ids = conn_sembrada

        with pytest.raises(FormatoNoSoportadoError) as excinfo:
            cargar_documento_clinico(
                conn=conn_documentos,
                conn_historia=conn,
                paciente_id=ids["paciente_maria"],
                nombre_archivo="notas.docx",
                contenido=b"contenido irrelevante",
                cargado_por="dra.rodriguez",
                directorio_almacenamiento=str(tmp_path),
            )

        mensaje = str(excinfo.value)
        assert "PDF" in mensaje
        assert "Imagen" in mensaje
        assert "DICOM" in mensaje

    def test_archivo_sin_extension_tambien_se_rechaza(self, conn_documentos, conn_sembrada, tmp_path):
        conn, ids = conn_sembrada

        with pytest.raises(FormatoNoSoportadoError):
            cargar_documento_clinico(
                conn=conn_documentos,
                conn_historia=conn,
                paciente_id=ids["paciente_maria"],
                nombre_archivo="archivo_sin_extension",
                contenido=_PDF_VALIDO,
                cargado_por="dra.rodriguez",
                directorio_almacenamiento=str(tmp_path),
            )

    def test_documento_rechazado_no_queda_en_el_historial(self, conn_documentos, conn_sembrada, tmp_path):
        conn, ids = conn_sembrada

        try:
            cargar_documento_clinico(
                conn=conn_documentos,
                conn_historia=conn,
                paciente_id=ids["paciente_maria"],
                nombre_archivo="notas.txt",
                contenido=b"texto plano",
                cargado_por="dra.rodriguez",
                directorio_almacenamiento=str(tmp_path),
            )
        except FormatoNoSoportadoError:
            pass

        assert listar_documentos_de_paciente(conn_documentos, ids["paciente_maria"]) == ()


# ---------------------------------------------------------------------------
# Comportamiento defensivo adicional: la extensión no es la única señal --
# el contenido real debe corresponder al formato que dice ser.
# ---------------------------------------------------------------------------
class TestRechazaContenidoQueNoCoincideConElFormatoDeclarado:
    def test_pdf_con_contenido_de_texto_plano_se_rechaza(self, conn_documentos, conn_sembrada, tmp_path):
        conn, ids = conn_sembrada

        with pytest.raises(ContenidoNoCoincideConFormatoError):
            cargar_documento_clinico(
                conn=conn_documentos,
                conn_historia=conn,
                paciente_id=ids["paciente_maria"],
                nombre_archivo="informe_falso.pdf",
                contenido=b"esto no es un pdf real",
                cargado_por="dra.rodriguez",
                directorio_almacenamiento=str(tmp_path),
            )

    def test_imagen_con_contenido_que_no_es_jpeg_ni_png_se_rechaza(self, conn_documentos, conn_sembrada, tmp_path):
        conn, ids = conn_sembrada

        with pytest.raises(ContenidoNoCoincideConFormatoError):
            cargar_documento_clinico(
                conn=conn_documentos,
                conn_historia=conn,
                paciente_id=ids["paciente_maria"],
                nombre_archivo="radiografia.jpg",
                contenido=b"esto no es una imagen real",
                cargado_por="dra.rodriguez",
                directorio_almacenamiento=str(tmp_path),
            )

    def test_dicom_sin_el_preambulo_real_se_rechaza(self, conn_documentos, conn_sembrada, tmp_path):
        conn, ids = conn_sembrada

        with pytest.raises(ContenidoNoCoincideConFormatoError):
            cargar_documento_clinico(
                conn=conn_documentos,
                conn_historia=conn,
                paciente_id=ids["paciente_maria"],
                nombre_archivo="resonancia.dcm",
                contenido=b"DICM" + b"\x00" * 8,  # sin el preambulo de 128 bytes
                cargado_por="dra.rodriguez",
                directorio_almacenamiento=str(tmp_path),
            )


# ---------------------------------------------------------------------------
# Validaciones básicas de forma, heredadas del resto del proyecto (autor
# explícito, contenido no vacío) — no negociables aunque no estén en el AC.
# ---------------------------------------------------------------------------
class TestValidacionesBasicasDeForma:
    def test_contenido_vacio_se_rechaza(self, conn_documentos, conn_sembrada, tmp_path):
        conn, ids = conn_sembrada

        with pytest.raises(DocumentoInvalidoError):
            cargar_documento_clinico(
                conn=conn_documentos,
                conn_historia=conn,
                paciente_id=ids["paciente_maria"],
                nombre_archivo="vacio.pdf",
                contenido=b"",
                cargado_por="dra.rodriguez",
                directorio_almacenamiento=str(tmp_path),
            )

    def test_autor_vacio_se_rechaza(self, conn_documentos, conn_sembrada, tmp_path):
        conn, ids = conn_sembrada

        with pytest.raises(DocumentoInvalidoError):
            cargar_documento_clinico(
                conn=conn_documentos,
                conn_historia=conn,
                paciente_id=ids["paciente_maria"],
                nombre_archivo="biopsia.pdf",
                contenido=_PDF_VALIDO,
                cargado_por="   ",
                directorio_almacenamiento=str(tmp_path),
            )

    def test_obtener_documento_por_id_inexistente_lanza_key_error(self, conn_documentos):
        with pytest.raises(KeyError):
            obtener_documento_por_id(conn_documentos, 99999)

    def test_paciente_sin_documentos_tiene_historial_vacio(self, conn_documentos, conn_sembrada):
        conn, ids = conn_sembrada

        assert listar_documentos_de_paciente(conn_documentos, ids["paciente_carlos"]) == ()
