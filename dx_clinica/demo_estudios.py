"""Demo end-to-end de DX-01: recomendación de estudios necesarios según el caso.

Ejecútalo con:

    python -m dx_clinica.demo_estudios

No requiere ningún proveedor externo ni LLM: el catálogo de estudios es
una tabla curada (``dx_clinica/catalogo_estudios.py``) y el reconocimiento
de la sospecha diagnóstica, igual que en DX-02, es una heurística de
palabras clave con detección de negación (``dx_clinica/matcher.py``).

Se usa un ``ahora`` explícito (no ``datetime.now()``) en cada escenario:
las fechas de los pacientes sintéticos son fijas, así que fijar también
la fecha de referencia hace que la ventana de "estudio reciente" sea
determinista sin importar cuándo se corra este demo.

Tres escenarios, uno por cada aspecto relevante de DX-01:

    - Escenario A (AC1 — sospecha definida, sin estudios previos):
      María, con sospecha de toxicidad musculoesquelética. No tiene en su
      expediente ningún laboratorio reumatológico ni radiografía de
      articulación, así que ambos estudios del perfil se sugieren
      completos, cada uno con su justificación.
    - Escenario B (AC2 — no repetir estudios redundantes): Carlos, con
      sospecha de progresión de enfermedad metastásica. Ya tiene una TAC
      de tórax y un perfil hepático RECIENTES en el expediente (no se
      vuelven a sugerir), pero su único biomarcador molecular es de hace
      más de un año y medio (fuera de la ventana de recencia), así que sí
      se sugiere reevaluarlo — igual que pide la nota de su consulta
      ("se solicita nueva biopsia para reevaluar biomarcadores").
    - Escenario C (sospecha no reconocida): una sospecha que no coincide
      con ningún perfil del catálogo no genera una lista genérica de
      estudios "por si acaso" — se devuelve vacía, con advertencia
      explícita.
"""

from __future__ import annotations

from datetime import datetime

from historia_clinica_mock.adapters import obtener_hallazgos_de_paciente
from historia_clinica_mock.db import crear_conexion
from historia_clinica_mock.seed import sembrar_datos_sinteticos

from dx_clinica.recomendacion_estudios import recomendar_estudios


def _mostrar_resultado(titulo: str, resultado) -> None:
    print("=" * 70)
    print(titulo)
    print("=" * 70)
    print(f"Sospecha diagnóstica: {resultado.sospecha_diagnostica}")
    print(f"*** {resultado.disclaimer} ***")
    print()

    if resultado.advertencia_sospecha_no_reconocida:
        print(f"(sin sugerencias) {resultado.advertencia_sospecha_no_reconocida}")
        print()
        return

    if resultado.esta_vacio():
        print("(todos los estudios relevantes ya existen recientes en el expediente)")
    else:
        print("Estudios sugeridos:")
        for estudio in resultado.estudios_sugeridos:
            print(f"  #{estudio.orden} [{estudio.tipo}] {estudio.nombre}")
            print(f"       Justificación: {estudio.justificacion}")

    if resultado.estudios_omitidos_por_redundantes:
        print()
        print("Estudios NO sugeridos por ser redundantes con algo ya reciente en el expediente:")
        for omitido in resultado.estudios_omitidos_por_redundantes:
            print(f"  - {omitido.nombre}: {omitido.motivo}")
    print()


def main() -> None:
    conn = crear_conexion()
    ids = sembrar_datos_sinteticos(conn)

    hallazgos_maria = obtener_hallazgos_de_paciente(conn, ids["paciente_maria"])
    resultado_a = recomendar_estudios(
        paciente_id=ids["paciente_maria"],
        sospecha_diagnostica="Sospecha de toxicidad musculoesquelética asociada a tratamiento oncológico",
        hallazgos=hallazgos_maria,
        ahora=datetime(2026, 1, 20),
    )
    _mostrar_resultado("ESCENARIO A (AC1): María — sospecha sin estudios previos", resultado_a)
    assert len(resultado_a.estudios_sugeridos) == 2
    assert not resultado_a.estudios_omitidos_por_redundantes

    hallazgos_carlos = obtener_hallazgos_de_paciente(conn, ids["paciente_carlos"])
    resultado_b = recomendar_estudios(
        paciente_id=ids["paciente_carlos"],
        sospecha_diagnostica="Sospecha de progresión de enfermedad pulmonar metastásica",
        hallazgos=hallazgos_carlos,
        ahora=datetime(2026, 2, 10),
    )
    _mostrar_resultado("ESCENARIO B (AC2): Carlos — no repite estudios recientes ya existentes", resultado_b)
    ids_sugeridos = {e.id for e in resultado_b.estudios_sugeridos}
    ids_omitidos = {o.id for o in resultado_b.estudios_omitidos_por_redundantes}
    assert ids_sugeridos == {"hemograma_completo", "reevaluacion_biomarcadores_moleculares"}
    assert ids_omitidos == {"perfil_hepatico", "tac_torax_control"}

    resultado_c = recomendar_estudios(
        paciente_id=ids["paciente_carlos"],
        sospecha_diagnostica="Quiste ovárico funcional",
        hallazgos=hallazgos_carlos,
        ahora=datetime(2026, 2, 10),
    )
    _mostrar_resultado("ESCENARIO C: sospecha no reconocida por el catálogo", resultado_c)
    assert resultado_c.esta_vacio()
    assert resultado_c.advertencia_sospecha_no_reconocida is not None

    conn.close()


if __name__ == "__main__":
    main()
