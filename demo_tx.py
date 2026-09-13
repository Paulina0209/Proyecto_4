"""Demo interactiva de tx_clinica, actualizada para:
  - thread_id persistente (lo exige el checkpointer desde que se agregó
    HumanInTheLoopMiddleware para TX-04)
  - manejo de interrupciones: cuando el agente llama a
    registrar_decision_tratamiento, la ejecución se PAUSA y hay que
    aprobar/editar/rechazar antes de que se ejecute de verdad

Uso: igual que antes (escribe tu mensaje, Enter). Nuevo: cuando aparezca
"~~~ DECISIÓN PENDIENTE DE APROBACIÓN ~~~", revisa lo que se va a
registrar y responde con:
    a  -> aprobar tal cual
    r  -> rechazar (te pide un motivo, que se lo pasa al modelo como
          feedback -- el modelo puede reintentar con otros argumentos)

NOTA: la forma exacta del payload de interrupción (`__interrupt__`) se
imprime completa antes de pedir tu decisión, por si tu versión de
langchain trae una forma distinta a la documentada -- avísame si ves
algo que no calza con lo que este script espera.
"""

from langgraph.types import Command

from tx_clinica.agent import construir_agente
from tx_clinica.tools._db import obtener_conexion

agente = construir_agente()

conn = obtener_conexion()  # dispara la creación del esquema + siembra real, si no existía ya
with open("patients\paciente_de_prueba.sql", encoding="utf-8") as f:
    conn.executescript(f.read())
conn.commit()
historial: list[dict] = []

# Fijo para toda la sesión de esta demo -- el checkpointer necesita un
# thread_id estable para poder pausar/reanudar la misma conversación.
config = {"configurable": {"thread_id": "demo-tx-clinica-1"}}

print("Escribe tu mensaje y presiona Enter. Escribe 'salir' para terminar.\n")


def _imprimir_mensajes_nuevos(mensajes_previos_len: int, mensajes: list) -> None:
    for mensaje in mensajes[mensajes_previos_len:]:
        tipo = type(mensaje).__name__
        print(f"--- {tipo} ---")
        if hasattr(mensaje, "tool_calls") and mensaje.tool_calls:
            for tc in mensaje.tool_calls:
                print("  Tool llamada:", tc["name"])
                print("  Argumentos:", tc["args"])
        if hasattr(mensaje, "content") and mensaje.content:
            print("  Contenido:", mensaje.content)


def _manejar_interrupcion(resultado: dict) -> dict:
    """Si el grafo se pausó (HumanInTheLoopMiddleware), pide la decisión
    del oncólogo y reanuda. Devuelve el resultado final ya sin
    interrupciones pendientes."""
    while "__interrupt__" in resultado and resultado["__interrupt__"]:
        interrupcion = resultado["__interrupt__"][0]
        print("\n~~~ DECISIÓN PENDIENTE DE APROBACIÓN ~~~")
        print(interrupcion)  # forma cruda, por si difiere de lo esperado

        # Intenta encontrar cuántas acciones hay que decidir (para armar
        # una decisión por cada una) -- nombres de llave defensivos,
        # porque no se pudo confirmar contra un Ollama real desde el
        # entorno de desarrollo.
        valor = getattr(interrupcion, "value", interrupcion)
        acciones = (
            valor.get("action_requests")
            or valor.get("actionRequests")
            or [None]
        )

        decisiones = []
        for accion in acciones:
            print("\nAcción propuesta:", accion)
            respuesta = input("¿Aprobar (a) o rechazar (r)? > ").strip().lower()
            if respuesta == "r":
                motivo = input("Motivo del rechazo: ").strip()
                decisiones.append({"type": "reject", "message": motivo})
            else:
                decisiones.append({"type": "approve"})

        resultado = agente.invoke(Command(resume={"decisions": decisiones}), config=config)

    return resultado


while True:
    pregunta = input("Oncólogo> ").strip()
    if not pregunta:
        continue
    if pregunta.lower() in {"salir", "exit", "quit"}:
        break

    historial.append({"role": "user", "content": pregunta})

    resultado = agente.invoke({"messages": historial}, config=config)
    resultado = _manejar_interrupcion(resultado)

    _imprimir_mensajes_nuevos(len(historial) - 1, resultado["messages"])

    historial = resultado["messages"]
    print()