"""Demo de HC-03 contra un Orthanc REAL (PACS + visor OHIF) en Docker.

    docker run -p 8042:8042 -p 4242:4242 -e ORTHANC_PASSWORD=orthanc \\
        -e DICOM_WEB_PLUGIN_ENABLED=true -e OHIF_PLUGIN_ENABLED=true orthancteam/orthanc
    pip install pydicom
    python -m historia_clinica.demo_orthanc

Genera un estudio DICOM sintético (una imagen de prueba, NO un paciente
real) con el PatientID ``SINT-0001`` de los datos sintéticos, lo sube a
Orthanc y consulta HC-03 como lo haría el copiloto: lista el estudio, lo enlaza
a su informe y construye el link del visor. Después apaga la conexión para
mostrar el aviso de "integración no disponible" (AC2).

Variables opcionales: ``ORTHANC_URL`` (por defecto http://localhost:8042),
``ORTHANC_USUARIO`` y ``ORTHANC_PASSWORD`` (por defecto orthanc / orthanc).
"""
from __future__ import annotations

import io
import os
import sys

import requests

from historia_clinica.db import crear_conexion
from historia_clinica.imagenes_pacs import FuenteDICOMweb, abrir_visor, estudios_del_expediente
from tests.datos_sinteticos import sembrar_datos_sinteticos

URL = os.environ.get("ORTHANC_URL", "http://localhost:8042").rstrip("/")
USUARIO = os.environ.get("ORTHANC_USUARIO", "orthanc")
PASSWORD = os.environ.get("ORTHANC_PASSWORD", "orthanc")
#: Visor OHIF que incluye la imagen orthancteam/orthanc.
PLANTILLA_VISOR = f"{URL}/ohif/viewer?StudyInstanceUIDs={{study_uid}}"


def generar_dicom_sintetico() -> bytes:
    """Un estudio mínimo: 256x256, escala de grises, ecografía del 2026-01-14
    de la paciente sintética SINT-0001. UIDs deterministas: repetir la demo no
    duplica el estudio."""
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

    estudio_uid = generate_uid(entropy_srcs=["hc03-demo-estudio"])
    serie_uid = generate_uid(entropy_srcs=["hc03-demo-serie"])
    instancia_uid = generate_uid(entropy_srcs=["hc03-demo-instancia"])

    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    meta.MediaStorageSOPInstanceUID = instancia_uid
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID, ds.SOPInstanceUID = SecondaryCaptureImageStorage, instancia_uid
    ds.StudyInstanceUID, ds.SeriesInstanceUID = estudio_uid, serie_uid
    ds.PatientID = "SINT-0001"
    ds.PatientName = "Rios^Maria Fernanda"  # ASCII: sin juego de caracteres especial
    ds.PatientBirthDate = "19730412"
    ds.PatientSex = "F"
    ds.StudyDate = "20260114"
    ds.StudyTime = "100000"
    ds.AccessionNumber = "SINT-ECO-1"
    ds.StudyDescription = "Ecografia mamaria (sintetica)"
    ds.SeriesDescription = "Imagen de prueba"
    ds.Modality = "US"
    ds.SeriesNumber, ds.InstanceNumber = 1, 1
    ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, "MONOCHROME2"
    ds.Rows = ds.Columns = 256
    ds.BitsAllocated = ds.BitsStored = 8
    ds.HighBit, ds.PixelRepresentation = 7, 0
    # Degradado con un círculo "tumor" para que se vea algo en el visor.
    filas = bytearray()
    for y in range(256):
        for x in range(256):
            en_circulo = (x - 128) ** 2 + (y - 128) ** 2 < 40 ** 2
            filas.append(235 if en_circulo else (x + y) // 4)
    ds.PixelData = bytes(filas)
    buffer = io.BytesIO()
    ds.save_as(buffer, enforce_file_format=True)
    return buffer.getvalue()


def subir_a_orthanc() -> None:
    respuesta = requests.post(
        f"{URL}/instances", data=generar_dicom_sintetico(), auth=(USUARIO, PASSWORD),
        headers={"Content-Type": "application/dicom"}, timeout=20,
    )
    respuesta.raise_for_status()
    print(f"Estudio subido a Orthanc ({respuesta.json().get('Status', '?')}).")


def diagnosticar_plugins() -> None:
    """Orthanc devuelve 404 en /dicom-web si el plugin DICOMweb no está
    cargado (en orthancteam/orthanc se activa con variables de entorno)."""
    try:
        plugins = requests.get(f"{URL}/plugins", auth=(USUARIO, PASSWORD), timeout=10).json()
    except (requests.RequestException, ValueError) as exc:
        print(f"  (no pude leer {URL}/plugins: {exc})")
        return
    print(f"  Plugins cargados en Orthanc: {', '.join(plugins) or '(ninguno)'}")
    faltan = [n for n in ("dicom-web", "ohif") if n not in plugins]
    if faltan:
        print(
            f"  Faltan: {', '.join(faltan)}. Reinicia Orthanc con:\n"
            "    docker run -p 8042:8042 -p 4242:4242 -e ORTHANC_PASSWORD=orthanc "
            "-e DICOM_WEB_PLUGIN_ENABLED=true -e OHIF_PLUGIN_ENABLED=true orthancteam/orthanc"
        )


def main() -> int:
    try:
        subir_a_orthanc()
    except ImportError:
        print("Falta pydicom: pip install pydicom")
        return 1
    except requests.RequestException as exc:
        print(f"No pude hablar con Orthanc en {URL}: {exc}\n¿Está corriendo y es correcta la contraseña?")
        return 1

    conn = crear_conexion(":memory:")
    paciente = sembrar_datos_sinteticos(conn)["paciente_maria"]
    pacs = FuenteDICOMweb("Orthanc local", f"{URL}/dicom-web", usuario=USUARIO, password=PASSWORD)

    print("\n== AC1: PACS disponible ==")
    vista = estudios_del_expediente(conn, paciente, pacs, plantilla_visor=PLANTILLA_VISOR)
    print(vista.mensaje or "Integración disponible.")
    for e in vista.estudios:
        print(f"{e.fecha} {e.modalidad} {e.descripcion}  ({e.series} serie, {e.instancias} imagen)")
        print(f"  informe: {e.informe.texto if e.informe else '— (sin informe asociado)'}")
        print(f"  visor:   {e.visor_url}   <- ábrelo en el navegador")
    if not vista.estudios:
        print("Orthanc no devolvió estudios del paciente SINT-0001.")
        diagnosticar_plugins()

    print("\n== AC2: PACS no disponible (puerto equivocado) ==")
    caido = FuenteDICOMweb("Orthanc local", "http://localhost:9/dicom-web", usuario=USUARIO, password=PASSWORD, timeout=3)
    uid = vista.estudios[0].study_uid if vista.estudios else "1.2.3"
    print(abrir_visor(conn, paciente, uid, caido, plantilla_visor=PLANTILLA_VISOR).mensaje)
    return 0


if __name__ == "__main__":
    sys.exit(main())
