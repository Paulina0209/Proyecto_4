from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


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
    """Antecedentes personales/familiares básicos. Texto libre, no
    interpretado por el sistema (igual que `condicion` en comorbilidades
    de tx_clinica)."""
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
class ErrorValidacion:
    campo: str
    mensaje: str


@dataclass
class ResultadoRegistroPaciente:
    exito: bool
    paciente: Optional[Paciente] = None
    errores: list = field(default_factory=list)
    # AC3: alerta de posible duplicado antes de crear
    posible_duplicado: Optional[Paciente] = None
