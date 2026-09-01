"""Estadificación automática asistida (EST-01).

Propone un estadio (componentes T/N/M y grupo global) usando el sistema de
estadificación aplicable al tipo de cáncer del paciente, con el sistema y la
versión usados explícitos, el fundamento de cada componente y trazabilidad
hasta la fila del expediente. Es apoyo a la decisión: debe validarlo el
profesional.
"""

from estadificacion.builder import proponer_estadificacion
from estadificacion.incompleta import (
    AnalisisEstadificacionIncompleta,
    ComponenteIndeterminado,
    analizar_estadificacion_incompleta,
)
from estadificacion.models import (
    DISCLAIMER,
    ComponenteEstadio,
    PropuestaEstadificacion,
)
from estadificacion.staging_systems import (
    CATALOGO_SISTEMAS,
    ComponenteDef,
    SistemaEstadificacion,
    agrupar_estadio,
    estadios_candidatos,
    familia_de_valor,
    orden_estadio,
    sistema_para_cancer,
)

__all__ = [
    "proponer_estadificacion",
    "analizar_estadificacion_incompleta",
    "AnalisisEstadificacionIncompleta",
    "ComponenteIndeterminado",
    "PropuestaEstadificacion",
    "ComponenteEstadio",
    "DISCLAIMER",
    "CATALOGO_SISTEMAS",
    "ComponenteDef",
    "SistemaEstadificacion",
    "sistema_para_cancer",
    "agrupar_estadio",
    "estadios_candidatos",
    "orden_estadio",
    "familia_de_valor",
]
