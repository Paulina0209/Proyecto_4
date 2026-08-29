from tx_clinica.agent import construir_agente

agente = construir_agente()

resultado = agente.invoke({
    "messages": [{"role": "user", "content":
        "Paciente con NSCLC metastásico, sin oncogén conductor, "
        "histología no escamosa (adenocarcinoma), ECOG 1, PD-L1 70%, "
        "ex-fumador, primera línea, sin contraindicación para "
        "inmunoterapia. ¿Qué sugieres?"
    }]
})

for mensaje in resultado["messages"]:
    tipo = type(mensaje).__name__
    print(f"--- {tipo} ---")
    if hasattr(mensaje, "tool_calls") and mensaje.tool_calls:
        for tc in mensaje.tool_calls:
            print("  Tool llamada:", tc["name"])
            print("  Argumentos:", tc["args"])
    if hasattr(mensaje, "content") and mensaje.content:
        print("  Contenido:", mensaje.content)