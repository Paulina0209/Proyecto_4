"""Demo end-to-end de DX-02: base de datos mock -> diagnóstico diferencial.

Ejecútalo con:

    python -m dx_clinica.demo

No requiere ninguna llave de API ni proveedor externo: la evidencia sale
de los `metadata.yaml` ya versionados en `guidelines/`, y el emparejamiento
de criterios es una heurística de palabras clave con detección de
negación (ver `dx_clinica/matcher.py`).
"""

from historia_clinica_mock.adapters import obtener_hallazgos_de_paciente
from historia_clinica_mock.db import crear_conexion
from historia_clinica_mock.repository import obtener_paciente
from historia_clinica_mock.seed import sembrar_datos_sinteticos

from dx_clinica.builder import construir_diagnosticos_diferenciales


def _mostrar_resultado(titulo: str, conn, paciente_id: int) -> None:
    print("=" * 70)
    print(titulo)
    print("=" * 70)

    paciente = obtener_paciente(conn, paciente_id)
    hallazgos = obtener_hallazgos_de_paciente(conn, paciente_id)
    print(f"Diagnóstico principal registrado: {paciente.diagnostico_principal} (estadio {paciente.estadio})")
    print(f"Hallazgos disponibles en el expediente: {len(hallazgos)}")
    print()

    resultado = construir_diagnosticos_diferenciales(paciente, hallazgos)
    print(f"*** {resultado.disclaimer} ***")
    print()

    if resultado.esta_vacio():
        print(f"(sin candidatos) {resultado.advertencia_sin_sustento}")
        print()
        return

    for candidato in resultado.candidatos:
        print(f"#{candidato.orden} — {candidato.nombre}")
        print(f"    Sustento: {candidato.resumen_sustento}")
        for criterio in candidato.criterios_sustentados:
            print(f"      [sustentado] {criterio.descripcion}  <- hallazgos: {list(criterio.hallazgos_ids)}")
        for descripcion in candidato.criterios_sin_sustento:
            print(f"      [sin dato]   {descripcion}")
        if candidato.evidencia:
            print(f"    Evidencia consultable: {candidato.evidencia.resumen_citable()}")
        else:
            print("    Evidencia consultable: no hay una guía relevante registrada para esta alternativa.")
        print()


def main() -> None:
    conn = crear_conexion()
    ids = sembrar_datos_sinteticos(conn)

    _mostrar_resultado("DEMO A: María (cáncer de mama TNBC) — dolor articular post-quimioterapia", conn, ids["paciente_maria"])
    _mostrar_resultado("DEMO B: Carlos (NSCLC metastásico) — sospecha de recaída", conn, ids["paciente_carlos"])

    conn.close()


if __name__ == "__main__":
    main()
