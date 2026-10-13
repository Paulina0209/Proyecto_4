"""NFR-04 — Cumplimiento normativo (HIPAA / GDPR / norma local).

Como institución, quiero que los datos personales y clínicos se manejen con
controles de privacidad y seguridad alineados con la normativa aplicable,
para proteger la información sensible de los pacientes durante su
almacenamiento, procesamiento y transmisión.

Ningún control nuevo vive aquí: NFR-04 integra los de SEC-01, SEC-02, SEC-03
y AUD-01 (nota técnica de la historia). Este módulo los *verifica* contra una
instalación concreta y produce un informe, uno por criterio de aceptación:

    AC1  almacenamiento   clave AES-256 configurada; documentos cifrados en disco
    AC2  transmisión      certificado TLS válido; APIs solo HTTPS; integraciones HTTPS
    AC3  acceso           cada acción con roles explícitos (fail-closed); el
                          administrador del sistema sin acceso clínico
    AC4  trazabilidad     auditoría (AUD-01) de solo inserción
    AC5  contexto de IA   consentimiento exigido (SEC-03) y sin identificadores
                          directos en lo que se envía al modelo

    python -m privacidad.cumplimiento            # sobre la instalación real
    python -m privacidad.cumplimiento --json

La normativa concreta la define la institución (ver NFR-06): el informe dice
qué controles técnicos están activos, no certifica cumplimiento legal.
Ver docs/cumplimiento_normativo.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import ssl
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, List, Optional, Sequence


class Estado(str, Enum):
    CUMPLE = "cumple"
    ATENCION = "atención"
    FALLA = "falla"


@dataclass(frozen=True)
class Control:
    criterio: str  # AC1 ... AC5
    nombre: str
    estado: Estado
    detalle: str


@dataclass(frozen=True)
class InformeCumplimiento:
    generado_en: str
    controles: tuple[Control, ...]

    @property
    def estado_general(self) -> Estado:
        estados = {c.estado for c in self.controles}
        if Estado.FALLA in estados:
            return Estado.FALLA
        return Estado.ATENCION if Estado.ATENCION in estados else Estado.CUMPLE

    def a_json(self) -> str:
        return json.dumps(
            {
                "generado_en": self.generado_en,
                "estado_general": self.estado_general.value,
                "controles": [asdict(c) | {"estado": c.estado.value} for c in self.controles],
            },
            ensure_ascii=False,
            indent=2,
        )

    def a_texto(self) -> str:
        simbolo = {Estado.CUMPLE: "✔", Estado.ATENCION: "!", Estado.FALLA: "✘"}
        lineas = [f"Informe de cumplimiento NFR-04 — {self.generado_en[:19]}", ""]
        for c in self.controles:
            lineas.append(f"  {simbolo[c.estado]} [{c.criterio}] {c.nombre}: {c.estado.value}")
            lineas.append(f"      {c.detalle}")
        lineas += ["", f"  Estado general: {self.estado_general.value}"]
        return "\n".join(lineas)


# ---------------------------------------------------------------------------
# AC1 — Almacenamiento
# ---------------------------------------------------------------------------


def control_clave_cifrado() -> Control:
    from seguridad.cifrado import ENV_CLAVE, ErrorCifrado, cifrador_configurado

    nombre = "Clave de cifrado en reposo (AES-256-GCM)"
    try:
        cifrador = cifrador_configurado(crear_si_falta=False)
    except ErrorCifrado as exc:
        return Control("AC1", nombre, Estado.FALLA, f"{exc} Los documentos nuevos no se podrían cifrar.")
    if cifrador.origen.startswith("variable"):
        return Control("AC1", nombre, Estado.CUMPLE, f"Clave tomada de {ENV_CLAVE} (gestor de secretos).")
    return Control(
        "AC1", nombre, Estado.ATENCION,
        f"Clave en {cifrador.origen.removeprefix('archivo ')}. Sirve en desarrollo; en producción "
        f"debe inyectarse con {ENV_CLAVE} desde el gestor de secretos de la institución.",
    )


def control_documentos_cifrados(conn_documentos: Optional[sqlite3.Connection]) -> Control:
    from seguridad.cifrado import esta_cifrado

    nombre = "Documentos clínicos cifrados en disco (DOC-01)"
    if conn_documentos is None:
        return Control("AC1", nombre, Estado.ATENCION, "No se indicó la base de documentos: no se revisó.")
    existe = conn_documentos.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'documentos_clinicos_cargados'"
    ).fetchone()
    rutas = [f[0] for f in conn_documentos.execute("SELECT ruta_almacenamiento FROM documentos_clinicos_cargados")] if existe else []
    en_claro = [r for r in rutas if Path(r).is_file() and not esta_cifrado(Path(r).read_bytes())]
    if en_claro:
        return Control(
            "AC1", nombre, Estado.FALLA,
            f"{len(en_claro)} de {len(rutas)} documento(s) siguen en claro (cargados antes de SEC-02); p. ej. {en_claro[0]}.",
        )
    return Control("AC1", nombre, Estado.CUMPLE, f"{len(rutas)} documento(s) revisados, todos cifrados.")


# ---------------------------------------------------------------------------
# AC2 — Transmisión
# ---------------------------------------------------------------------------


def control_certificado_tls(ahora: Optional[datetime] = None) -> Control:
    from seguridad.servidor_tls import ENV_CERT, ENV_KEY
    from seguridad.tls import contexto_tls_servidor

    nombre = "Certificado TLS del servidor"
    cert, clave = os.environ.get(ENV_CERT), os.environ.get(ENV_KEY)
    if not cert or not clave:
        return Control("AC2", nombre, Estado.FALLA, f"Sin {ENV_CERT}/{ENV_KEY}: la API no puede servirse (no hay respaldo en HTTP).")
    try:
        contexto_tls_servidor(cert, clave)
        from cryptography import x509

        vence = x509.load_pem_x509_certificate(Path(cert).read_bytes()).not_valid_after_utc
    except (OSError, ssl.SSLError, ValueError) as exc:
        return Control("AC2", nombre, Estado.FALLA, f"El certificado o la clave no se pueden usar: {exc}")
    restante = vence - (ahora or datetime.now(timezone.utc))
    if restante <= timedelta(0):
        return Control("AC2", nombre, Estado.FALLA, f"El certificado venció el {vence.date()}.")
    if restante < timedelta(days=30):
        return Control("AC2", nombre, Estado.ATENCION, f"El certificado vence el {vence.date()} (menos de 30 días).")
    return Control("AC2", nombre, Estado.CUMPLE, f"TLS 1.2 como mínimo; certificado válido hasta {vence.date()}.")


def control_apis_solo_https() -> Control:
    import administracion.api
    import patients.api
    from seguridad.tls import SoloHTTPSMiddleware

    sin = [
        nombre for nombre, app in (("patients.api", patients.api.app), ("administracion.api", administracion.api.app))
        if not any(m.cls is SoloHTTPSMiddleware for m in app.user_middleware)
    ]
    if sin:
        return Control("AC2", "APIs solo HTTPS", Estado.FALLA, f"Sin SoloHTTPSMiddleware: {', '.join(sin)}.")
    return Control("AC2", "APIs solo HTTPS", Estado.CUMPLE, "patients.api y administracion.api rechazan HTTP (403) y envían HSTS.")


def control_integraciones_https() -> Control:
    from historia_clinica.imagenes_pacs import ENV_PACS_URL, ENV_VISOR_URL
    from seguridad.tls import ConexionInseguraError, exigir_url_segura

    nombre = "Integraciones salientes por HTTPS"
    problemas, revisadas = [], []
    for variable in (ENV_PACS_URL, ENV_VISOR_URL, "OPENAI_BASE_URL", "LANGFUSE_HOST"):
        valor = (os.environ.get(variable) or "").strip()
        if not valor:
            continue
        revisadas.append(variable)
        try:
            exigir_url_segura(valor.replace("{study_uid}", "0"), que=variable)
        except ConexionInseguraError as exc:
            problemas.append(str(exc))
    if problemas:
        return Control("AC2", nombre, Estado.FALLA, " ".join(problemas))
    detalle = f"Revisadas: {', '.join(revisadas)}." if revisadas else "Sin integraciones configuradas por entorno."
    return Control("AC2", nombre, Estado.CUMPLE, detalle + " cBioPortal y OpenAI van por HTTPS.")


# ---------------------------------------------------------------------------
# AC3 — Acceso
# ---------------------------------------------------------------------------

#: Acciones que dan acceso a datos clínicos de pacientes.
_ACCIONES_CLINICAS = (
    "CONFIRMAR_TRATAMIENTO", "CONFIRMAR_ESTADIFICACION", "REGISTRAR_JUICIO_DIAGNOSTICO",
    "VER_EXPEDIENTE", "EDITAR_EXPEDIENTE", "EXPORTAR_EXPEDIENTE", "REGISTRAR_CONSENTIMIENTO_IA",
)


def control_permisos_por_rol() -> Control:
    from seguridad.autorizacion import PERMISOS_POR_ROL, Accion
    from seguridad.models import Rol

    nombre = "Acceso por identidad, rol y permiso (SEC-01)"
    sin_roles = [a.value for a in Accion if not PERMISOS_POR_ROL.get(a)]
    if sin_roles:
        return Control("AC3", nombre, Estado.ATENCION, f"Acciones sin ningún rol (nadie puede ejecutarlas): {', '.join(sin_roles)}.")
    clinicas_admin = [a for a in _ACCIONES_CLINICAS if Rol.ADMINISTRADOR in PERMISOS_POR_ROL[Accion[a]]]
    if clinicas_admin:
        return Control("AC3", nombre, Estado.FALLA, f"El administrador del sistema tiene acceso clínico: {', '.join(clinicas_admin)}.")
    return Control(
        "AC3", nombre, Estado.CUMPLE,
        f"{len(Accion)} acciones, cada una con roles explícitos; lo no listado se deniega. "
        "El administrador del sistema no tiene acceso clínico.",
    )


# ---------------------------------------------------------------------------
# AC4 — Trazabilidad
# ---------------------------------------------------------------------------


def control_auditoria(conn: Optional[sqlite3.Connection], nombre_base: str) -> Control:
    nombre = f"Auditoría de solo inserción (AUD-01) en {nombre_base}"
    if conn is None:
        return Control("AC4", nombre, Estado.ATENCION, "No se indicó la base: no se revisó.")
    triggers = {
        f[0] for f in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'eventos_acceso'")
    }
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'eventos_acceso'").fetchone():
        return Control("AC4", nombre, Estado.FALLA, "No existe la tabla eventos_acceso.")
    if not {"eventos_acceso_no_update", "eventos_acceso_no_delete"} <= triggers:
        return Control("AC4", nombre, Estado.FALLA, "eventos_acceso no está protegida contra modificación o borrado.")
    total = conn.execute("SELECT COUNT(*) FROM eventos_acceso").fetchone()[0]
    return Control("AC4", nombre, Estado.CUMPLE, f"{total} evento(s); la base impide modificarlos o borrarlos.")


# ---------------------------------------------------------------------------
# AC5 — Contexto enviado a la IA
# ---------------------------------------------------------------------------


def control_consentimiento_ia(conn_expediente: Optional[sqlite3.Connection]) -> Control:
    from privacidad.consentimiento_ia import CODIGO_POLITICA, FINALIDAD_IA, consentimiento_ia_activo

    nombre = "IA solo con consentimiento informado (SEC-03)"
    if conn_expediente is None:
        return Control("AC5", nombre, Estado.ATENCION, "No se indicó el expediente: no se revisó.")
    if not consentimiento_ia_activo(conn_expediente):
        return Control(
            "AC5", nombre, Estado.FALLA,
            "La exigencia de consentimiento no está activada en el expediente "
            "(python -m privacidad.consentimiento_ia activar).",
        )
    habilitados = conn_expediente.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT a.paciente_id, a.estado FROM autorizaciones_tratamiento a
            JOIN politicas_tratamiento p ON p.id = a.politica_id
            WHERE p.codigo = ? AND a.finalidad = ?
              AND a.id = (SELECT MAX(a2.id) FROM autorizaciones_tratamiento a2
                          JOIN politicas_tratamiento p2 ON p2.id = a2.politica_id
                          WHERE a2.paciente_id = a.paciente_id AND p2.codigo = ? AND a2.finalidad = ?)
        ) WHERE estado = 'otorgada'
        """,
        (CODIGO_POLITICA, FINALIDAD_IA, CODIGO_POLITICA, FINALIDAD_IA),
    ).fetchone()[0]
    total = conn_expediente.execute("SELECT COUNT(*) FROM pacientes").fetchone()[0]
    return Control(
        "AC5", nombre, Estado.CUMPLE,
        f"Activada. {habilitados} de {total} paciente(s) con consentimiento vigente; el resto queda sin IA.",
    )


