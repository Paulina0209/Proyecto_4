import pytest

from historia_clinica_mock.db import crear_conexion
from historia_clinica_mock.seed import sembrar_datos_sinteticos

from documentos_clinicos.carga_documentos import crear_conexion as crear_conexion_documentos
from documentos_clinicos.pdf_export import BloqueTabla, BloqueTexto, DocumentoExportable, SeccionDocumento


@pytest.fixture
def conn_sembrada():
    conn = crear_conexion(":memory:")
    ids = sembrar_datos_sinteticos(conn)
    yield conn, ids
    conn.close()


@pytest.fixture
def conn_documentos():
    """Conexión propia (en memoria) para la tabla de solo-inserción de DOC-01.

    Deliberadamente separada de ``conn_sembrada`` (la conexión de
    ``historia_clinica_mock``), igual que en el código de producción:
    ``cargar_documento_clinico`` recibe las dos conexiones por separado.
    """

    conn = crear_conexion_documentos(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def documento_con_contenido() -> DocumentoExportable:
    """Un documento exportable "genérico" con secciones de texto y de tabla."""

    from datetime import datetime

    return DocumentoExportable(
        titulo="Documento de prueba",
        paciente_ref="paciente-1",
        generado_en=datetime(2026, 1, 1, 10, 0),
        secciones=(
            SeccionDocumento(
                titulo="Diagnóstico",
                bloques=(BloqueTexto("Cáncer de mama triple negativo, estadio II."),),
            ),
            SeccionDocumento(
                titulo="Laboratorios",
                bloques=(
                    BloqueTabla(
                        encabezados=("Fecha", "Prueba", "Valor"),
                        filas=(("2026-01-01", "Hemograma", "Normal"),),
                    ),
                ),
            ),
        ),
        disclaimer="Documento generado automáticamente. Verifique antes de compartir.",
        advertencias=("Aviso de ejemplo.",),
    )


@pytest.fixture
def documento_vacio() -> DocumentoExportable:
    from datetime import datetime

    return DocumentoExportable(
        titulo="Documento sin contenido",
        paciente_ref="paciente-9",
        generado_en=datetime(2026, 1, 1),
        secciones=(),
    )
