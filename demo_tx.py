
from __future__ import annotations

from datetime import datetime
from typing import Any

try:  # lee LANGFUSE_* del .env de la raíz, si python-dotenv está instalado
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from tx_clinica.agent import construir_agente
from tx_clinica.conversacion import RespuestaAgente, enviar_mensaje, reanudar_con_decisiones
from tx_clinica.observability import vaciar_langfuse
from tx_clinica.tools._db import conn_lock, obtener_conexion

ONCOLOGO_ID = 1

# Estable durante TODA la conversación de esta ejecución (el checkpointer lo
# necesita para pausar/reanudar). Lleva fecha y hora para que cada corrida
# del script sea una sesión distinta en Langfuse: el checkpointer es
# InMemorySaver, así que al reiniciar el proceso la conversación empieza
# de cero de todos modos.
THREAD_ID = f"demo-tx-clinica-{datetime.now():%Y%m%d-%H%M%S}"


def mostrar_pacientes_disponibles() -> None:
    """El agente trabaja sobre la base real (data/copiloto.db): muestra
    pacientes con historia cargada para poder referirse a ellos por id."""
    from expediente.repository import pacientes_con_historia

    conn = obtener_conexion()
    with conn_lock:
        pacientes = pacientes_con_historia(conn, limite=10)
    if not pacientes:
        print("No hay pacientes con historia cargada. Prepara la base real con `python demo.py`.")
        return
    print("Pacientes con historia cargada (id interno):")
    for p in pacientes:
        print(f"  {p.id}. {p.nombre} | {p.diagnostico_principal or 'Sin diagnóstico'}")
    print()


def _imprimir_mensajes_nuevos(mensajes_previos_len: int, mensajes: list) -> int:
    """Imprime los mensajes agregados desde la última vez y devuelve el
    nuevo total (para llamarla de nuevo en el siguiente turno)."""
    for mensaje in mensajes[mensajes_previos_len:]:
        tipo = type(mensaje).__name__
        print(f"--- {tipo} ---")
        if hasattr(mensaje, "tool_calls") and mensaje.tool_calls:
            for tc in mensaje.tool_calls:
                print("  Tool llamada:", tc["name"])
                print("  Argumentos:", tc["args"])
        texto = getattr(mensaje, "text", None) or ""
        if texto:
            print("  Contenido:", texto)
    return len(mensajes)


def _acciones_pendientes(respuesta: RespuestaAgente) -> list[Any]:
    """Aplana las interrupciones en una lista de acciones a resolver.

    Nombres de llave defensivos, porque el payload de
    HumanInTheLoopMiddleware puede variar entre versiones de langchain.
    """
    acciones: list[Any] = []
    for interrupcion in respuesta.pendientes_aprobacion:
        print("\n~~~ DECISIÓN PENDIENTE DE APROBACIÓN ~~~")
        print(interrupcion)  # forma cruda, por si difiere de lo esperado
        valor = getattr(interrupcion, "value", interrupcion)
        encontradas = None
        if isinstance(valor, dict):
            encontradas = valor.get("action_requests") or valor.get("actionRequests")
        acciones.extend(encontradas or [valor])
    return acciones


def _pedir_decisiones(respuesta: RespuestaAgente) -> list[dict[str, Any]]:
    decisiones: list[dict[str, Any]] = []
    for accion in _acciones_pendientes(respuesta):
        print("\nAcción propuesta:", accion)
        eleccion = input("¿Aprobar (a) o rechazar (r)? > ").strip().lower()
        if eleccion == "r":
            motivo = input("Motivo del rechazo: ").strip()
            decisiones.append({"type": "reject", "message": motivo or "Rechazado por el oncólogo."})
        else:
            decisiones.append({"type": "approve"})
    return decisiones


def main() -> None:
    agente = construir_agente()
    mostrar_pacientes_disponibles()

    print(f"thread_id / session Langfuse: {THREAD_ID}")
    print("Escribe tu mensaje y presiona Enter. Escribe 'salir' para terminar.\n")

    mensajes_vistos = 0
    try:
        while True:
            pregunta = input("Oncólogo> ").strip()
            if not pregunta:
                continue
            if pregunta.lower() in {"salir", "exit", "quit"}:
                break

            respuesta = enviar_mensaje(agente, pregunta, THREAD_ID, ONCOLOGO_ID)
            while respuesta.esta_pausada:
                decisiones = _pedir_decisiones(respuesta)
                respuesta = reanudar_con_decisiones(agente, decisiones, THREAD_ID, ONCOLOGO_ID)

            mensajes_vistos = _imprimir_mensajes_nuevos(mensajes_vistos, respuesta.mensajes)
            print()
    finally:
        vaciar_langfuse()  # sin esto, en un script corto pueden perderse traces


if __name__ == "__main__":
    main()