def control_minimizacion() -> Control:
    """Comprueba con un caso sintético que lo que llega al modelo no trae identificadores."""
    from expediente.adapters import construir_contexto_clinico
    from expediente.db import crear_conexion
    from expediente.registro import registrar_consulta
    from ia_clinica.notes.llm_client import build_user_prompt

    nombre = "Minimización del contexto de IA"
    conn = crear_conexion()
    try:
        cursor = conn.execute(
            "INSERT INTO pacientes (nombre, fecha_nacimiento, sexo, identificacion) VALUES (?, ?, ?, ?)",
            ("Zoila Prueba Control", "1970-01-01", "femenino", "CC-99887766"),
        )
        consulta = registrar_consulta(
            conn, cursor.lastrowid, "Control",
            "Zoila Prueba refiere dolor. Documento CC-99887766, teléfono 300 123 4567, zoila@correo.example.",
        )
        prompt = build_user_prompt(construir_contexto_clinico(conn, consulta))
    finally:
        conn.close()
    filtrados = [t for t in ("Zoila", "Prueba", "99887766", "300 123 4567", "zoila@") if t in prompt]
    if filtrados:
        return Control("AC5", nombre, Estado.FALLA, f"El prompt de IA-02 contiene identificadores: {', '.join(filtrados)}.")
    return Control(
        "AC5", nombre, Estado.CUMPLE,
        "Nombre, documento, teléfono y correo del paciente no llegan al modelo (verificado con un caso sintético).",
    )


