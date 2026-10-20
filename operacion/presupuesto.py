"""NFR-01 — La nota (IA-02) o el resumen (IA-04) llegan en menos de 10 s.

GPT tarda normalmente entre 4 y 7 s en redactar un borrador, pero sin límite
una respuesta lenta, más los reintentos del cliente, podía tardar minutos.
``LLMConPresupuesto`` envuelve al cliente del modelo:

    - le da al modelo el presupuesto (por defecto 8 s, con margen para validar
      y armar el borrador dentro de los 10 s);
    - si no responde a tiempo o falla, usa el cliente por reglas, que responde
      en milisegundos con el mismo formato. El generador valida igual cada
      sección contra los fragmentos de la consulta, así que el borrador de
      respaldo es tan trazable como el de GPT; solo es menos redactado;
    - deja en ``ultimo_uso`` qué cliente respondió, en cuánto y por qué, para
      que la interfaz pueda avisar «borrador por reglas: el modelo no respondió
      a tiempo».

Sirve para cualquier cliente con ``complete(system_prompt, user_prompt)``
(notas de IA-02 y resúmenes de IA-04).
"""

from __future__ import annotations

import concurrent.futures
import time
from dataclasses import dataclass
from typing import Any, Optional

from operacion.latencia import OBJETIVO_NOTA_S

#: Tiempo que se le da al modelo; el resto hasta OBJETIVO_NOTA_S es para validar el borrador.
PRESUPUESTO_MODELO_S = 8.0

# Hilos compartidos: una llamada que se pasa del presupuesto sigue en su hilo
# hasta que el cliente HTTP la corta, sin bloquear al médico.
_EJECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="llm-presupuesto")


@dataclass(frozen=True)
class UsoModelo:
    #: "modelo" si respondió el cliente principal, "respaldo" si se usó el de reglas.
    proveedor: str
    segundos: float
    motivo: Optional[str] = None

    @property
    def uso_respaldo(self) -> bool:
        return self.proveedor == "respaldo"


class LLMConPresupuesto:
    def __init__(self, principal: Any, respaldo: Any, presupuesto_s: float = PRESUPUESTO_MODELO_S):
        if presupuesto_s <= 0 or presupuesto_s >= OBJETIVO_NOTA_S:
            raise ValueError(f"El presupuesto debe estar entre 0 y {OBJETIVO_NOTA_S} s.")
        self.principal = principal
        self.respaldo = respaldo
        self.presupuesto_s = presupuesto_s
        self.ultimo_uso: Optional[UsoModelo] = None

    @property
    def model(self) -> str:
        return getattr(self.principal, "model", type(self.principal).__name__)

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        inicio = time.perf_counter()
        futuro = _EJECUTOR.submit(self.principal.complete, system_prompt, user_prompt)
        try:
            texto = futuro.result(timeout=self.presupuesto_s)
        except concurrent.futures.TimeoutError:
            futuro.cancel()
            motivo = f"el modelo no respondió en {self.presupuesto_s:.0f} s"
        except Exception as exc:  # red, llave, cuota: el borrador por reglas sigue sirviendo
            motivo = f"el modelo falló ({type(exc).__name__})"
        else:
            self.ultimo_uso = UsoModelo("modelo", time.perf_counter() - inicio)
            return texto

        texto = self.respaldo.complete(system_prompt, user_prompt)
        self.ultimo_uso = UsoModelo("respaldo", time.perf_counter() - inicio, motivo)
        return texto


def cliente_openai_para_presupuesto(presupuesto_s: float = PRESUPUESTO_MODELO_S, **kwargs):
    """``OpenAILLMClient`` sin reintentos y con el tiempo de espera del presupuesto,
    para que una llamada lenta no siga consumiendo un hilo mucho después."""
    from ia_clinica.notes.llm_client import OpenAILLMClient

    return OpenAILLMClient(timeout=presupuesto_s, max_retries=0, **kwargs)
