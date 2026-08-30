"""Demo de DX-03: manejo de la incertidumbre diagnóstica y juicio clínico.

Ejecútalo con (desde la raíz del repositorio):

    python -m dx_clinica.demo_incertidumbre

La primera parte usa escenarios construidos a mano (en vez de depender de
los datos sintéticos compartidos de ``historia_clinica_mock``, que pueden
cambiar) para mostrar, de forma determinista, cada uno de los tres tipos
de incertidumbre que distingue ``dx_clinica.incertidumbre`` y también el
caso sin incertidumbre. La segunda parte sí usa el caso real de Carlos
(NSCLC) para mostrar el registro de un juicio clínico que prevalece sobre
la sugerencia del sistema.
"""

from __future__ import annotations

from datetime import datetime, timezone

from dx_clinica.builder import construir_diagnosticos_diferenciales
from dx_clinica.incertidumbre import analizar_incertidumbre
from dx_clinica.juicio_clinico import (
    crear_conexion as crear_conexion_juicios,
    obtener_decision_diagnostica_vigente,
    obtener_historial_juicios,
    registrar_juicio_clinico,
)
from dx_clinica.models import CriterioEvaluado, DiagnosticoDiferencialCandidato, ResultadoDiagnosticoDiferencial

from historia_clinica_mock.adapters import obtener_hallazgos_de_paciente
from historia_clinica_mock.db import crear_conexion as crear_conexion_historia
from historia_clinica_mock.repository import obtener_paciente
from historia_clinica_mock.seed import sembrar_datos_sinteticos

AHORA = datetime(2026, 8, 30, tzinfo=timezone.utc)


def _candidato(perfil_id, nombre, orden, sustentados_ids, sin_sustento):
    criterios_sustentados = tuple(
        CriterioEvaluado(id=f"{perfil_id}-c{i}", descripcion=f"criterio sustentado #{i}", hallazgos_ids=(hid,))
        for i, hid in enumerate(sustentados_ids, start=1)
    )
    return DiagnosticoDiferencialCandidato(
        perfil_id=perfil_id,
        nombre=nombre,
        orden=orden,
        criterios_sustentados=criterios_sustentados,
        criterios_sin_sustento=tuple(sin_sustento),
        evidencia=None,
    )


def _mostrar_analisis(titulo, resultado):
    print("=" * 70)
    print(titulo)
    print("=" * 70)
    analisis = analizar_incertidumbre(resultado)
    print(f"¿Hay incertidumbre?: {analisis.hay_incertidumbre}")
    print(f"Tipos detectados: {[t.value for t in analisis.tipos]}")
    print(f"Mensaje: {analisis.mensaje}")
    if analisis.informacion_adicional_sugerida:
        print("Información adicional que podría ayudar a diferenciar:")
        for sugerencia in analisis.informacion_adicional_sugerida:
            print(f"  - {sugerencia}")
        print(f"  ({analisis.disclaimer_sugerencias})")
    print()


def demo_escenarios_de_incertidumbre() -> None:
    # Escenario A: dos alternativas empatadas exactamente -> AMBIGUEDAD_ENTRE_ALTERNATIVAS.
    empatado_1 = _candidato("perfil_a", "Alternativa A", 1, ["h1", "h2"], ["criterio pendiente de A"])
    empatado_2 = _candidato("perfil_b", "Alternativa B", 2, ["h3", "h4"], ["criterio pendiente de B"])
    resultado_empate = ResultadoDiagnosticoDiferencial(
        paciente_id=999, generado_en=AHORA, candidatos=(empatado_1, empatado_2)
    )
    _mostrar_analisis("ESCENARIO A: dos alternativas empatadas en el primer lugar", resultado_empate)

    # Escenario B: un único líder claro, pero con criterios propios sin sustento -> INFORMACION_FALTANTE.
    lider_incompleto = _candidato("perfil_c", "Alternativa C (líder)", 1, ["h5"], ["dato pendiente 1", "dato pendiente 2"])
    resultado_faltante = ResultadoDiagnosticoDiferencial(
        paciente_id=999, generado_en=AHORA, candidatos=(lider_incompleto,)
    )
    _mostrar_analisis("ESCENARIO B: líder claro, pero con datos propios sin sustento", resultado_faltante)

    # Escenario C: líder con perfil de un solo criterio, ya completo -> INCERTIDUMBRE_INHERENTE_AL_CASO.
    lider_perfil_pobre = _candidato("perfil_e", "Alternativa E (perfil de 1 solo criterio)", 1, ["h6"], [])
    resultado_inherente = ResultadoDiagnosticoDiferencial(
        paciente_id=999, generado_en=AHORA, candidatos=(lider_perfil_pobre,)
    )
    _mostrar_analisis("ESCENARIO C: líder sustentado por completo, pero con un perfil de un solo criterio", resultado_inherente)

    # Escenario D: sin ningún candidato sustentado -> incertidumbre pura, sin forzar una alternativa.
    resultado_vacio = ResultadoDiagnosticoDiferencial(
        paciente_id=999, generado_en=AHORA, candidatos=(), advertencia_sin_sustento="No hay información suficiente."
    )
    _mostrar_analisis("ESCENARIO D: sin ningún candidato sustentado", resultado_vacio)

    # Escenario E (contraste): caso real de Carlos, totalmente sustentado -> sin incertidumbre.
    conn = crear_conexion_historia()
    ids = sembrar_datos_sinteticos(conn)
    paciente_carlos = obtener_paciente(conn, ids["paciente_carlos"])
    hallazgos_carlos = obtener_hallazgos_de_paciente(conn, ids["paciente_carlos"])
    resultado_carlos = construir_diagnosticos_diferenciales(paciente_carlos, hallazgos_carlos)
    _mostrar_analisis(
        "ESCENARIO E (contraste): caso real de Carlos, con su alternativa principal totalmente sustentada",
        resultado_carlos,
    )
    conn.close()