# ---------------------------------------------------------------------------


def evaluar_cumplimiento(
    conn_expediente: Optional[sqlite3.Connection] = None,
    conn_pacientes: Optional[sqlite3.Connection] = None,
    conn_documentos: Optional[sqlite3.Connection] = None,
    ahora: Optional[datetime] = None,
) -> InformeCumplimiento:
    controles: List[Callable[[], Control]] = [
        control_clave_cifrado,
        lambda: control_documentos_cifrados(conn_documentos),
        lambda: control_certificado_tls(ahora),
        control_apis_solo_https,
        control_integraciones_https,
        control_permisos_por_rol,
        lambda: control_auditoria(conn_expediente, "el expediente"),
        lambda: control_auditoria(conn_pacientes, "la base de pacientes"),
        lambda: control_consentimiento_ia(conn_expediente),
        control_minimizacion,
    ]
    momento = ahora or datetime.now(timezone.utc)
    return InformeCumplimiento(generado_en=momento.isoformat(), controles=tuple(c() for c in controles))


def main(argv: Optional[Sequence[str]] = None) -> int:
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    p = argparse.ArgumentParser(prog="python -m privacidad.cumplimiento", description="Informe de cumplimiento (NFR-04).")
    p.add_argument("--json", action="store_true", help="Salida en JSON.")
    p.add_argument("--documentos", type=Path, help="Base de DOC-01 a revisar (documentos cifrados).")
    args = p.parse_args(argv)

    from historia_clinica.db import ruta_expediente
    from patients import db as db_pacientes

    def abrir(ruta: Path) -> Optional[sqlite3.Connection]:
        if not Path(ruta).is_file():
            return None
        conn = sqlite3.connect(str(ruta))
        conn.row_factory = sqlite3.Row
        return conn

    conexiones = [abrir(ruta_expediente()), abrir(Path(db_pacientes.RUTA_DB)), abrir(args.documentos) if args.documentos else None]
    try:  # solo lectura: el informe no crea ni modifica nada en las bases
        informe = evaluar_cumplimiento(*conexiones)
    finally:
        for conn in conexiones:
            if conn is not None:
                conn.close()
    print(informe.a_json() if args.json else informe.a_texto())
    return 0 if informe.estado_general is not Estado.FALLA else 1


if __name__ == "__main__":
    sys.exit(main())
