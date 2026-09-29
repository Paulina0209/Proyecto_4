"""Demo end-to-end de IA-04: resumen de caso para junta médica / interconsulta.

Ejecútalo con (desde la raíz del repositorio):

    python -m ia_clinica.summary.demo

Usa el modelo GPT configurado en el ``.env`` (``OpenAILLMClient``, el
mismo que IA-02/IA-03) para redactar "tratamientos previos" y "estado
actual" a partir del expediente completo del paciente. Si no hay llave de
OpenAI o la API no responde, el demo lo detecta y sigue funcionando con
``RuleBasedSummaryLLMClient`` para no bloquear la demostración de IA-04,
que es independiente de qué generó el texto de esas dos secciones.

El modelo y el tiempo de espera se ajustan sin tocar código con
``OPENAI_MODEL`` y ``OPENAI_TIMEOUT`` (en el ``.env`` o en la terminal):

    $env:OPENAI_MODEL = "gpt-5.4"
    python -m ia_clinica.summary.demo

El demo muestra dos escenarios, uno por cada criterio de aceptación de
IA-04:

    - Escenario A (AC1 — historia clínica suficiente): María, la paciente
      ya sembrada por ``sembrar_datos_sinteticos``, con diagnóstico,
      estadio, tratamiento previo (quimioterapia neoadyuvante) y
      evolución reciente documentados. El resumen queda completo, listo
      para presentarse.
    - Escenario B (AC2 — información incompleta): un paciente sintético
      nuevo, con diagnóstico registrado pero sin estadio, tratamientos
      previos ni estado actual documentados todavía. El resumen debe
      indicar explícitamente qué secciones faltan, sin inventar nada.
"""

from __future__ import annotations

from historia_clinica_mock.adapters import construir_contexto_resumen_caso
from historia_clinica_mock.db import crear_conexion as crear_conexion_historia
from historia_clinica_mock.seed import sembrar_datos_sinteticos

from ia_clinica.notes.llm_client import OpenAILLMClient
from ia_clinica.summary.generator import CaseSummaryGenerator
from ia_clinica.summary.llm_client import RuleBasedSummaryLLMClient


def _construir_generador() -> CaseSummaryGenerator:
    cliente = OpenAILLMClient()
    if cliente.esta_disponible():
        print(f"Usando OpenAILLMClient ({cliente.model}) para redactar el resumen.")
        return CaseSummaryGenerator(llm_client=cliente)

    print(f"Aviso: no se pudo usar el modelo de OpenAI '{cliente.model}' (¿falta OPENAI_API_KEY en el .env o no hay red?).")
    print("Se usa RuleBasedSummaryLLMClient como respaldo solo para poder demostrar IA-04 sin el modelo real.")
    return CaseSummaryGenerator(llm_client=RuleBasedSummaryLLMClient())


def _crear_paciente_con_informacion_incompleta(conn) -> int:
    """Paciente sintético con diagnóstico registrado pero sin más datos aún.

    A propósito no tiene estadio, ni menciones de tratamiento previo, ni
    de estado/evolución en su única nota de consulta: sirve para
    demostrar el criterio de aceptación AC2 (información incompleta) sin
    depender de que el conjunto de pacientes de ``sembrar_datos_sinteticos``
    cambie en el futuro.
    """

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO pacientes (nombre, fecha_nacimiento, sexo, identificacion, "
        "diagnostico_principal, estadio) VALUES (?, ?, ?, ?, ?, ?)",
        (
            "Paciente sintético — interconsulta inicial",
            "1980-01-01",
            "femenino",
            "SINT-DEMO-IA04",
            "Cáncer de ovario (sospecha inicial)",
            None,
        ),
    )
    paciente_id = cur.lastrowid
    cur.execute(
        "INSERT INTO consultas (paciente_id, fecha, motivo, notas_libres) VALUES (?, ?, ?, ?)",
        (
            paciente_id,
            "2026-06-01",
            "Interconsulta oncológica inicial",
            (
                "Paciente remitida para interconsulta oncológica inicial. "
                "Trae estudios de imagen externos pendientes de revisión por el servicio."
            ),
        ),
    )
    conn.commit()
    return paciente_id


def main() -> None:
    conn_historia = crear_conexion_historia()
    ids = sembrar_datos_sinteticos(conn_historia)
    paciente_incompleto_id = _crear_paciente_con_informacion_incompleta(conn_historia)

    generador = _construir_generador()

    print("=" * 70)
    print("ESCENARIO A (AC1): historia clínica suficiente — paciente María")
    print("=" * 70)
    contexto_completo = construir_contexto_resumen_caso(conn_historia, ids["paciente_maria"])
    resumen_completo = generador.generate_summary(contexto_completo)
    print(resumen_completo.to_text())
    if resumen_completo.tiene_informacion_incompleta():
        # Con un modelo real la redacción no es determinista: si el modelo no
        # cita un fragmento válido para una sección, esa sección se marca como
        # faltante en vez de inventarse (comportamiento esperado, no un error).
        print("Nota: el modelo no respaldó con citas válidas:", resumen_completo.secciones_faltantes())

    print("=" * 70)
    print("ESCENARIO B (AC2): información incompleta — paciente sintético nuevo")
    print("=" * 70)
    contexto_incompleto = construir_contexto_resumen_caso(conn_historia, paciente_incompleto_id)
    resumen_incompleto = generador.generate_summary(contexto_incompleto)
    print(resumen_incompleto.to_text())
    print("Secciones marcadas como faltantes:", resumen_incompleto.secciones_faltantes())
    if not resumen_incompleto.tiene_informacion_incompleta():
        print("Aviso: el escenario B está diseñado para tener al menos una sección faltante.")

    conn_historia.close()


if __name__ == "__main__":
    main()
