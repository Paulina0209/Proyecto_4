"""Esquemas de entrada/salida de la API (capa HTTP; el dominio está en models.py).

Los de salida se construyen directo desde los dataclasses de dominio o
las filas de la base (`model_validate(..., from_attributes=True)`).
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .models import EstadoTratamiento, Sexo, TipoIdentificacion


class _Esquema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorValidacionSchema(_Esquema):
    campo: str
    mensaje: str


class ErroresValidacionResponse(_Esquema):
    errores: list[ErrorValidacionSchema]


# ---------------------------------------------------------------------------
# HC-01 · Registro de paciente
# ---------------------------------------------------------------------------

class DatosContactoSchema(_Esquema):
    telefono: Optional[str] = None
    email: Optional[str] = None
    direccion: Optional[str] = None


class AntecedentesSchema(_Esquema):
    personales: Optional[str] = None
    familiares: Optional[str] = None


class PacienteCreateSchema(_Esquema):
    # Defaults "vacíos" a propósito: la obligatoriedad la valida
    # registro.py (AC2), para responder qué campo falta con su mensaje.
    nombre_completo: str = ""
    fecha_nacimiento: Optional[date] = None
    sexo: Optional[Sexo] = None
    tipo_identificacion: Optional[TipoIdentificacion] = None
    # Vacío con tipo "temporal": el servidor genera el identificador.
    numero_identificacion: Optional[str] = None
    contacto: DatosContactoSchema = Field(default_factory=DatosContactoSchema)
    oncologo_id: int
    antecedentes: AntecedentesSchema = Field(default_factory=AntecedentesSchema)
    motivo_consulta_inicial: Optional[str] = None


class CompletarRegistroSchema(_Esquema):
    """Solo los campos que se envían con valor se actualizan."""
    antecedentes: AntecedentesSchema = Field(default_factory=AntecedentesSchema)
    motivo_consulta_inicial: Optional[str] = None


class PacienteResponseSchema(_Esquema):
    id: int
    nombre_completo: str
    fecha_nacimiento: Optional[date]
    sexo: Sexo
    tipo_identificacion: TipoIdentificacion
    numero_identificacion: str
    contacto: DatosContactoSchema
    antecedentes: AntecedentesSchema
    motivo_consulta_inicial: Optional[str]
    oncologo_id: int
    registro_completo: bool


class DuplicadoResponse(_Esquema):
    mensaje: str = "Ya existe un paciente registrado con esta identificación."
    # Solo se incluye si el duplicado es del mismo oncólogo que registra.
    posible_duplicado: Optional[PacienteResponseSchema] = None


# ---------------------------------------------------------------------------
# PAC-02 · Búsqueda y datos clínicos
# ---------------------------------------------------------------------------

class PacienteResumenSchema(_Esquema):
    id: int
    nombre_completo: str
    fecha_nacimiento: Optional[date]
    tipo_identificacion: TipoIdentificacion
    numero_identificacion: str
    diagnosticos: list[str]
    estado_tratamiento: Optional[str]
    fecha_ultima_consulta: Optional[date]


class BusquedaPacientesResponse(_Esquema):
    items: list[PacienteResumenSchema]
    total: int
    pagina: int
    tamano_pagina: int
    total_paginas: int
    filtros_aplicados: dict[str, str]
    # Solo con total == 0: el front lo muestra en lugar de una lista vacía.
    mensaje: Optional[str] = None


class DiagnosticoCreateSchema(_Esquema):
    descripcion: str = ""
    estadio: Optional[str] = None
    fecha: Optional[date] = None


class DiagnosticoSchema(_Esquema):
    id: int
    paciente_id: int
    descripcion: str
    estadio: Optional[str]
    fecha: Optional[date]


class TratamientoCreateSchema(_Esquema):
    estado: EstadoTratamiento
    regimen: Optional[str] = None
    fecha_inicio: Optional[date] = None


class TratamientoSchema(_Esquema):
    id: int
    paciente_id: int
    estado: EstadoTratamiento
    regimen: Optional[str]
    fecha_inicio: Optional[date]


class ConsultaCreateSchema(_Esquema):
    fecha: date
    nota: Optional[str] = None


class ConsultaSchema(_Esquema):
    id: int
    paciente_id: int
    fecha: date
    nota: Optional[str]


# ---------------------------------------------------------------------------
# PAC-03 · Resumen 360
# ---------------------------------------------------------------------------

class TratamientoRecienteSchema(_Esquema):
    estado: str
    regimen: Optional[str]
    fecha_inicio: Optional[date]


class AlertaActivaSchema(_Esquema):
    tipo: str
    severidad: str
    descripcion: str
    fecha: date


class AccesoRapidoSchema(_Esquema):
    fecha: date
    resumen: str
    titulo: Optional[str] = None


class Resumen360Schema(_Esquema):
    paciente_id: int
    nombre: str
    diagnostico_principal: Optional[str]
    estadio: Optional[str]
    tratamiento_mas_reciente: Optional[TratamientoRecienteSchema]
    alertas_activas: list[AlertaActivaSchema]
    labs_recientes: list[AccesoRapidoSchema]
    imagenes_recientes: list[AccesoRapidoSchema]
    notas_recientes: list[AccesoRapidoSchema]
    # AC2: el front muestra un indicador de "información faltante" cuando
    # esto no está vacío.
    campos_faltantes: list[str]
    informacion_incompleta: bool
