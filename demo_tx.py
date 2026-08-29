from tx_clinica.agent import construir_agente

agente = construir_agente()
historial: list[dict] = []

print("Escribe tu mensaje y presiona Enter. Escribe 'salir' para terminar.\n")

while True:
    pregunta = input("Oncólogo> ").strip()
    if not pregunta:
        continue
    if pregunta.lower() in {"salir", "exit", "quit"}:
        break

    historial.append({"role": "user", "content": pregunta})

    resultado = agente.invoke({"messages": historial})
    mensajes_nuevos = resultado["messages"][len(historial) - 1 :]
    for mensaje in mensajes_nuevos:
        tipo = type(mensaje).__name__
        print(f"--- {tipo} ---")
        if hasattr(mensaje, "tool_calls") and mensaje.tool_calls:
            for tc in mensaje.tool_calls:
                print("  Tool llamada:", tc["name"])
                print("  Argumentos:", tc["args"])
        if hasattr(mensaje, "content") and mensaje.content:
            print("  Contenido:", mensaje.content)

    historial = resultado["messages"]
    print()