def demo_juicio_clinico_prevalece() -> None:
    print("=" * 70)
    print("PARTE 2: el juicio clínico del médico prevalece (AC4/AC5)")
    print("=" * 70)

    conn_historia = crear_conexion_historia()
    ids = sembrar_datos_sinteticos(conn_historia)
    paciente_carlos = obtener_paciente(conn_historia, ids["paciente_carlos"])
    hallazgos_carlos = obtener_hallazgos_de_paciente(conn_historia, ids["paciente_carlos"])
    resultado_sistema = construir_diagnosticos_diferenciales(paciente_carlos, hallazgos_carlos)
    print(f"Sugerencia del sistema (#1): {resultado_sistema.candidatos[0].nombre}")

    conn_juicios = crear_conexion_juicios()

    decision_inicial = obtener_decision_diagnostica_vigente(conn_juicios, paciente_carlos.id, resultado_sistema)
    print(f"Decisión vigente ANTES de registrar juicio médico: fuente={decision_inicial.fuente!r} -> {decision_inicial.contenido}")
    print()

    print("El oncólogo no está de acuerdo con priorizar 'progresión de enfermedad' y registra su propio juicio:")
    registrar_juicio_clinico(
        conn_juicios,
        paciente_id=paciente_carlos.id,
        diagnostico_registrado=(
            "Toxicidad hepática por tratamiento sistémico como causa principal; progresión de "
            "enfermedad no descartada pero secundaria en este momento, según correlación clínica adicional."
        ),
        autor="dr. Gómez (oncólogo tratante)",
        resultado_sistema=resultado_sistema,
        ahora=AHORA,
    )

    decision_final = obtener_decision_diagnostica_vigente(conn_juicios, paciente_carlos.id, resultado_sistema)
    print(f"Decisión vigente DESPUÉS de registrar juicio médico: fuente={decision_final.fuente!r} -> {decision_final.contenido}")
    print("(El sistema no bloqueó ni validó este juicio contra su propia priorización: se aceptó tal cual.)")
    print()

    print("El médico registra un segundo juicio más adelante (por ejemplo, en una consulta de seguimiento):")
    registrar_juicio_clinico(
        conn_juicios,
        paciente_id=paciente_carlos.id,
        diagnostico_registrado="Confirmada progresión de enfermedad tras biopsia; se descarta causa hepática aislada.",
        autor="dr. Gómez (oncólogo tratante)",
        resultado_sistema=resultado_sistema,
        ahora=AHORA,
    )
    decision_actualizada = obtener_decision_diagnostica_vigente(conn_juicios, paciente_carlos.id, resultado_sistema)
    print(f"Decisión vigente tras el segundo juicio: {decision_actualizada.contenido}")

    historial = obtener_historial_juicios(conn_juicios, paciente_carlos.id)
    print(f"El historial conserva ambos juicios (no se pierde el primero): {len(historial)} juicios registrados.")

    conn_juicios.close()
    conn_historia.close()


def main() -> None:
    demo_escenarios_de_incertidumbre()
    demo_juicio_clinico_prevalece()


if __name__ == "__main__":
    main()
