"""Esquemas de entrada/salida de la API (capa HTTP; el dominio está en models.py).

Los de salida se construyen directo desde los dataclasses de dominio o
las filas de la base (`model_validate(..., from_attributes=True)`).
"""
from __future__ import annotations

from datetime import date, time
from enum import Enum
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


class BiomarcadorClaveSchema(_Esquema):
    biomarcador: str
    resultado: str
    terapia: Optional[str]
    confirmado: bool
    fecha: date


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
    # HC-04 AC2: biomarcadores accionables (confirmados primero).
    biomarcadores_clave: list[BiomarcadorClaveSchema] = []


# ---------------------------------------------------------------------------
# HC-02 · Laboratorios (los datos viven en el expediente clínico)
# ---------------------------------------------------------------------------

class LaboratorioCreateSchema(_Esquema):
    """Doble validación: la identificación y el nombre que vienen en la
    orden de laboratorio deben corresponder al paciente."""
    identificacion: str
    nombre: str
    prueba: str
    valor: str
    unidad: Optional[str] = None
    fecha: date
    hora: Optional[time] = None
    rango_referencia: Optional[str] = Field(default=None, description="Formato 'bajo-alto', p. ej. 3.5-5.1")


class MensajeHL7Schema(_Esquema):
    """Interfaz de laboratorio: mensaje HL7 v2 ORU^R01 tal como lo envía el LIS."""
    mensaje: str
    fuente: str = "Interfaz de laboratorio"


class SincronizacionSchema(_Esquema):
    exito: bool
    registros_importados: int
    registros_omitidos: int
    mensaje: str


class AlertaLaboratorioSchema(_Esquema):
    id: int
    laboratorio_id: int
    prueba: str
    valor: str
    unidad: Optional[str]
    limite_superado: str
    severidad: str
    estado: str
    fecha: date
    revisada_por: Optional[str]
    fecha_revision: Optional[str]


class ConflictoLaboratorioSchema(_Esquema):
    id: int
    prueba: str
    momento: str
    laboratorio_a_id: int
    valor_a: str
    unidad_a: Optional[str]
    laboratorio_b_id: int
    valor_b: str
    unidad_b: Optional[str]
    estado: str
    resolucion: Optional[str]
    resuelto_por: Optional[str]
    nota: Optional[str]


class LaboratorioRegistradoSchema(_Esquema):
    laboratorio_id: int
    alerta: Optional[AlertaLaboratorioSchema]
    conflictos: list[ConflictoLaboratorioSchema]


class RevisarAlertaSchema(_Esquema):
    revisada_por: str


class ResolucionConflicto(str, Enum):
    VALIDO_A = "valido_a"
    VALIDO_B = "valido_b"
    AMBOS_VALIDOS = "ambos_validos"
    NINGUNO_VALIDO = "ninguno_valido"


class ResolverConflictoSchema(_Esquema):
    resolucion: ResolucionConflicto
    resuelto_por: str
    nota: Optional[str] = None


class ResumenMarcadorSchema(_Esquema):
    clave: str
    prueba: str
    cantidad: int
    ultima_fecha: date
    ultimo_valor: str
    unidad: Optional[str]


class PuntoTendenciaSchema(_Esquema):
    laboratorio_id: int
    fecha: date
    fecha_hora: Optional[str]
    valor: str
    valor_numerico: Optional[float]
    unidad: Optional[str]
    alterado: bool
    critico: bool
    en_conflicto: bool


class SerieTendenciaSchema(_Esquema):
    unidad: Optional[str]
    puntos: list[PuntoTendenciaSchema]


class TendenciaMarcadorSchema(_Esquema):
    clave: str
    prueba: str
    series: list[SerieTendenciaSchema]
    advertencias: list[str]


# ---------------------------------------------------------------------------
# HC-04 · Biopsias y biomarcadores
# ---------------------------------------------------------------------------

class EpisodioCreateSchema(_Esquema):
    descripcion: str = ""
    tipo_cancer: Optional[str] = Field(default=None, description="Código de cancer_type, p. ej. NSCLC o breast")
    fecha_diagnostico: Optional[date] = None


class EpisodioSchema(_Esquema):
    id: int
    descripcion: str
    tipo_cancer: Optional[str]
    fecha_diagnostico: Optional[date]
    origen: str


class BiopsiaCreateSchema(_Esquema):
    fecha: date
    sitio: str = ""
    procedimiento: str = ""
    diagnostico_histologico: Optional[str] = None
    # Opcional si el paciente tiene un solo episodio diagnóstico (AC1).
    episodio_id: Optional[int] = None
    registrado_por: Optional[str] = None


class BiopsiaSchema(_Esquema):
    id: int
    episodio_id: int
    fecha: date
    sitio: str
    procedimiento: str
    diagnostico_histologico: Optional[str]
    muestra_externa: Optional[str]
    origen: str


class BiomarcadorCreateSchema(_Esquema):
    """Validación estricta contra el catálogo (historia_clinica/
    catalogo_biomarcadores.yaml). ``confirmacion`` repite el resultado
    clave (el estado, o el valor en PD-L1) para evitar inversiones."""
    biopsia_id: int
    biomarcador: str
    estado: str
    confirmacion: str
    metodo: str
    variante: Optional[str] = None
    valor: Optional[float] = None
    ihc_score: Optional[str] = None
    ish: Optional[str] = None
    registrado_por: Optional[str] = None


class BiomarcadorSchema(_Esquema):
    biomarcador_id: int
    biopsia_id: Optional[int]
    episodio_id: Optional[int]
    fecha: date
    biomarcador: str
    resultado: str
    estado: str
    variante: Optional[str]
    valor_numerico: Optional[float]
    metodo: Optional[str]
    # accionable_confirmado | pendiente_confirmacion | informativo | descartado
    relevancia: str
    terapia_asociada: Optional[str]
    variable_tx: Optional[str]
    valor_tx: Optional[str]
    confirmado_por: Optional[str]
    origen: str


class ConfirmarBiomarcadorSchema(_Esquema):
    confirmado_por: str
    confirmacion: str


class DescartarBiomarcadorSchema(_Esquema):
    revisado_por: str
