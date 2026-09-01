"""Modelos del resultado de estadificación asistida (EST-01)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Tuple

#: Aviso fijo que acompaña toda propuesta. Regla de negocio de EST-01: la
#: estadificación generada es apoyo a la decisión y debe validarla el
#: profesional de salud.
DISCLAIMER = (
    "Esta estadificación es una propuesta de apoyo a la decisión clínica "
    "generada a partir de los datos disponibles del expediente. NO constituye "
    "una estadificación definitiva y debe ser revisada, ajustada y validada por "
    "el profesional tratante."
)


@dataclass(frozen=True)
class ComponenteEstadio:
    """Un componente del estadio (T, N o M) ya resuelto contra el expediente."""

    codigo: str  # "T" | "N" | "M"
    valor: str  # valor tal como está registrado, p. ej. "cT2"
    criterio_aplicado: str  # descripción del criterio del sistema usado
    fundamento: str  # de qué registro salió y con qué fecha
    fuente_ids: Tuple[str, ...]  # ids trazables a filas del expediente (p. ej. "dato-7")


@dataclass(frozen=True)
class PropuestaEstadificacion:
    """Propuesta completa devuelta al oncólogo para un paciente."""

    paciente_id: int
    generado_en: datetime
    sistema_id: Optional[str]
    sistema_version: Optional[str]
    sistema_nombre: Optional[str]
    sistema_fuente: Optional[str]
    componentes: Tuple[ComponenteEstadio, ...]
    estadio_global: Optional[str]
    fundamento_global: str
    datos_faltantes: Tuple[str, ...] = ()
    nota_alcance: Optional[str] = None

    es_apoyo_a_decision: bool = field(default=True, init=False)
    disclaimer: str = field(default=DISCLAIMER, init=False)

    def esta_completa(self) -> bool:
        """True si se pudo proponer un estadio global sin datos faltantes."""

        return self.estadio_global is not None and not self.datos_faltantes

    def identificador_sistema(self) -> Optional[str]:
        if not self.sistema_id:
            return None
        return f"{self.sistema_id} (v{self.sistema_version})"
