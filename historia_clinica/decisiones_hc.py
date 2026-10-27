"""Lo que el médico confirma o corrige de la IA pasa a la historia clínica, en la consulta de ese día.

El ciclo de la propuesta: la IA sugiere (diagnóstico, estadio, tratamiento) → el médico confirma o corrige → eso
queda en la historia clínica. Las tablas de trazabilidad (DX-03, EST-02, TX-04, AUD-02) guardan la comparación IA
frente a médico para auditoría; este módulo hace que la decisión se VEA en la historia clínica:

    - Ficha: el diagnóstico y el estadio que confirmó el médico reemplazan a los anteriores (expediente). En la base
      de pacientes se agregan como el diagnóstico vigente: los anteriores quedan en su historial, nada se borra.
    - Tratamiento aceptado o modificado: queda como tratamiento en curso con el régimen elegido.
    - Consulta del día (la crea si no hay): una línea con lo decidido, quién lo decidió y qué había sugerido la IA.

Así lo leen todas las pantallas (resumen 360, ficha, línea de tiempo, consultas, exportación) y el asistente.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date
from typing import Optional, Tuple

TIPOS = {"diagnostico": "Diagnóstico", "estadio": "Estadio", "tratamiento": "Tratamiento"}
MOTIVO_CONSULTA = "Consulta oncológica"


@dataclass(frozen=True)
class Incorporacion:
    tipo: str
    valor: str
    linea: str
    consulta_id: int
    corregido: bool

    def a_dict(self) -> dict:
        return {"tipo": self.tipo, "valor": self.valor, "linea": self.linea, "consulta_id": self.consulta_id,
                "corregido": self.corregido,
                "mensaje": "Se agregó a la historia clínica, en la consulta de hoy."}


def _igual(a: Optional[str], b: Optional[str]) -> bool:
    return " ".join((a or "").split()).casefold() == " ".join((b or "").split()).casefold()


def _abrir_pacientes() -> sqlite3.Connection:
    from patients import api as papi

    conn = papi.db.conectar(papi.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _paciente_en_pacientes(conn_pac: sqlite3.Connection, identificacion: str) -> Optional[int]:
    fila = conn_pac.execute("SELECT id FROM pacientes WHERE numero_identificacion = ?", (identificacion,)).fetchone()
    return fila[0] if fila else None


def _consulta_del_dia(conn_exp: sqlite3.Connection, expediente_id: int, hoy: str, linea: str) -> int:
    """Agrega la línea a la última consulta de hoy del expediente; si no hay, la crea."""
    fila = conn_exp.execute("SELECT id, notas_libres FROM consultas WHERE paciente_id = ? AND fecha = ? ORDER BY id DESC LIMIT 1",
                            (expediente_id, hoy)).fetchone()
    if fila is None:
        return conn_exp.execute("INSERT INTO consultas (paciente_id, fecha, motivo, notas_libres) VALUES (?, ?, ?, ?)",
                                (expediente_id, hoy, MOTIVO_CONSULTA, linea)).lastrowid
    notas = (fila[1] or "").rstrip()
    conn_exp.execute("UPDATE consultas SET notas_libres = ? WHERE id = ?", (f"{notas}\n{linea}" if notas else linea, fila[0]))
    return fila[0]


def _nota_del_dia(conn_pac: sqlite3.Connection, paciente_id: int, hoy: str, linea: str) -> None:
    fila = conn_pac.execute("SELECT id, nota FROM consultas WHERE paciente_id = ? AND fecha = ? ORDER BY id DESC LIMIT 1",
                            (paciente_id, hoy)).fetchone()
    if fila is None:
        conn_pac.execute("INSERT INTO consultas (paciente_id, fecha, nota) VALUES (?, ?, ?)", (paciente_id, hoy, linea))
    else:
        nota = (fila[1] or "").rstrip()
        conn_pac.execute("UPDATE consultas SET nota = ? WHERE id = ?", (f"{nota}\n{linea}" if nota else linea, fila[0]))


def incorporar_decision(conn_exp: sqlite3.Connection, expediente_id: int, *, tipo: str, valor: str, autor: str,
                        sugerencia: Optional[str] = None, detalle: Optional[str] = None,
                        conn_pacientes: Optional[sqlite3.Connection] = None, hoy: Optional[date] = None) -> Incorporacion:
    """Lleva a la historia clínica la decisión del médico. ``tipo``: diagnostico, estadio o tratamiento.
    Para un tratamiento rechazado, ``valor`` es la palabra «rechazado» y ``detalle`` el motivo."""
    if tipo not in TIPOS:
        raise ValueError(f"Tipo de decisión desconocido: {tipo!r}.")
    valor = " ".join((valor or "").split())
    if not valor:
        raise ValueError("La decisión del médico no puede estar vacía.")
    hoy_iso = (hoy or date.today()).isoformat()
    ficha = conn_exp.execute("SELECT identificacion, diagnostico_principal, estadio FROM pacientes WHERE id = ?", (expediente_id,)).fetchone()
    if ficha is None:
        raise ValueError(f"El paciente {expediente_id} no tiene expediente.")
    identificacion, dx_actual, estadio_actual = ficha[0], ficha[1], ficha[2]

    corregido = bool(sugerencia) and not _igual(sugerencia, valor)
    anterior_ficha = dx_actual if tipo == "diagnostico" else estadio_actual if tipo == "estadio" else None
    if sugerencia:
        accion = "corregido" if corregido else "confirmado"
    elif anterior_ficha:  # la IA no sugirió nada: el médico confirma lo que había en la ficha o lo actualiza
        accion = "confirmado" if _igual(anterior_ficha, valor) else "actualizado"
    else:
        accion = "registrado"
    # Lo clínico va primero y en UNA oración (partes separadas con «;»): la historia clínica divide las notas en
    # oraciones y un «Dra.» en medio cortaría la decisión de su contenido. El responsable va al final, aparte.
    if tipo == "tratamiento":
        if _igual(valor, "rechazado"):
            partes = [f"Tratamiento sugerido por la IA rechazado: {sugerencia or 'sin régimen'}", f"motivo: {detalle or 'sin motivo'}"]
        else:
            partes = [f"Tratamiento decidido: {valor}{f' ({detalle})' if detalle else ''}",
                      f"la IA había sugerido: {sugerencia}" if corregido else "coincide con la sugerencia de la IA"]
    else:
        anterior = dx_actual if tipo == "diagnostico" else estadio_actual
        partes = [f"{TIPOS[tipo]} {accion}: {valor}"]
        if sugerencia:
            partes.append(f"la IA había sugerido: {sugerencia}" if corregido else "coincide con la sugerencia de la IA")
        if anterior and not _igual(anterior, valor):
            partes.append(f"antes en la ficha: {anterior}")
        if detalle:
            partes.append(detalle[0].lower() + detalle[1:])
    linea = "; ".join(partes) + f". Responsable: {autor}."

    propia = conn_pacientes is None
    conn_pac = conn_pacientes or _abrir_pacientes()
    try:
        paciente_id = _paciente_en_pacientes(conn_pac, identificacion)
        # Ficha del expediente: lo último que decidió el médico.
        if tipo == "diagnostico":
            conn_exp.execute("UPDATE pacientes SET diagnostico_principal = ? WHERE id = ?", (valor, expediente_id))
        elif tipo == "estadio":
            conn_exp.execute("UPDATE pacientes SET estadio = ? WHERE id = ?", (valor, expediente_id))
        consulta_id = _consulta_del_dia(conn_exp, expediente_id, hoy_iso, linea)
        if paciente_id is not None:
            # Base de pacientes: un registro nuevo y vigente; los anteriores quedan como historial.
            if tipo == "diagnostico":
                conn_pac.execute("INSERT INTO diagnosticos (paciente_id, descripcion, estadio, fecha) VALUES (?, ?, ?, ?)",
                                 (paciente_id, valor, estadio_actual, hoy_iso))
            elif tipo == "estadio":
                conn_pac.execute("INSERT INTO diagnosticos (paciente_id, descripcion, estadio, fecha) VALUES (?, ?, ?, ?)",
                                 (paciente_id, dx_actual or "Sin diagnóstico registrado", valor, hoy_iso))
            elif not _igual(valor, "rechazado"):
                conn_pac.execute("INSERT INTO tratamientos (paciente_id, estado, regimen, fecha_inicio) VALUES (?, ?, ?, ?)",
                                 (paciente_id, "en_tratamiento", f"{valor}{f' — {detalle}' if detalle else ''}", hoy_iso))
            _nota_del_dia(conn_pac, paciente_id, hoy_iso, linea)
        conn_exp.commit()
        conn_pac.commit()
    finally:
        if propia:
            conn_pac.close()
    return Incorporacion(tipo, valor, linea, consulta_id, corregido)


def nombre_de_usuario(usuario_id: int) -> str:
    """«Nombre completo (usuario)» de quien decide, para la historia clínica."""
    try:
        from datos.capas import RutasTrabajo

        with closing(sqlite3.connect(f"file:{RutasTrabajo.por_defecto().usuarios.as_posix()}?mode=ro", uri=True)) as conn:
            fila = conn.execute("SELECT p.nombre_completo, u.nombre_usuario FROM usuarios u LEFT JOIN perfiles_usuario p "
                                "ON p.usuario_id = u.id WHERE u.id = ?", (usuario_id,)).fetchone()
    except sqlite3.Error:
        fila = None
    if fila is None:
        return f"el oncólogo {usuario_id}"
    return f"{fila[0]} ({fila[1]})" if fila[0] else fila[1]


def farmacos_de(snapshot: dict, regimen_id: Optional[str]) -> Tuple[str, ...]:
    for c in (snapshot or {}).get("candidatos") or []:
        if c.get("regimen_id") == regimen_id:
            return tuple(c.get("farmacos") or ())
    return ()
