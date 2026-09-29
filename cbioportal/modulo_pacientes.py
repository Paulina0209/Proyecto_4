"""Volcado de un paciente de cBioPortal en la base del módulo de pacientes.

El módulo ``patients`` (PAC-02 búsqueda, PAC-03 resumen 360) tiene su
propia base (``patients/db``), separada del expediente de
``historia_clinica``. Para que un paciente importado aparezca en la
búsqueda y en el 360 hay que crearlo también ahí, con su diagnóstico,
tratamientos y estudios.

Solo se crea: si el paciente ya existe en esa base no se toca, porque el
oncólogo pudo haber agregado diagnósticos o tratamientos a mano y esta
base no guarda de dónde salió cada fila. El expediente de
``historia_clinica`` sí se actualiza en cada re-importación (HC-01).
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from .importador import ResultadoImportacion
from .mapeo import CLASES_TRATAMIENTO, calendario, registros_desde_cbioportal

TIPO_IDENTIFICACION = "externo"

#: Un tratamiento que terminó a menos de estos días del último evento del
#: paciente se considera en curso al momento de los datos.
DIAS_TRATAMIENTO_EN_CURSO = 30


def volcar_en_modulo_pacientes(
    conn: sqlite3.Connection, resultado: ResultadoImportacion, fecha_referencia: date, oncologo_id: int
) -> Optional[int]:
    """Crea el paciente en ``patients/db`` y devuelve su id.

    ``None`` si la importación no trajo datos. Si ya existía, devuelve su
    id sin modificar nada.
    """
    if resultado.contenido is None or resultado.ficha is None:
        return None
    ficha, contenido = resultado.ficha, resultado.contenido
    fila = conn.execute(
        "SELECT id FROM pacientes WHERE tipo_identificacion = ? AND numero_identificacion = ?",
        (TIPO_IDENTIFICACION, ficha.identificacion),
    ).fetchone()
    if fila:
        return fila[0]

    fecha = calendario(contenido, fecha_referencia)
    registros, _ = registros_desde_cbioportal(contenido, SimpleNamespace(identificacion=ficha.identificacion), fecha_referencia)
    primarios = [r.valores for r in registros if r.tabla == "antecedentes_externos" and r.valores["tipo"] == "condicion"]

    try:
        cursor = conn.execute(
            "INSERT INTO pacientes (nombre_completo, fecha_nacimiento, sexo, tipo_identificacion, numero_identificacion, "
            "antecedentes_personales, oncologo_id, registro_completo, fecha_registro) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)",
            (
                ficha.nombre,
                ficha.fecha_nacimiento if ficha.fecha_nacimiento != "desconocida" else None,
                ficha.sexo,
                TIPO_IDENTIFICACION,
                ficha.identificacion,
                "\n".join(p["descripcion"] for p in primarios) or None,
                oncologo_id,
                datetime.now().isoformat(),
            ),
        )
        paciente_id = cursor.lastrowid

        if ficha.diagnostico_principal:
            conn.execute(
                "INSERT INTO diagnosticos (paciente_id, descripcion, estadio, fecha) VALUES (?, ?, ?, ?)",
                (paciente_id, ficha.diagnostico_principal, ficha.estadio,
                 primarios[0]["fecha"] if len(primarios) == 1 else None),
            )

        for t in _tratamientos(contenido, fecha):
            conn.execute(
                "INSERT INTO tratamientos (paciente_id, estado, regimen, fecha_inicio) VALUES (?, ?, ?, ?)",
                (paciente_id, t["estado"], t["regimen"], t["fecha_inicio"]),
            )

        for r in registros:
            v = r.valores
            if r.tabla == "laboratorios":
                resumen = f"{v['valor']} {v['unidad'] or ''}".strip() + (" (fuera de rango)" if v["alterado"] else "")
                conn.execute(
                    "INSERT INTO estudios (paciente_id, tipo, nombre, resumen, fecha) VALUES (?, 'laboratorio', ?, ?, ?)",
                    (paciente_id, v["prueba"], resumen, v["fecha"]),
                )
            elif r.tabla == "imagenologia":
                conn.execute(
                    "INSERT INTO estudios (paciente_id, tipo, nombre, resumen, fecha) VALUES (?, 'imagen', ?, ?, ?)",
                    (paciente_id, v["modalidad"], f"{v['region']}: {v['hallazgos']}", v["fecha"]),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return paciente_id


def _tratamientos(contenido: Dict[str, Any], fecha) -> List[Dict[str, Any]]:
    """Un tratamiento por fármaco: desde su primera hasta su última
    administración registrada."""
    eventos = contenido.get("eventos") or []
    ultimo_dia = max((d for e in eventos for d in (e.get("inicio"), e.get("fin")) if d is not None), default=0)
    fallecido = (contenido.get("datos_paciente") or {}).get("OS_STATUS") == "1:DECEASED"

    por_agente: Dict[str, Dict[str, Any]] = {}
    for e in eventos:
        a = e["atributos"]
        if e["tipo"] != "Treatment" or not a.get("AGENT") or e.get("inicio") is None:
            continue
        clase = CLASES_TRATAMIENTO.get(a.get("SUBTYPE"), a.get("SUBTYPE") or "tratamiento")
        t = por_agente.setdefault(a["AGENT"], {"regimen": f"{a['AGENT'].capitalize()} ({clase})",
                                               "inicio": e["inicio"], "fin": e["inicio"]})
        t["inicio"] = min(t["inicio"], e["inicio"])
        t["fin"] = max(t["fin"], e.get("fin") if e.get("fin") is not None else e["inicio"])

    return [
        {
            "regimen": t["regimen"],
            "fecha_inicio": fecha(t["inicio"]),
            "estado": "en_tratamiento"
            if not fallecido and ultimo_dia - t["fin"] <= DIAS_TRATAMIENTO_EN_CURSO
            else "finalizado",
        }
        for t in sorted(por_agente.values(), key=lambda t: t["inicio"])
    ]
