"""SEC-03 — Consentimiento informado y privacidad.

Como paciente/institución, quiero que el sistema gestione el consentimiento
informado sobre el uso de los datos y de la IA, para cumplir la normativa de
protección de datos de salud.

Criterios de aceptación:

    AC1  Dado un paciente nuevo, cuando se crea su historia clínica, el
         sistema exige que se registre el consentimiento informado antes de
         habilitar las funciones de IA sobre sus datos.
    AC2  Si el paciente retira el consentimiento, las funciones de IA dejan de
         aplicarse a su historia clínica, sin borrar la historia existente.

Se construye sobre NFR-06: el consentimiento es una *autorización* de la
finalidad ``asistencia_ia`` dentro de la política ``consentimiento-ia``. Por
eso hereda todo lo de ``privacidad.tratamiento_datos``: tablas de solo
inserción (retirar es un registro nuevo, nada se borra), evidencia obligatoria
(medio y soporte del consentimiento firmado), versión exacta de la política
vigente cuando se firmó y traza en ``eventos_acceso`` (AUD-01).

Activación. La exigencia rige en una base desde que la institución *activa* la
política (``activar_consentimiento_ia``); la API de pacientes lo hace al
arrancar sobre el expediente real. Desde ese momento es fail-closed: un
paciente sin consentimiento otorgado vigente, nuevo o antiguo, queda sin IA.
Una base donde nunca se activó (las bases en memoria de las pruebas de cada
módulo) no tiene la política y no aplica la exigencia.

Las funciones de IA consultan ``exigir_consentimiento_ia`` justo antes de
armar el contexto que le entregan al modelo: IA-01 (consultas), IA-02 (nota),
IA-04 (resumen), DX-02, EST-01 y el agente de tratamiento (TX). Ver
docs/consentimiento_ia.md.

    python -m privacidad.consentimiento_ia estado 6788
    python -m privacidad.consentimiento_ia otorgar 6788 --medio escrito --soporte doc-123
    python -m privacidad.consentimiento_ia retirar 6788
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence

from privacidad.models import Autorizacion, EstadoAutorizacion, Finalidad, ResultadoOperacion
from seguridad.autorizacion import Accion, verificar_permiso
from seguridad.models import Usuario
from privacidad.tratamiento_datos import (
    configurar_politica,
    estado_autorizacion,
    inicializar_esquema,
    politica_vigente,
    registrar_autorizacion,
)

CODIGO_POLITICA = "consentimiento-ia"
FINALIDAD_IA = "asistencia_ia"
BASE_LEGAL = "consentimiento_informado"

DESCRIPCION_FINALIDAD = (
    "Uso de los datos de la historia clínica por las funciones de inteligencia artificial del copiloto "
    "(consultas en lenguaje natural, borradores de notas y resúmenes, diagnóstico diferencial, "
    "estadificación y recomendaciones de tratamiento) como apoyo a la decisión del médico tratante."
)


def _sin_permiso(usuario: Optional[Usuario], accion: Accion) -> Optional[ResultadoOperacion]:
    """NFR-04: si se identifica al usuario, su rol debe permitir la acción (SEC-01).
    Igual que TX-04, sin ``usuario`` no se aplica el control (llamadas internas)."""
    if usuario is None:
        return None
    permiso = verificar_permiso(usuario, accion)
    return None if permiso.permitido else ResultadoOperacion(exito=False, motivo_rechazo=permiso.motivo_rechazo)


class ConsentimientoIARequerido(PermissionError):
    """La función de IA no se puede aplicar a este paciente (sin consentimiento vigente)."""

    def __init__(self, paciente_id: int, motivo: str):
        self.paciente_id = paciente_id
        self.motivo = motivo
        super().__init__(
            f"Las funciones de IA no están habilitadas para el paciente {paciente_id}: {motivo} "
            "Registre el consentimiento informado del paciente para habilitarlas."
        )


@dataclass(frozen=True)
class EstadoConsentimientoIA:
    paciente_id: int
    #: True si la institución activó la exigencia en esta base.
    exigido: bool
    #: True si las funciones de IA se pueden aplicar al paciente.
    ia_habilitada: bool
    motivo: str
    #: Último registro (otorgado, revocado o denegado), o None si nunca hubo.
    ultimo_registro: Optional[Autorizacion] = None

    @property
    def etiqueta(self) -> str:
        if not self.exigido:
            return "no exigido"
        if self.ultimo_registro is None:
            return "pendiente"
        return self.ultimo_registro.estado.value


# ---------------------------------------------------------------------------
# Activación por la institución
# ---------------------------------------------------------------------------


def consentimiento_ia_activo(conn: sqlite3.Connection) -> bool:
    """¿La institución activó la exigencia de consentimiento en esta base?"""
    existe = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'politicas_tratamiento'"
    ).fetchone()
    return bool(existe) and politica_vigente(conn, CODIGO_POLITICA) is not None


def activar_consentimiento_ia(
    conn: sqlite3.Connection,
    usuario_id: int,
    *,
    jurisdiccion: str = "Colombia",
    marco_normativo: Optional[str] = "Definido por la institución (p. ej. Ley 1581 de 2012 y Resolución 1995 de 1999)",
    usuario: Optional[Usuario] = None,
    ahora: Optional[datetime] = None,
) -> ResultadoOperacion:
    """Activa la exigencia en ``conn`` (idempotente: si ya existe, no crea otra versión).

    La política es un dato de la institución: para cambiar el texto, la
    jurisdicción o el marco normativo se publica otra versión con
    ``privacidad.tratamiento_datos.configurar_politica`` y el mismo código.
    """
    if (rechazo := _sin_permiso(usuario, Accion.CONFIGURAR_POLITICA_DATOS)) is not None:
        return rechazo
    inicializar_esquema(conn)
    vigente = politica_vigente(conn, CODIGO_POLITICA)
    if vigente is not None:
        return ResultadoOperacion(exito=True, registro=vigente)
    return configurar_politica(
        conn,
        usuario_id,
        codigo=CODIGO_POLITICA,
        jurisdiccion=jurisdiccion,
        nombre="Consentimiento informado para el uso de IA en la atención",
        marco_normativo=marco_normativo,
        finalidades=(Finalidad(FINALIDAD_IA, DESCRIPCION_FINALIDAD, requiere_autorizacion=True),),
        bases_legales=(BASE_LEGAL,),
        derechos=("acceso", "rectificacion", "revocacion"),
        plazo_respuesta_dias=15,
        requiere_evidencia_autorizacion=True,
        ahora=ahora,
    )


# ---------------------------------------------------------------------------
# Registro y retiro (AC1, AC2)
# ---------------------------------------------------------------------------


def registrar_consentimiento_ia(
    conn: sqlite3.Connection,
    usuario_id: int,
    paciente_id: int,
    *,
    medio: str,
    soporte: str,
    otorgado: bool = True,
    usuario: Optional[Usuario] = None,
    ahora: Optional[datetime] = None,
) -> ResultadoOperacion:
    """Registra la respuesta del paciente: otorga (``otorgado=True``) o rechaza.

    ``medio`` (escrito, digital...) y ``soporte`` (id del documento firmado,
    hash, ruta) son obligatorios: la política exige evidencia.
    """
    if (rechazo := _sin_permiso(usuario, Accion.REGISTRAR_CONSENTIMIENTO_IA)) is not None:
        return rechazo
    if not consentimiento_ia_activo(conn):
        return ResultadoOperacion(
            exito=False,
            motivo_rechazo="La institución no ha activado el consentimiento de IA en esta base (activar_consentimiento_ia).",
        )
    estado = EstadoAutorizacion.OTORGADA if otorgado else EstadoAutorizacion.DENEGADA
    return registrar_autorizacion(
        conn, usuario_id, paciente_id=paciente_id, codigo_politica=CODIGO_POLITICA, finalidad=FINALIDAD_IA,
        base_legal=BASE_LEGAL, estado=estado, medio=medio, evidencia_ref=soporte, ahora=ahora,
    )


def retirar_consentimiento_ia(
    conn: sqlite3.Connection,
    usuario_id: int,
    paciente_id: int,
    *,
    medio: Optional[str] = None,
    soporte: Optional[str] = None,
    usuario: Optional[Usuario] = None,
    ahora: Optional[datetime] = None,
) -> ResultadoOperacion:
    """AC2: el retiro es un registro nuevo (revocada). No toca la historia clínica
    ni el consentimiento anterior, que sigue como evidencia de lo que rigió."""
    if (rechazo := _sin_permiso(usuario, Accion.REGISTRAR_CONSENTIMIENTO_IA)) is not None:
        return rechazo
    if not consentimiento_ia_activo(conn):
        return ResultadoOperacion(
            exito=False,
            motivo_rechazo="La institución no ha activado el consentimiento de IA en esta base (activar_consentimiento_ia).",
        )
    return registrar_autorizacion(
        conn, usuario_id, paciente_id=paciente_id, codigo_politica=CODIGO_POLITICA, finalidad=FINALIDAD_IA,
        base_legal=BASE_LEGAL, estado=EstadoAutorizacion.REVOCADA, medio=medio, evidencia_ref=soporte, ahora=ahora,
    )


# ---------------------------------------------------------------------------
# Verificación (lo que consultan las funciones de IA)
# ---------------------------------------------------------------------------


def estado_consentimiento_ia(conn: sqlite3.Connection, paciente_id: int) -> EstadoConsentimientoIA:
    if not consentimiento_ia_activo(conn):
        return EstadoConsentimientoIA(
            paciente_id, exigido=False, ia_habilitada=True,
            motivo="La institución no ha activado la exigencia de consentimiento en esta base.",
        )
    ultimo = estado_autorizacion(conn, paciente_id, CODIGO_POLITICA, FINALIDAD_IA)
    if ultimo is None:
        return EstadoConsentimientoIA(
            paciente_id, exigido=True, ia_habilitada=False,
            motivo="No hay consentimiento informado registrado.",
        )
    if ultimo.estado is EstadoAutorizacion.OTORGADA:
        return EstadoConsentimientoIA(
            paciente_id, exigido=True, ia_habilitada=True,
            motivo=f"Consentimiento otorgado el {ultimo.fecha[:10]}.", ultimo_registro=ultimo,
        )
    verbo = "retiró" if ultimo.estado is EstadoAutorizacion.REVOCADA else "rechazó"
    return EstadoConsentimientoIA(
        paciente_id, exigido=True, ia_habilitada=False,
        motivo=f"El paciente {verbo} el consentimiento el {ultimo.fecha[:10]}.", ultimo_registro=ultimo,
    )


def exigir_consentimiento_ia(conn: sqlite3.Connection, paciente_id: int) -> EstadoConsentimientoIA:
    """Lanza ``ConsentimientoIARequerido`` si la IA no puede aplicarse al paciente."""
    estado = estado_consentimiento_ia(conn, paciente_id)
    if not estado.ia_habilitada:
        raise ConsentimientoIARequerido(paciente_id, estado.motivo)
    return estado


# ---------------------------------------------------------------------------
# Línea de comandos (sobre el expediente real)
# ---------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    from historia_clinica.db import conectar_expediente

    p = argparse.ArgumentParser(prog="python -m privacidad.consentimiento_ia", description="Consentimiento de IA (SEC-03).")
    p.add_argument("--usuario", type=int, default=1, help="Id de quien registra (queda en la auditoría).")
    sub = p.add_subparsers(dest="comando", required=True)
    sub.add_parser("activar", help="Activa la exigencia de consentimiento en el expediente.")
    e = sub.add_parser("estado", help="Estado del consentimiento de un paciente.")
    e.add_argument("paciente", type=int)
    o = sub.add_parser("otorgar", help="Registra el consentimiento otorgado.")
    o.add_argument("paciente", type=int)
    o.add_argument("--medio", required=True)
    o.add_argument("--soporte", required=True, help="Id o ruta del documento firmado.")
    r = sub.add_parser("retirar", help="Registra el retiro del consentimiento.")
    r.add_argument("paciente", type=int)
    args = p.parse_args(argv)

    conn = conectar_expediente()
    try:
        if args.comando == "activar":
            resultado = activar_consentimiento_ia(conn, args.usuario)
        elif args.comando == "estado":
            estado = estado_consentimiento_ia(conn, args.paciente)
            print(f"Paciente {args.paciente}: {estado.etiqueta} — {estado.motivo}")
            return 0
        elif args.comando == "otorgar":
            activar_consentimiento_ia(conn, args.usuario)
            resultado = registrar_consentimiento_ia(conn, args.usuario, args.paciente, medio=args.medio, soporte=args.soporte)
        else:
            resultado = retirar_consentimiento_ia(conn, args.usuario, args.paciente)
    finally:
        conn.close()
    print("Listo." if resultado.exito else f"No se registró: {resultado.motivo_rechazo}")
    return 0 if resultado.exito else 1


if __name__ == "__main__":
    sys.exit(main())
