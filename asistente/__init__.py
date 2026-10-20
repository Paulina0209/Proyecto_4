"""Asistente conversacional del copiloto: chatbot RAG sobre las bases del sistema.

El oncólogo conversa con el copiloto; el universo de conocimiento son SOLO las
bases del sistema (el expediente de sus pacientes, los documentos cargados y las
guías clínicas versionadas). Cada respuesta cita los registros exactos de los
que salió, y la interfaz los resalta en la historia clínica.

    config.py      variables de entorno (modelo, embeddings, umbral, rutas)
    fragmentos.py  qué se indexa: expediente (con los mismos ids que la HC), documentos y guías
    indice.py      base vectorial (ChromaDB) con embeddings de OpenAI
    llm.py         modelo que redacta: GPT (por defecto) u Ollama (local)
    intencion.py   intención de la pregunta y paciente al que se refiere
    grafo.py       el agente: grafo de LangGraph (validar → recuperar → evaluar → responder/rechazar → guardar)
    historial.py   conversaciones de cada médico (SQLite)

Ver docs/asistente.md.
"""

MENSAJE_SIN_INFORMACION = "No tengo suficiente información en mi base de conocimiento para responder esa pregunta."
