"""Escenario de la capa de trabajo: lo que el sistema necesita y cBioPortal no trae.

cBioPortal da pacientes reales desidentificados, con su historia clínica. No
trae nada de lo que la institución registra: usuarios, a qué oncólogo
pertenece cada paciente, consentimientos ni autorizaciones. El escenario lo
agrega, siempre igual (determinista), para que la demo muestre cada caso:

    Usuarios (ADM-01)      un usuario por rol, con ids fijos (ver ``USUARIOS``).
                           Contraseña de todos: ``CLAVE_ESCENARIO``. SOLO PARA DEMO.
    Pacientes              repartidos entre los tres oncólogos; los de la demo
                           unificada son de ``ONCOLOGO_DEMO_ID`` (dra. Gómez).
    Consentimiento de IA   activado (SEC-03) y, en la cohorte con detalle:
      (SEC-03)               - otorgado (la mayoría), con medio y soporte;
                             - pendiente: nunca se registró (la IA no se aplica);
                             - rechazado: el paciente no lo otorgó;
                             - retirado: lo otorgó y después lo retiró;
                             - retirado y vuelto a otorgar.
                           Los pacientes del índice sin detalle quedan pendientes.
    Autorizaciones         política ``co-pacientes`` (NFR-06): investigación
      (NFR-06)               autorizada en parte de la cohorte, y revocada en otra.
    Consulta de revisión   una por paciente de la cohorte (salvo los de la demo,
                           que la registra el oncólogo en vivo): resume lo que el
                           expediente ya tiene de cBioPortal, sin inventar nada.
                           Sin consulta, IA-02 no tiene de qué redactar una nota.

Todo lo que registra el escenario pasa por las funciones del sistema (quedan
la evidencia, la versión de la política y la auditoría), con fechas anteriores
a hoy y a nombre del usuario que lo haría en la institución.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from seguridad.models import Rol, Usuario

VERSION = 1
CLAVE_ESCENARIO = "Demo-Clave-2026"

#: (usuario, rol, nombre completo). El orden fija los ids: el administrador es el 1.
USUARIOS: Tuple[Tuple[str, Rol, str], ...] = (
    ("admin.copiloto", Rol.ADMINISTRADOR, "Administración del sistema"),
    ("dra.gomez", Rol.ONCOLOGO, "Dra. Ana Gómez"),
    ("dr.vega", Rol.ONCOLOGO, "Dr. Andrés Vega"),
    ("dra.rios", Rol.ONCOLOGO, "Dra. Camila Ríos"),
    ("enf.mora", Rol.ENFERMERIA, "Enf. Laura Mora"),
    ("adm.lopez", Rol.ADMINISTRATIVO, "Julián López (admisiones)"),
    ("auditor", Rol.AUDITOR, "Auditoría interna"),
    ("adm.clinico", Rol.ADMINISTRADOR_CLINICO, "Coordinación clínica"),
    ("direccion", Rol.DIRECTOR_MEDICO, "Dirección médica"),
)
IDS = {nombre: i for i, (nombre, _r, _n) in enumerate(USUARIOS, 1)}
ONCOLOGOS = tuple(IDS[n] for n, rol, _ in USUARIOS if rol is Rol.ONCOLOGO)
#: Oncólogo de los pacientes de la demo unificada (demo.py, patients/demo.py...).
ONCOLOGO_DEMO_ID = IDS["dra.gomez"]
ADMINISTRATIVO_ID = IDS["adm.lopez"]

OTORGADO, PENDIENTE, RECHAZADO, RETIRADO, REOTORGADO = "otorgado", "pendiente", "rechazado", "retirado", "retirado_y_reotorgado"
#: Se recorre en ciclo sobre la cohorte: 10 de cada 15 con consentimiento vigente.
CICLO_CONSENTIMIENTO = (OTORGADO,) * 10 + (PENDIENTE, PENDIENTE, RECHAZADO, RETIRADO, REOTORGADO)

POLITICA_DATOS = "co-pacientes"


@dataclass
class ResumenEscenario:
    version: int = VERSION
    aplicado_en: str = ""
    usuarios: Dict[str, int] = field(default_factory=dict)
    pacientes_por_oncologo: Dict[int, int] = field(default_factory=dict)
    cohorte: int = 0
    consentimientos: Dict[str, int] = field(default_factory=dict)
    investigacion: Dict[str, int] = field(default_factory=dict)
    consultas_de_revision: int = 0

    def a_dict(self) -> dict:
        return dict(self.__dict__)


# ---------------------------------------------------------------------------


def version_aplicada(conn: sqlite3.Connection) -> Optional[int]:
    existe = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'escenario_copiloto'"
    ).fetchone()
    if not existe:
        return None
    fila = conn.execute("SELECT MAX(version) FROM escenario_copiloto").fetchone()
    return fila[0] if fila else None


def resumen_aplicado(conn: sqlite3.Connection) -> Optional[dict]:
    if version_aplicada(conn) is None:
        return None
    fila = conn.execute("SELECT resumen_json FROM escenario_copiloto ORDER BY version DESC LIMIT 1").fetchone()
    return json.loads(fila[0]) if fila else None


def _momento(fecha: date, dias_antes: int, hora: int = 9) -> datetime:
    return datetime.combine(fecha - timedelta(days=dias_antes), time(hora, 0), tzinfo=timezone.utc)


def caso_consentimiento(indice: int) -> str:
    return CICLO_CONSENTIMIENTO[indice % len(CICLO_CONSENTIMIENTO)]


def cohorte_con_detalle(conn_exp: sqlite3.Connection) -> List[Tuple[int, str]]:
    """(id en el expediente, id de cBioPortal) de los pacientes con detalle importado."""
    filas = conn_exp.execute(
        "SELECT DISTINCT p.id, p.identificacion FROM pacientes p JOIN sincronizaciones_externas s ON s.paciente_id = p.id "
        "WHERE s.fuente = 'cbioportal' AND s.estado = 'exitosa' ORDER BY p.id"
    ).fetchall()
    return [(f[0], f[1].rsplit(":", 1)[-1]) for f in filas]


# ---------------------------------------------------------------------------
# Partes del escenario
# ---------------------------------------------------------------------------


def crear_usuarios(conn_usuarios: sqlite3.Connection) -> Dict[str, int]:
    from administracion import usuarios as adm

    admin_nombre, _rol, admin_completo = USUARIOS[0]
    admin = adm.crear_primer_administrador(conn_usuarios, admin_nombre, CLAVE_ESCENARIO, admin_completo)
    actor = Usuario(admin.id, admin.nombre_usuario, Rol.ADMINISTRADOR, True)
    creados = {admin_nombre: admin.id}
    for nombre, rol, completo in USUARIOS[1:]:
        creados[nombre] = adm.crear_usuario(conn_usuarios, actor, nombre, CLAVE_ESCENARIO, rol.value, completo).id
    if creados != IDS:  # las demos dependen de estos ids
        raise RuntimeError(f"Los usuarios no quedaron con los ids esperados: {creados}")
    return creados


def repartir_pacientes(conn_pac: sqlite3.Connection, demo: Sequence[str]) -> Dict[int, int]:
    """Los de la demo son de dra. Gómez; el resto, por turnos entre los tres oncólogos."""
    filas = conn_pac.execute("SELECT id, numero_identificacion FROM pacientes ORDER BY id").fetchall()
    asignacion = []
    for i, (paciente_id, identificacion) in enumerate(filas):
        de_demo = str(identificacion).rsplit(":", 1)[-1] in demo
        asignacion.append((ONCOLOGO_DEMO_ID if de_demo else ONCOLOGOS[i % len(ONCOLOGOS)], paciente_id))
    conn_pac.executemany("UPDATE pacientes SET oncologo_id = ? WHERE id = ?", asignacion)
    conn_pac.commit()
    return dict(Counter(o for o, _ in asignacion))


def oncologo_de(conn_pac: sqlite3.Connection, identificacion_cbio: str) -> int:
    fila = conn_pac.execute(
        "SELECT oncologo_id FROM pacientes WHERE numero_identificacion LIKE ?", (f"%:{identificacion_cbio}",)
    ).fetchone()
    return fila[0] if fila else ONCOLOGO_DEMO_ID


def registrar_consentimientos(
    conn_exp: sqlite3.Connection, conn_pac: sqlite3.Connection, cohorte: Sequence[Tuple[int, str]],
    demo: Sequence[str], fecha: date,
) -> Dict[int, str]:
    from privacidad import consentimiento_ia as sec03

    sec03.activar_consentimiento_ia(conn_exp, IDS["adm.clinico"], ahora=_momento(fecha, 120))
    casos: Dict[int, str] = {}
    otros = [c for c in cohorte if c[1] not in demo]
    for paciente_id, cbio in cohorte:
        casos[paciente_id] = OTORGADO if cbio in demo else caso_consentimiento(otros.index((paciente_id, cbio)))
    for n, (paciente_id, cbio) in enumerate(cohorte):
        caso, quien = casos[paciente_id], oncologo_de(conn_pac, cbio)
        soporte = f"consentimiento-ia-{cbio}.pdf"
        if caso == PENDIENTE:
            continue
        if caso == RECHAZADO:
            sec03.registrar_consentimiento_ia(conn_exp, ADMINISTRATIVO_ID, paciente_id, medio="escrito",
                                              soporte=f"no-consentimiento-{cbio}.pdf", otorgado=False,
                                              ahora=_momento(fecha, 60 - n % 30))
            continue
        sec03.registrar_consentimiento_ia(conn_exp, quien, paciente_id, medio="escrito", soporte=soporte,
                                          ahora=_momento(fecha, 90 - n % 30))
        if caso in (RETIRADO, REOTORGADO):
            sec03.retirar_consentimiento_ia(conn_exp, quien, paciente_id, medio="escrito",
                                            soporte=f"retiro-consentimiento-{cbio}.pdf", ahora=_momento(fecha, 40 - n % 20))
        if caso == REOTORGADO:
            sec03.registrar_consentimiento_ia(conn_exp, quien, paciente_id, medio="digital",
                                              soporte=f"consentimiento-ia-{cbio}-v2.pdf", ahora=_momento(fecha, 10))
    return casos


def registrar_autorizaciones_investigacion(
    conn_exp: sqlite3.Connection, cohorte: Sequence[Tuple[int, str]], fecha: date
) -> Dict[str, int]:
    from privacidad.models import EstadoAutorizacion, Finalidad
    from privacidad.tratamiento_datos import configurar_politica, registrar_autorizacion

    configurar_politica(
        conn_exp, IDS["adm.clinico"], codigo=POLITICA_DATOS, jurisdiccion="Colombia",
        nombre="Política de tratamiento de datos de pacientes",
        marco_normativo="Definido por la institución (p. ej. Ley 1581 de 2012)",
        finalidades=(Finalidad("atencion_clinica", "Prestación del servicio de salud", False),
                     Finalidad("investigacion", "Uso de datos seudonimizados en investigación", True)),
        bases_legales=("autorizacion_titular", "prestacion_servicio_salud"),
        derechos=("acceso", "rectificacion", "supresion", "revocacion"),
        plazo_respuesta_dias=15, ahora=_momento(fecha, 120),
    )
    conteo = Counter()
    for n, (paciente_id, cbio) in enumerate(cohorte):
        if n % 4 != 0:
            continue
        registrar_autorizacion(conn_exp, ADMINISTRATIVO_ID, paciente_id=paciente_id, codigo_politica=POLITICA_DATOS,
                               finalidad="investigacion", base_legal="autorizacion_titular", medio="escrito",
                               evidencia_ref=f"autorizacion-investigacion-{cbio}.pdf", ahora=_momento(fecha, 80))
        if n % 12 == 0:
            registrar_autorizacion(conn_exp, ADMINISTRATIVO_ID, paciente_id=paciente_id, codigo_politica=POLITICA_DATOS,
                                   finalidad="investigacion", base_legal="autorizacion_titular",
                                   estado=EstadoAutorizacion.REVOCADA, ahora=_momento(fecha, 20))
            conteo["revocada"] += 1
        else:
            conteo["otorgada"] += 1
    return dict(conteo)


def texto_de_revision(conn_exp: sqlite3.Connection, paciente_id: int) -> Optional[str]:
    """Lo que el expediente ya tiene del paciente, en una nota de revisión. Sin datos nuevos."""
    paciente = conn_exp.execute("SELECT diagnostico_principal, estadio FROM pacientes WHERE id = ?", (paciente_id,)).fetchone()
    if paciente is None:
        return None
    partes = ["Revisión del expediente importado de cBioPortal."]
    if paciente[0]:
        partes.append(f"Diagnóstico registrado: {paciente[0]}" + (f", estadio {paciente[1]}." if paciente[1] else "."))
    marcadores = conn_exp.execute(
        "SELECT biomarcador, resultado FROM biomarcadores WHERE paciente_id = ? AND resultado LIKE 'mutación detectada%' "
        "ORDER BY fecha DESC LIMIT 3", (paciente_id,),
    ).fetchall()
    if marcadores:
        partes.append("Alteraciones en el panel: " + "; ".join(f"{b} {r.split('·')[0].strip()}" for b, r in marcadores) + ".")
    labs = conn_exp.execute(
        "SELECT prueba, valor, unidad, fecha FROM laboratorios WHERE paciente_id = ? ORDER BY fecha DESC LIMIT 2", (paciente_id,)
    ).fetchall()
    if labs:
        partes.append("Últimos laboratorios: " + "; ".join(f"{p} {v}{' ' + u if u else ''} ({f})" for p, v, u, f in labs) + ".")
    imagen = conn_exp.execute(
        "SELECT modalidad, region, fecha FROM imagenologia WHERE paciente_id = ? ORDER BY fecha DESC LIMIT 1", (paciente_id,)
    ).fetchone()
    if imagen:
        partes.append(f"Último estudio de imagen: {imagen[0]}, región {imagen[1]} ({imagen[2]}).")
    partes.append("Pendiente valorar en consulta el estado funcional y la línea de tratamiento.")
    return " ".join(partes)


def registrar_consultas_de_revision(
    conn_exp: sqlite3.Connection, cohorte: Sequence[Tuple[int, str]], demo: Sequence[str], fecha: date
) -> int:
    from expediente.registro import registrar_consulta

    hechas = 0
    for paciente_id, cbio in cohorte:
        if cbio in demo:
            continue  # en la demo unificada el oncólogo registra la consulta en vivo
        texto = texto_de_revision(conn_exp, paciente_id)
        if texto:
            registrar_consulta(conn_exp, paciente_id, "Revisión del expediente (escenario de demostración)", texto,
                               fecha=fecha - timedelta(days=7))
            hechas += 1
    return hechas


# ---------------------------------------------------------------------------


#: Equipo de atención del escenario: enfermería y admisiones trabajan con la Dra. Gómez.
EQUIPOS = {"enf.mora": ("dra.gomez",), "adm.lopez": ("dra.gomez",)}

#: Órdenes médicas de demostración (inventadas, como las consultas de revisión): lo que enfermería ve en su horario.
#: (paciente de cBioPortal, [(medicamento, dosis, vía, horas entre dosis, hora de inicio, días desde el inicio, indicaciones)])
ORDENES_DEMO = (
    ("P-0006895", [("Pembrolizumab", "200 mg", "IV", 504, "09:00", 0, "Diluir en 100 ml de SSN 0,9 %; pasar en 30 minutos. Orden de demostración del escenario."),
                   ("Ondansetrón", "8 mg", "VO", 8, "08:00", 0, "Antiemético. Orden de demostración del escenario."),
                   ("Dexametasona", "4 mg", "VO", 12, "08:00", 0, "Con alimentos, durante 3 días. Orden de demostración del escenario.")]),
    ("P-0008538", [("Capecitabina", "1000 mg/m²", "VO", 12, "08:00", 0, "Dentro de los 30 minutos después de comer. Orden de demostración del escenario."),
                   ("Metoclopramida", "10 mg", "VO", 8, "07:00", 0, "Antes de las comidas, si hay náuseas. Orden de demostración del escenario.")]),
)


def asegurar_equipos(conn_usuarios: sqlite3.Connection) -> int:
    """Asigna el equipo del escenario si todavía no hay ninguno (idempotente: no toca lo que el administrador ya armó)."""
    from administracion import equipo

    equipo.inicializar_esquema(conn_usuarios)
    if conn_usuarios.execute("SELECT 1 FROM equipo_atencion LIMIT 1").fetchone():
        return 0
    ids = {f[1]: f[0] for f in conn_usuarios.execute("SELECT id, nombre_usuario FROM usuarios")}
    admin = conn_usuarios.execute("SELECT id, nombre_usuario FROM usuarios WHERE rol = ? AND activo = 1 ORDER BY id LIMIT 1",
                                  (Rol.ADMINISTRADOR.value,)).fetchone()
    if admin is None:
        return 0
    actor = Usuario(admin[0], admin[1], Rol.ADMINISTRADOR, True)
    asignadas = 0
    for persona, oncologos in EQUIPOS.items():
        for oncologo in oncologos:
            if persona in ids and oncologo in ids:
                equipo.asignar(conn_usuarios, actor, ids[persona], ids[oncologo])
                asignadas += 1
    return asignadas


def asegurar_ordenes_demo(conn_exp: sqlite3.Connection, conn_pac: sqlite3.Connection, fecha: Optional[date] = None) -> int:
    """Las órdenes de demostración, si el expediente todavía no tiene ninguna orden médica (idempotente)."""
    from historia_clinica import ordenes_medicas as om
    from patients.expediente import paciente_en_expediente

    om.inicializar_esquema(conn_exp)
    if conn_exp.execute("SELECT 1 FROM ordenes_medicamento LIMIT 1").fetchone():
        return 0
    fecha = fecha or date.today()
    creadas = 0
    for cbio, ordenes in ORDENES_DEMO:
        fila = conn_pac.execute("SELECT id FROM pacientes WHERE numero_identificacion LIKE ?", (f"%:{cbio}",)).fetchone()
        eid = paciente_en_expediente(conn_pac, conn_exp, fila[0], crear=False) if fila else None
        if eid is None:
            continue
        for medicamento, dosis, via, intervalo, hora, dias, indicaciones in ordenes:
            om.prescribir(conn_exp, eid, medicamento=medicamento, dosis=dosis, via=via, intervalo_horas=intervalo,
                          fecha_inicio=(fecha - timedelta(days=dias)).isoformat(), hora_inicio=hora, indicaciones=indicaciones,
                          ordenado_por="Dra. Ana Gómez (dra.gomez)")
            creadas += 1
    return creadas


def asegurar_equipo_y_ordenes(rutas) -> Tuple[int, int]:
    """Para capas de trabajo armadas antes de existir el equipo de atención y las órdenes médicas."""
    from administracion import usuarios as adm
    from historia_clinica.db import conectar_expediente
    from patients import db as db_pacientes

    conn_usu = adm.crear_conexion(str(rutas.usuarios))
    conn_exp = conectar_expediente(rutas.expediente)
    conn_pac = db_pacientes.conectar(rutas.pacientes)
    try:
        return asegurar_equipos(conn_usu), asegurar_ordenes_demo(conn_exp, conn_pac)
    finally:
        conn_usu.close()
        conn_exp.close()
        conn_pac.close()


def aplicar_escenario(rutas, fecha_referencia: Optional[date] = None, demo: Sequence[str] = None) -> ResumenEscenario:
    """Aplica el escenario sobre una capa de trabajo recién copiada de la base."""
    from administracion import usuarios as adm
    from datos.capas import PACIENTES_DEMO
    from historia_clinica.db import conectar_expediente
    from patients import db as db_pacientes

    demo = tuple(demo if demo is not None else PACIENTES_DEMO)
    fecha = fecha_referencia or date.today()
    resumen = ResumenEscenario(aplicado_en=datetime.now(timezone.utc).isoformat())
    conn_exp = conectar_expediente(rutas.expediente)
    conn_pac = db_pacientes.conectar(rutas.pacientes)
    conn_usu = adm.crear_conexion(str(rutas.usuarios))
    try:
        if version_aplicada(conn_exp) is not None:
            raise RuntimeError("El escenario ya está aplicado en esta capa de trabajo (use python -m datos reiniciar).")
        db_pacientes.inicializar(conn_pac)
        resumen.usuarios = crear_usuarios(conn_usu)
        resumen.pacientes_por_oncologo = repartir_pacientes(conn_pac, demo)
        cohorte = cohorte_con_detalle(conn_exp)
        resumen.cohorte = len(cohorte)
        casos = registrar_consentimientos(conn_exp, conn_pac, cohorte, demo, fecha)
        resumen.consentimientos = dict(Counter(casos.values()))
        resumen.investigacion = registrar_autorizaciones_investigacion(conn_exp, cohorte, fecha)
        resumen.consultas_de_revision = registrar_consultas_de_revision(conn_exp, cohorte, demo, fecha)
        asegurar_equipos(conn_usu)
        asegurar_ordenes_demo(conn_exp, conn_pac, fecha)
        conn_exp.execute(
            "CREATE TABLE IF NOT EXISTS escenario_copiloto (version INTEGER PRIMARY KEY, aplicado_en TEXT NOT NULL, resumen_json TEXT NOT NULL)"
        )
        conn_exp.execute("INSERT INTO escenario_copiloto VALUES (?, ?, ?)",
                         (VERSION, resumen.aplicado_en, json.dumps(resumen.a_dict(), ensure_ascii=False, default=str)))
        conn_exp.commit()
    finally:
        conn_exp.close()
        conn_pac.close()
        conn_usu.close()
    return resumen
