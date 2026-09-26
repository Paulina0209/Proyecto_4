"""Demo end-to-end de DOC-01: carga de documentos clínicos al expediente.

Ejecútalo con (desde la raíz del repositorio):

    python -m documentos_clinicos.demo_carga_documentos

No depende de ningún proveedor externo: la validación de formato es
puramente local (extensión + firma binaria real del contenido).

Tres escenarios, uno por cada aspecto relevante de DOC-01:

    - Escenario A (AC1 — formato soportado): se cargan un PDF, una
      imagen JPEG y un estudio DICOM (sintéticos, pero con la firma
      binaria real de cada formato) al expediente de María, y se
      confirma que los tres quedan asociados a su historial de
      documentos.
    - Escenario B (AC2 — formato no soportado): se intenta cargar un
      archivo ``.txt`` — se rechaza con un mensaje que indica
      explícitamente los formatos aceptados.
    - Escenario C (contenido que no corresponde al formato declarado):
      un archivo llamado ``informe.pdf`` cuyo contenido real es texto
      plano (no la firma binaria de un PDF) — se rechaza igual, con un
      mensaje distinto que explica por qué.

Los documentos sintéticos se guardan bajo ``./salida_demo_doc01/``.
"""

from __future__ import annotations

import os

from historia_clinica_mock.db import crear_conexion as crear_conexion_historia
from historia_clinica_mock.seed import sembrar_datos_sinteticos

from documentos_clinicos.carga_documentos import (
    ContenidoNoCoincideConFormatoError,
    FormatoNoSoportadoError,
    cargar_documento_clinico,
    crear_conexion,
    leer_contenido_documento,
    listar_documentos_de_paciente,
)

_DIRECTORIO_ALMACENAMIENTO = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "salida_demo_doc01"
)

# Firmas binarias mínimas pero reales de cada formato -- suficientes para
# pasar la validación de contenido sin necesitar un archivo real de
# ejemplo en el repositorio.
_CONTENIDO_PDF_SINTETICO = b"%PDF-1.4\n%Documento sintetico para demo DOC-01\n%%EOF"
_CONTENIDO_JPEG_SINTETICO = b"\xff\xd8\xff\xe0" + b"\x00" * 32
_CONTENIDO_DICOM_SINTETICO = (b"\x00" * 128) + b"DICM" + b"\x00" * 16


def main() -> None:
    conn_historia = crear_conexion_historia()
    ids = sembrar_datos_sinteticos(conn_historia)
    paciente_maria = ids["paciente_maria"]

    conn_documentos = crear_conexion()

    print("=" * 70)
    print("ESCENARIO A (AC1): cargar documentos en formatos soportados")
    print("=" * 70)
    for nombre, contenido in (
        ("biopsia_patologia.pdf", _CONTENIDO_PDF_SINTETICO),
        ("radiografia_torax.jpg", _CONTENIDO_JPEG_SINTETICO),
        ("resonancia_mamaria.dcm", _CONTENIDO_DICOM_SINTETICO),
    ):
        documento = cargar_documento_clinico(
            conn=conn_documentos,
            conn_historia=conn_historia,
            paciente_id=paciente_maria,
            nombre_archivo=nombre,
            contenido=contenido,
            cargado_por="dra.rodriguez",
            directorio_almacenamiento=_DIRECTORIO_ALMACENAMIENTO,
        )
        print(f"  Cargado: {documento.nombre_archivo_original} -> tipo={documento.tipo_documento}, "
              f"id={documento.id}, ruta={documento.ruta_almacenamiento}")
        assert leer_contenido_documento(documento) == contenido

    historial = listar_documentos_de_paciente(conn_documentos, paciente_maria)
    print(f"\nHistorial de documentos de María ({len(historial)} documentos):")
    for doc in historial:
        print(f"  #{doc.id} [{doc.tipo_documento}] {doc.nombre_archivo_original} — cargado por {doc.cargado_por}")
    assert len(historial) == 3

    print()
    print("=" * 70)
    print("ESCENARIO B (AC2): formato no soportado")
    print("=" * 70)
    try:
        cargar_documento_clinico(
            conn=conn_documentos,
            conn_historia=conn_historia,
            paciente_id=paciente_maria,
            nombre_archivo="notas_personales.txt",
            contenido=b"esto es texto plano, no un documento clinico soportado",
            cargado_por="dra.rodriguez",
            directorio_almacenamiento=_DIRECTORIO_ALMACENAMIENTO,
        )
        raise AssertionError("se esperaba que el .txt fuera rechazado")
    except FormatoNoSoportadoError as error:
        print(f"  Rechazado correctamente: {error}")

    print()
    print("=" * 70)
    print("ESCENARIO C: contenido que no corresponde al formato declarado")
    print("=" * 70)
    try:
        cargar_documento_clinico(
            conn=conn_documentos,
            conn_historia=conn_historia,
            paciente_id=paciente_maria,
            nombre_archivo="informe_falso.pdf",
            contenido=b"esto dice ser un pdf pero no tiene la firma binaria real",
            cargado_por="dra.rodriguez",
            directorio_almacenamiento=_DIRECTORIO_ALMACENAMIENTO,
        )
        raise AssertionError("se esperaba que el contenido no coincidente fuera rechazado")
    except ContenidoNoCoincideConFormatoError as error:
        print(f"  Rechazado correctamente: {error}")

    # El historial de María sigue teniendo exactamente los 3 documentos
    # válidos -- ninguno de los dos intentos rechazados dejó rastro.
    assert len(listar_documentos_de_paciente(conn_documentos, paciente_maria)) == 3

    conn_documentos.close()
    conn_historia.close()


if __name__ == "__main__":
    main()
