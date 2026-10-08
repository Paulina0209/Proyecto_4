"""PAC-03 · Resumen 360 del paciente.

Arma en una sola consulta lo que el oncólogo necesita al abrir la
historia: diagnóstico, estadio y tratamiento más reciente (AC1), alertas
activas y acceso rápido a laboratorios, imágenes y notas. Si falta algún
dato clínico clave, lo reporta en `campos_faltantes` (AC2).

Lee las mismas tablas que registro (HC-01) y búsqueda (PAC-02): un
diagnóstico o tratamiento registrado ahí aparece aquí.

Si se pasa la conexión al expediente clínico y el paciente está en él
(``expediente.paciente_en_expediente``), el 360 suma lo que vive allí:

    - HC-02: alertas por laboratorio crítico (severidad alta) y conflictos
      de laboratorio pendientes (media); los laboratorios recientes se leen
      del expediente, con sus marcas (crítico, en conflicto, fuera de rango).
    - HC-04: biomarcadores clave para el tratamiento, y una alerta por cada
      uno importado que espera la confirmación del oncólogo.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from .expediente import paciente_en_expediente
from .models import AccesoRapido, AlertaActiva, BiomarcadorClave, ResumenPaciente360, TratamientoReciente

#: Máximo de entradas por lista de acceso rápido (evitar sobrecarga).
LIMITE_ACCESO_RAPIDO = 5

#: Más urgente primero.
_ORDEN_SEVERIDAD = {"alta": 0, "media": 1, "baja": 2}


class PacienteNoEncontrado(Exception):
    """El id no existe o pertenece a otro oncólogo. No se distinguen los
    dos casos para no confirmar que el registro existe."""

    def __init__(self, paciente_id: int):
        self.paciente_id = paciente_id
        super().__init__(f"No existe un paciente con id {paciente_id}.")


def obtener_resumen_360(
    conn: sqlite3.Connection,
    paciente_id: int,
    oncologo_id: int,
    conn_expediente: Optional[sqlite3.Connection] = None,
) -> ResumenPaciente360:
    paciente = conn.execute(
        "SELECT nombre_completo FROM pacientes WHERE id = ? AND oncologo_id = ?",
        (paciente_id, oncologo_id),
    ).fetchone()
    if paciente is None:
        raise PacienteNoEncontrado(paciente_id)

    diagnostico = conn.execute(
        "SELECT descripcion, estadio FROM diagnosticos WHERE paciente_id = ? "
        "ORDER BY fecha DESC, id DESC LIMIT 1",
        (paciente_id,),
    ).fetchone()

    fila_tratamiento = conn.execute(
        "SELECT estado, regimen, fecha_inicio FROM tratamientos WHERE paciente_id = ? "
        "ORDER BY fecha_inicio DESC, id DESC LIMIT 1",
        (paciente_id,),
    ).fetchone()
    tratamiento = TratamientoReciente(**dict(fila_tratamiento)) if fila_tratamiento else None

    alertas = [
        AlertaActiva(**dict(f))
        for f in conn.execute(
            "SELECT tipo, severidad, descripcion, fecha FROM alertas "
            "WHERE paciente_id = ? AND resuelta = 0 ORDER BY fecha DESC, id DESC",
            (paciente_id,),
        ).fetchall()
    ]
    labs = _estudios(conn, paciente_id, "laboratorio")
    biomarcadores: tuple[BiomarcadorClave, ...] = ()

    expediente_id = (
        paciente_en_expediente(conn, conn_expediente, paciente_id) if conn_expediente is not None else None
    )
    if expediente_id is not None:
        alertas += _alertas_del_expediente(conn_expediente, expediente_id)
        labs = _labs_del_expediente(conn_expediente, expediente_id) or labs
        biomarcadores = _biomarcadores_clave(conn_expediente, expediente_id)
    alertas.sort(key=lambda a: _ORDEN_SEVERIDAD.get(a.severidad, 99))

    diagnostico_principal = diagnostico["descripcion"] if diagnostico else None
    estadio = diagnostico["estadio"] if diagnostico else None
    if diagnostico_principal is None and expediente_id is not None:
        # HC-04: el diagnóstico pudo registrarse como episodio diagnóstico
        # (con su biopsia). El estadio no se toma de ahí: no lo tiene.
        diagnostico_principal = _ultimo_episodio(conn_expediente, expediente_id)
    campos_clave = {
        "diagnostico_principal": diagnostico_principal,
        "estadio": estadio,
        "tratamiento_mas_reciente": tratamiento,
    }

    return ResumenPaciente360(
        paciente_id=paciente_id,
        nombre=paciente["nombre_completo"],
        diagnostico_principal=diagnostico_principal,
        estadio=estadio,
        tratamiento_mas_reciente=tratamiento,
        alertas_activas=tuple(alertas),
        labs_recientes=labs,
        imagenes_recientes=_estudios(conn, paciente_id, "imagen"),
        notas_recientes=_notas(conn, paciente_id),
        campos_faltantes=tuple(campo for campo, valor in campos_clave.items() if not valor),
        biomarcadores_clave=biomarcadores,
    )


def _estudios(conn: sqlite3.Connection, paciente_id: int, tipo: str) -> tuple[AccesoRapido, ...]:
    filas = conn.execute(
        "SELECT fecha, resumen, nombre FROM estudios WHERE paciente_id = ? AND tipo = ? "
        "ORDER BY fecha DESC, id DESC LIMIT ?",
        (paciente_id, tipo, LIMITE_ACCESO_RAPIDO),
    ).fetchall()
    return tuple(AccesoRapido(fecha=f["fecha"], resumen=f["resumen"], titulo=f["nombre"]) for f in filas)


def _notas(conn: sqlite3.Connection, paciente_id: int) -> tuple[AccesoRapido, ...]:
    filas = conn.execute(
        "SELECT fecha, nota FROM consultas WHERE paciente_id = ? AND nota IS NOT NULL "
        "ORDER BY fecha DESC, id DESC LIMIT ?",
        (paciente_id, LIMITE_ACCESO_RAPIDO),
    ).fetchall()
    return tuple(AccesoRapido(fecha=f["fecha"], resumen=f["nota"]) for f in filas)


# ---------------------------------------------------------------------------
# Datos del expediente clínico (HC-02, HC-04)
# ---------------------------------------------------------------------------

def _alertas_del_expediente(conn_exp: sqlite3.Connection, expediente_id: int) -> list[AlertaActiva]:
    from historia_clinica.biopsias_biomarcadores import PENDIENTE_CONFIRMACION, biomarcadores_clave
    from historia_clinica.laboratorios import alertas_activas, conflictos_pendientes

    alertas = [
        AlertaActiva(
            tipo="laboratorio_critico",
            severidad="alta",
            descripcion=f"{a.prueba} {a.valor} {a.unidad or ''}".strip() + f": valor crítico ({a.limite_superado}).",
            fecha=a.fecha,
        )
        for a in alertas_activas(conn_exp, expediente_id)
    ]
    alertas += [
        AlertaActiva(
            tipo="conflicto_laboratorio",
            severidad="media",
            descripcion=(
                f"{c.prueba}: dos resultados del mismo momento con valores distintos "
                f"({c.valor_a} y {c.valor_b} {c.unidad_a or ''}".rstrip() + "). Revise cuál es válido."
            ),
            fecha=c.momento[:10],
        )
        for c in conflictos_pendientes(conn_exp, expediente_id)
    ]
    alertas += [
        AlertaActiva(
            tipo="biomarcador_pendiente",
            severidad="media",
            descripcion=(
                f"{b.biomarcador} {b.variante or b.estado}: potencialmente accionable "
                f"({b.terapia_asociada}). Confirme el resultado para usarlo en la decisión de tratamiento."
            ),
            fecha=b.fecha,
        )
        for b in biomarcadores_clave(conn_exp, expediente_id)
        if b.relevancia == PENDIENTE_CONFIRMACION
    ]
    return alertas


def _ultimo_episodio(conn_exp: sqlite3.Connection, expediente_id: int) -> Optional[str]:
    fila = conn_exp.execute(
        "SELECT descripcion FROM episodios_diagnosticos WHERE paciente_id = ? "
        "ORDER BY fecha_diagnostico DESC, id DESC LIMIT 1",
        (expediente_id,),
    ).fetchone()
    return fila[0] if fila else None


def _labs_del_expediente(conn_exp: sqlite3.Connection, expediente_id: int) -> tuple[AccesoRapido, ...]:
    criticos = {f[0] for f in conn_exp.execute(
        "SELECT laboratorio_id FROM alertas_laboratorio WHERE paciente_id = ?", (expediente_id,)
    )}
    en_conflicto = set()
    for a, b in conn_exp.execute(
        "SELECT laboratorio_a_id, laboratorio_b_id FROM conflictos_laboratorio "
        "WHERE paciente_id = ? AND estado = 'pendiente'",
        (expediente_id,),
    ):
        en_conflicto.update((a, b))
    filas = conn_exp.execute(
        "SELECT id, fecha, prueba, valor, unidad, alterado FROM laboratorios WHERE paciente_id = ? "
        "ORDER BY fecha DESC, id DESC LIMIT ?",
        (expediente_id, LIMITE_ACCESO_RAPIDO),
    ).fetchall()

    def marca(f) -> str:
        if f["id"] in en_conflicto:
            return " (en conflicto)"
        if f["id"] in criticos:
            return " (crítico)"
        return " (fuera de rango)" if f["alterado"] else ""

    return tuple(
        AccesoRapido(fecha=f["fecha"], resumen=f"{f['valor']} {f['unidad'] or ''}".strip() + marca(f), titulo=f["prueba"])
        for f in filas
    )


def _biomarcadores_clave(conn_exp: sqlite3.Connection, expediente_id: int) -> tuple[BiomarcadorClave, ...]:
    from historia_clinica.biopsias_biomarcadores import ACCIONABLE_CONFIRMADO, biomarcadores_clave

    return tuple(
        BiomarcadorClave(
            biomarcador=b.biomarcador,
            resultado=b.resultado,
            terapia=b.terapia_asociada,
            confirmado=b.relevancia == ACCIONABLE_CONFIRMADO,
            fecha=b.fecha,
        )
        for b in biomarcadores_clave(conn_exp, expediente_id)
    )
