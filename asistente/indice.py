"""Base vectorial del asistente: ChromaDB (en disco) con embeddings de OpenAI.

Cada fragmento se guarda con su texto, su embedding y metadatos: tipo
(expediente / documento / guía), origen, paciente al que pertenece y, para las
guías, organización, módulo y DOI. Así se puede:

    - guardar los fragmentos procesados y asociarlos a su documento o registro original;
    - buscar por similitud SOLO dentro del paciente activo (filtro por ``paciente_id``)
      o solo en las guías;
    - devolver el contexto, con su similitud, para que el grafo decida si alcanza.

El índice de un paciente se mantiene al día por huella: si su expediente cambió,
se reemplazan sus fragmentos antes de buscar. Si el paciente no tiene (o retiró)
el consentimiento de IA, sus fragmentos se borran del índice (SEC-03).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence

from asistente import config
from asistente.fragmentos import Fragmento, fragmentos_de_guias, huella

COLECCION = "copiloto"
TAMANO_LOTE = 96


@dataclass(frozen=True)
class Recuperado:
    id: str
    texto: str
    similitud: float
    metadatos: Dict[str, object]

    def a_dict(self) -> dict:
        return {"id": self.id, "texto": self.texto, "similitud": round(self.similitud, 3), **{k: v for k, v in self.metadatos.items()}}


class EmbeddingsOpenAI:
    """Embeddings con la API de OpenAI (``OPENAI_EMBEDDING_MODEL``), por lotes."""

    def __init__(self, modelo: Optional[str] = None, cliente=None):
        self.modelo = modelo or config.modelo_embeddings()
        self._cliente = cliente

    def _api(self):
        if self._cliente is None:
            from openai import OpenAI

            from core import llm_config

            llave = llm_config.obtener_api_key()
            if not llave:
                raise RuntimeError("Sin OPENAI_API_KEY no se pueden calcular embeddings.")
            self._cliente = OpenAI(api_key=llave, timeout=20, max_retries=1)
        return self._cliente

    def __call__(self, textos: Sequence[str]) -> List[List[float]]:
        vectores: List[List[float]] = []
        for i in range(0, len(textos), TAMANO_LOTE):
            respuesta = self._api().embeddings.create(model=self.modelo, input=list(textos[i:i + TAMANO_LOTE]))
            vectores.extend(d.embedding for d in respuesta.data)
        return vectores


class IndiceVectorial:
    def __init__(self, cliente=None, embeddings: Optional[Callable[[Sequence[str]], List[List[float]]]] = None):
        import chromadb

        if cliente is None:
            carpeta = config.carpeta_vectorial()
            carpeta.mkdir(parents=True, exist_ok=True)
            cliente = chromadb.PersistentClient(path=str(carpeta))
        self._cliente = cliente
        self._embeddings = embeddings or EmbeddingsOpenAI()
        self._coleccion = cliente.get_or_create_collection(COLECCION, metadata={"hnsw:space": "cosine"})
        self._huellas = cliente.get_or_create_collection(f"{COLECCION}_huellas")
        self._cerrojo = threading.Lock()

    # --- escritura ---------------------------------------------------------------------

    def _agregar(self, fragmentos: Sequence[Fragmento]) -> int:
        if not fragmentos:
            return 0
        vectores = self._embeddings([f.texto for f in fragmentos])
        self._coleccion.upsert(ids=[f.id for f in fragmentos], documents=[f.texto for f in fragmentos],
                               embeddings=vectores, metadatas=[f.metadatos_chroma() for f in fragmentos])
        return len(fragmentos)

    def _huella(self, clave: str) -> Optional[str]:
        r = self._huellas.get(ids=[clave])
        return (r.get("metadatas") or [{}])[0].get("huella") if r.get("ids") else None

    def _guardar_huella(self, clave: str, valor: str) -> None:
        self._huellas.upsert(ids=[clave], documents=[clave], embeddings=[[0.0]], metadatas=[{"huella": valor}])

    def sincronizar_paciente(self, paciente_id: int, fragmentos: Sequence[Fragmento]) -> int:
        """Deja en el índice exactamente estos fragmentos del expediente del paciente. Devuelve cuántos se recalcularon."""
        valor = huella(fragmentos)
        clave = f"paciente-{paciente_id}"
        with self._cerrojo:
            if self._huella(clave) == valor:
                return 0
            self._coleccion.delete(where={"$and": [{"paciente_id": int(paciente_id)}, {"tipo": "expediente"}]})
            agregados = self._agregar(list(fragmentos))
            self._guardar_huella(clave, valor)
            return agregados

    def olvidar_paciente(self, paciente_id: int) -> None:
        """Saca del índice todo lo del paciente (consentimiento retirado o no otorgado)."""
        with self._cerrojo:
            self._coleccion.delete(where={"paciente_id": int(paciente_id)})
            self._huellas.delete(ids=[f"paciente-{paciente_id}"])

    def agregar_documento(self, fragmentos: Sequence[Fragmento]) -> int:
        with self._cerrojo:
            return self._agregar(list(fragmentos))

    def asegurar_guias(self) -> int:
        fragmentos = fragmentos_de_guias()
        valor = huella(fragmentos)
        with self._cerrojo:
            if self._huella("guias") == valor:
                return 0
            self._coleccion.delete(where={"tipo": "guia"})
            agregados = self._agregar(fragmentos)
            self._guardar_huella("guias", valor)
            return agregados

    # --- búsqueda ----------------------------------------------------------------------

    def buscar(self, pregunta: str, *, paciente_id: Optional[int] = None, tipo: Optional[str] = None, k: int = 8) -> List[Recuperado]:
        filtros = []
        if paciente_id is not None:
            filtros.append({"paciente_id": int(paciente_id)})
        if tipo is not None:
            filtros.append({"tipo": tipo})
        donde = None if not filtros else filtros[0] if len(filtros) == 1 else {"$and": filtros}
        vector = self._embeddings([pregunta])[0]
        r = self._coleccion.query(query_embeddings=[vector], n_results=k, where=donde)
        resultados = []
        for i, fid in enumerate((r.get("ids") or [[]])[0]):
            distancia = r["distances"][0][i]
            resultados.append(Recuperado(fid, r["documents"][0][i], 1.0 - float(distancia), dict(r["metadatas"][0][i] or {})))
        return resultados

    def cuantos(self, paciente_id: Optional[int] = None) -> int:
        if paciente_id is None:
            return self._coleccion.count()
        return len(self._coleccion.get(where={"paciente_id": int(paciente_id)}).get("ids") or [])


_INDICE: Optional[IndiceVectorial] = None
_CERROJO = threading.Lock()


def indice() -> IndiceVectorial:
    """El índice del proceso (se abre la primera vez que se usa)."""
    global _INDICE
    with _CERROJO:
        if _INDICE is None:
            _INDICE = IndiceVectorial()
        return _INDICE


def usar_indice(nuevo: Optional[IndiceVectorial]) -> None:
    """Para pruebas: reemplaza el índice del proceso."""
    global _INDICE
    with _CERROJO:
        _INDICE = nuevo
