from tx_clinica.agent import construir_agente

agente = construir_agente()


def preguntar(agente, pregunta: str) -> str:
    resultado = agente.invoke({"messages": [{"role": "user", "content": pregunta}]})
    return resultado["messages"][-1].content


# Caso 1: paciente ya registrado
print(preguntar(agente, "¿Qué datos tiene el paciente 1?"))

# Caso 3: caso descrito directo en el chat, sin base de datos
print(preguntar(
    agente,
    "Paciente con NSCLC metastásico, sin oncogén conductor, "
    "ECOG 1, PD-L1 70%, ex-fumador, primera línea, sin "
    "contraindicación para inmunoterapia. ¿Qué sugieres?",
))