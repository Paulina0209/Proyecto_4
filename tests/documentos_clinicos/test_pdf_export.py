"""Pruebas de aceptación de DOC-02 — Exportación de documentos clínicos a PDF.

Criterio de aceptación de la historia (único, tal como se recibió):

    Dado un expediente/resumen con información suficiente, cuando solicito
    exportar el resumen, entonces recibo un PDF con formato profesional
    listo para compartir.

``TestExportaUnPDFListoParaCompartir`` cubre ese criterio directamente
sobre el renderizador genérico (independiente de qué produjo el
contenido — eso lo cubre ``test_adaptadores.py``). Las clases adicionales
cubren el comportamiento defensivo ya establecido en el resto del
proyecto: nunca se produce un documento "profesional" a partir de
información insuficiente.
"""

import os

import pytest

from documentos_clinicos.pdf_export import (
    BloqueTabla,
    BloqueTexto,
    DocumentoExportable,
    DocumentoInsuficienteError,
    SeccionDocumento,
    exportar_a_pdf,
)


def _es_pdf_valido(ruta: str) -> bool:
    with open(ruta, "rb") as f:
        contenido = f.read()
    return contenido.startswith(b"%PDF-") and b"%%EOF" in contenido[-2048:]


# ---------------------------------------------------------------------------
# AC único — información suficiente -> PDF profesional listo para compartir.
# ---------------------------------------------------------------------------
class TestExportaUnPDFListoParaCompartir:
    def test_produce_un_archivo_pdf_valido(self, documento_con_contenido, tmp_path):
        ruta_destino = str(tmp_path / "salida.pdf")

        resultado = exportar_a_pdf(documento_con_contenido, ruta_destino)

        assert os.path.exists(ruta_destino)
        assert resultado.ruta == ruta_destino
        assert resultado.bytes_escritos == os.path.getsize(ruta_destino)
        assert resultado.bytes_escritos > 0
        assert _es_pdf_valido(ruta_destino)

    def test_crea_los_directorios_intermedios_si_no_existen(self, documento_con_contenido, tmp_path):
        ruta_destino = str(tmp_path / "subcarpeta" / "anidada" / "salida.pdf")

        resultado = exportar_a_pdf(documento_con_contenido, ruta_destino)

        assert os.path.exists(resultado.ruta)

    def test_conserva_la_fecha_de_generacion_del_documento(self, documento_con_contenido, tmp_path):
        ruta_destino = str(tmp_path / "salida.pdf")

        resultado = exportar_a_pdf(documento_con_contenido, ruta_destino)

        assert resultado.generado_en == documento_con_contenido.generado_en

    def test_documento_solo_con_una_seccion_de_tabla_tambien_exporta(self, tmp_path):
        from datetime import datetime

        documento = DocumentoExportable(
            titulo="Solo tabla",
            paciente_ref="paciente-2",
            generado_en=datetime(2026, 1, 1),
            secciones=(
                SeccionDocumento(
                    titulo="Biomarcadores",
                    bloques=(BloqueTabla(encabezados=("Fecha", "Resultado"), filas=(("2026-01-01", "Positivo"),)),),
                ),
            ),
        )
        ruta_destino = str(tmp_path / "solo_tabla.pdf")

        resultado = exportar_a_pdf(documento, ruta_destino)

        assert _es_pdf_valido(resultado.ruta)


# ---------------------------------------------------------------------------
# Comportamiento defensivo heredado del resto del proyecto: nunca se produce
# un PDF "profesional" disfrazado a partir de información insuficiente.
# ---------------------------------------------------------------------------
class TestRechazaDocumentosSinContenido:
    def test_documento_sin_secciones_lanza_error_explicito(self, documento_vacio, tmp_path):
        ruta_destino = str(tmp_path / "no_deberia_existir.pdf")

        with pytest.raises(DocumentoInsuficienteError):
            exportar_a_pdf(documento_vacio, ruta_destino)

        assert not os.path.exists(ruta_destino)

    def test_documento_con_secciones_sin_bloques_tambien_se_rechaza(self, tmp_path):
        from datetime import datetime

        documento = DocumentoExportable(
            titulo="Secciones vacías",
            paciente_ref="paciente-3",
            generado_en=datetime(2026, 1, 1),
            secciones=(SeccionDocumento(titulo="Diagnóstico", bloques=()),),
        )
        ruta_destino = str(tmp_path / "no_deberia_existir.pdf")

        with pytest.raises(DocumentoInsuficienteError):
            exportar_a_pdf(documento, ruta_destino)

    def test_tiene_contenido_es_falso_cuando_no_hay_secciones_con_bloques(self, documento_vacio):
        assert documento_vacio.tiene_contenido() is False


# ---------------------------------------------------------------------------
# Validación de invariantes del modelo genérico.
# ---------------------------------------------------------------------------
class TestModeloDeBloques:
    def test_bloque_tabla_rechaza_filas_con_numero_de_columnas_distinto(self):
        with pytest.raises(ValueError):
            BloqueTabla(encabezados=("A", "B"), filas=(("solo-una-columna",),))

    def test_bloque_texto_conserva_el_texto_tal_cual(self):
        bloque = BloqueTexto("algo de texto")
        assert bloque.texto == "algo de texto"

    def test_seccion_con_bloques_tiene_contenido(self):
        seccion = SeccionDocumento(titulo="X", bloques=(BloqueTexto("y"),))
        assert seccion.tiene_contenido() is True
