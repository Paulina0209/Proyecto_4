"""Demo de HC-03: un PACS simulado con y sin conexión.

    python -m historia_clinica.demo_imagenes_pacs
"""
from __future__ import annotations

from historia_clinica.db import crear_conexion
from historia_clinica.imagenes_pacs import EstudioDICOM, abrir_visor, estudios_del_expediente
from tests.datos_sinteticos import sembrar_datos_sinteticos

UID = "1.2.840.113619.2.55.3.604688119.969.1268071829.6"
#: URL de ejemplo: no abre nada. Para un visor real, ver demo_orthanc.py.
VISOR = "https://visor.hospital.example/viewer?StudyInstanceUIDs={study_uid}"


class PACSSimulado:
    nombre = "PACS demo"

    def __init__(self, caido: bool = False):
        self.caido = caido

    def buscar_estudios(self, identificacion):
        if self.caido:
            raise ConnectionError("conexión rechazada por el PACS")
        return [EstudioDICOM(UID, identificacion, "Ríos^María Fernanda", "2026-01-14", "US", "Ecografía mamaria", None, 3, 120)]


def main() -> None:
    conn = crear_conexion(":memory:")
    paciente = sembrar_datos_sinteticos(conn)["paciente_maria"]

    print("== AC1: PACS disponible (simulado; el link es de ejemplo y no abre, usa demo_orthanc para uno real) ==")
    vista = estudios_del_expediente(conn, paciente, PACSSimulado(), plantilla_visor=VISOR)
    for e in vista.estudios:
        print(f"{e.fecha} {e.modalidad} {e.descripcion}\n  visor: {e.visor_url}\n  informe: {e.informe.texto if e.informe else '—'}")

    print("\n== AC2: PACS caído ==")
    vista = estudios_del_expediente(conn, paciente, PACSSimulado(caido=True), plantilla_visor=VISOR)
    print(vista.mensaje)
    print(abrir_visor(conn, paciente, UID, PACSSimulado(caido=True), plantilla_visor=VISOR).mensaje)


if __name__ == "__main__":
    main()
