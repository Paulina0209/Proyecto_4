"""Modelos de dominio del módulo de pacientes: dataclasses sin SQL ni HTTP."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


@dataclass
class ErrorValidacion:
    campo: str
    mensaje: str


# ---------------------------------------------------------------------------
# HC-01 · Registro de paciente
# ---------------------------------------------------------------------------

class Sexo(str, Enum):
    MASCULINO = "masculino"
    FEMENINO = "femenino"
    OTRO = "otro"


class TipoIdentificacion(str, Enum):
    """Tipos de documento soportados, más el identificador temporal
    para pacientes sin documento (menor, extranjero, indocumentado)."""
    CEDULA = "cedula"
    TARJETA_IDENTIDAD = "tarjeta_identidad"
    PASAPORTE = "pasaporte"
    REGISTRO_CIVIL = "registro_civil"
    TEMPORAL = "temporal"


@dataclass
class DatosContacto:
    telefono: Optional[str] = None
    email: Optional[str] = None
    direccion: Optional[str] = None

    def tiene_al_menos_un_dato(self) -> bool:
        return bool(self.telefono or self.email)


@dataclass
class AntecedentesMedicos:
    """Texto libre, no interpretado por el sistema."""
    personales: Optional[str] = None
    familiares: Optional[str] = None


@dataclass
class Paciente:
    nombre_completo: str
    fecha_nacimiento: Optional[date]
    sexo: Sexo
    tipo_identificacion: TipoIdentificacion
    numero_identificacion: str  # o el identificador temporal generado
    contacto: DatosContacto
    oncologo_id: int
    id: Optional[int] = None
    antecedentes: AntecedentesMedicos = field(default_factory=AntecedentesMedicos)
    motivo_consulta_inicial: Optional[str] = None
    # False mientras falten antecedentes/motivo — soporta "completar después"
    registro_completo: bool = False


@dataclass
class ResultadoRegistroPaciente:
    exito: bool
    paciente: Optional[Paciente] = None
    errores: list[ErrorValidacion] = field(default_factory=list)
    # AC3: alerta de posible duplicado antes de crear
    posible_duplicado: Optional[Paciente] = None


# ---------------------------------------------------------------------------
# PAC-02 · Búsqueda y filtros
# ---------------------------------------------------------------------------

class EstadoTratamiento(str, Enum):
    EN_TRATAMIENTO = "en_tratamiento"
    EN_SEGUIMIENTO = "en_seguimiento"
    SUSPENDIDO = "suspendido"
    FINALIZADO = "finalizado"


@dataclass
class FiltrosBusqueda:
    oncologo_id: int  # alcance de permisos: solo pacientes de este oncólogo
    nombre: Optional[str] = None
    diagnostico: Optional[str] = None
    estado_tratamiento: Optional[EstadoTratamiento] = None
    ultima_consulta_desde: Optional[date] = None
    ultima_consulta_hasta: Optional[date] = None

    def aplicados(self) -> dict[str, str]:
        """Solo los filtros con valor, ya en texto legible (para el mensaje
        de 'sin resultados' y para que la UI muestre los filtros activos)."""
        filtros: dict[str, str] = {}
        if self.nombre and self.nombre.strip():
            filtros["nombre"] = self.nombre.strip()
        if self.diagnostico and self.diagnostico.strip():
            filtros["diagnostico"] = self.diagnostico.strip()
        if self.estado_tratamiento:
            filtros["estado_tratamiento"] = self.estado_tratamiento.value
        if self.ultima_consulta_desde:
            filtros["ultima_consulta_desde"] = self.ultima_consulta_desde.isoformat()
        if self.ultima_consulta_hasta:
            filtros["ultima_consulta_hasta"] = self.ultima_consulta_hasta.isoformat()
        return filtros


@dataclass
class PacienteResumen:
    """Una fila de la lista de resultados de búsqueda."""
    id: int
    nombre_completo: str
    fecha_nacimiento: Optional[date]
    tipo_identificacion: TipoIdentificacion
    numero_identificacion: str
    diagnosticos: list[str] = field(default_factory=list)
    estado_tratamiento: Optional[str] = None  # el del tratamiento más reciente
    fecha_ultima_consulta: Optional[date] = None


@dataclass
class ResultadoBusqueda:
    items: list[PacienteResumen]
    total: int
    pagina: int
    tamano_pagina: int
    mensaje: Optional[str] = None  # solo se llena cuando total == 0

    @property
    def total_paginas(self) -> int:
        return -(-self.total // self.tamano_pagina) if self.total else 0


# ---------------------------------------------------------------------------
# PAC-03 · Resumen 360
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TratamientoReciente:
    estado: str
    regimen: Optional[str]
    fecha_inicio: Optional[str]


@dataclass(frozen=True)
class AlertaActiva:
    tipo: str  # "interaccion" | "estudio_pendiente"
    severidad: str  # "alta" | "media" | "baja"
    descripcion: str
    fecha: str


@dataclass(frozen=True)
class AccesoRapido:
    """Una entrada de lab/imagen/nota para la lista de acceso rápido."""
    fecha: str
    resumen: str
    #: Nombre de la prueba (labs) o modalidad (imágenes); None en notas.
    titulo: Optional[str] = None


@dataclass(frozen=True)
class ResumenPaciente360:
    paciente_id: int
    nombre: str
    diagnostico_principal: Optional[str]
    estadio: Optional[str]
    tratamiento_mas_reciente: Optional[TratamientoReciente]
    alertas_activas: tuple[AlertaActiva, ...] = ()
    labs_recientes: tuple[AccesoRapido, ...] = ()
    imagenes_recientes: tuple[AccesoRapido, ...] = ()
    notas_recientes: tuple[AccesoRapido, ...] = ()
    #: AC2: campos clínicos clave que faltan. Nunca se infieren ni se
    #: rellenan; la UI muestra un indicador por cada uno.
    campos_faltantes: tuple[str, ...] = ()

    @property
    def informacion_incompleta(self) -> bool:
        return bool(self.campos_faltantes)
