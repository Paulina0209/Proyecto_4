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

import contextlib
import threading
import time
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
            cliente = _abrir_o_reconstruir(config.carpeta_vectorial())
        self._cliente = cliente
        self._embeddings = embeddings or EmbeddingsOpenAI()
        self._coleccion = cliente.get_or_create_collection(COLECCION, metadata={"hnsw:space": "cosine"})
        if _espacio(self._coleccion) != "cosine":
            # Chroma no cambia el espacio de una colección existente: con L2 la "similitud" (1 - distancia) sale
            # en otra escala y el umbral rechaza casi todo. Se rehace; los pacientes se reindexan al consultarlos.
            import logging

            logging.getLogger(__name__).warning("Índice vectorial con distancia %s: se rehace con coseno.", _espacio(self._coleccion))
            for nombre in (COLECCION, f"{COLECCION}_huellas"):
                with contextlib.suppress(Exception):
                    cliente.delete_collection(nombre)
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
        r = None
        for intento in range(3):
            try:
                r = self._coleccion.query(query_embeddings=[vector], n_results=k, where=donde)
                break
            except Exception as exc:  # noqa: BLE001 - chromadb.errors.InternalError
                if "nothing found on disk" not in str(exc).casefold():
                    raise
                time.sleep(0.05 * (intento + 1))
        if r is None:
            # Chroma aún no escribió el segmento HNSW (colección recién llenada y pequeña): se compara contra todos.
            return self._buscar_exhaustiva(vector, donde, k)
        resultados = []
        for i, fid in enumerate((r.get("ids") or [[]])[0]):
            distancia = r["distances"][0][i]
            resultados.append(Recuperado(fid, r["documents"][0][i], 1.0 - float(distancia), dict(r["metadatas"][0][i] or {})))
        return resultados

    def _buscar_exhaustiva(self, vector: Sequence[float], donde, k: int) -> List[Recuperado]:
        import math

        # Sin pedir los embeddings guardados: leerlos también necesita el segmento que falta. Se recalculan.
        r = self._coleccion.get(where=donde, include=["documents", "metadatas"])
        textos = r.get("documents") or []
        norma = math.sqrt(sum(x * x for x in vector)) or 1.0
        candidatos = []
        for fid, texto, meta, emb in zip(r.get("ids") or [], textos, r.get("metadatas") or [], self._embeddings(textos) if textos else []):
            otra = math.sqrt(sum(float(x) * float(x) for x in emb)) or 1.0
            similitud = sum(a * float(b) for a, b in zip(vector, emb)) / (norma * otra)
            candidatos.append(Recuperado(fid, texto, similitud, dict(meta or {})))
        return sorted(candidatos, key=lambda c: c.similitud, reverse=True)[:k]

    def cuantos(self, paciente_id: Optional[int] = None) -> int:
        if paciente_id is None:
            return self._coleccion.count()
        return len(self._coleccion.get(where={"paciente_id": int(paciente_id)}).get("ids") or [])


def _espacio(coleccion) -> str:
    """Métrica de distancia de una colección (``cosine``, ``l2``, ``ip``)."""
    try:
        espacio = ((coleccion.configuration_json or {}).get("hnsw") or {}).get("space")
    except Exception:  # noqa: BLE001 - versiones de chromadb sin configuration_json
        espacio = None
    return espacio or (coleccion.metadata or {}).get("hnsw:space") or "l2"


def _abrir_o_reconstruir(carpeta):
    """Abre el índice; si está dañado (p. ej. binarios HNSW incompletos), lo aparta y empieza uno nuevo.
    Es un derivado de las bases: se vuelve a llenar solo al preguntar o con ``python -m asistente indexar``."""
    import logging
    import time

    import chromadb

    carpeta.mkdir(parents=True, exist_ok=True)
    cliente = chromadb.PersistentClient(path=str(carpeta))
    try:
        # Solo se ABREN las que existen: crearlas aquí, sin métrica, las dejaría en L2 para siempre.
        for coleccion in cliente.list_collections():
            cliente.get_collection(getattr(coleccion, "name", coleccion)).count()
        return cliente
    except Exception as exc:  # noqa: BLE001 - chromadb.errors.InternalError y similares
        logging.getLogger(__name__).warning("Índice vectorial dañado (%s): se aparta y se reconstruye.", exc)
        cliente.clear_system_cache()
        apartado = carpeta.with_name(f"{carpeta.name}_danado_{time.strftime('%Y%m%d_%H%M%S')}")
        try:
            carpeta.rename(apartado)
        except OSError:
            import shutil

            shutil.rmtree(carpeta, ignore_errors=True)
        carpeta.mkdir(parents=True, exist_ok=True)
        return chromadb.PersistentClient(path=str(carpeta))


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
