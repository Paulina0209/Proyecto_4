"""Datos de prueba de ADM-02: una "institución" con usuarios, accesos, decisiones y alertas.

Cada pieza vive en una base de archivo distinta (usuarios / accesos como los guarda la
API de pacientes / expediente), como en el sistema real, para probar que las métricas
suman bien entre bases. Los esquemas son los reales (los archivos .sql del sistema).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from administracion import usuarios as adm
from administracion.metricas_uso import FuentesMetricas
from auditoria.models import TipoAccion
from auditoria.registro_acceso import crear_conexion as crear_accesos
from auditoria.registro_acceso import registrar_acceso
from clinical_decision.registro import inicializar_schema as inicializar_decisiones
from historia_clinica.db import crear_conexion as crear_expediente
from seguridad.models import Rol, Usuario

RAIZ = Path(__file__).resolve().parents[2]
CLAVE = "Cl1nic@2026"
CLAVE_ADMIN = "Adm1n-Inicial"
#: "Hoy" de las pruebas. Periodo por defecto: 2026-09-18 .. 2026-10-17; el anterior: 2026-08-19 .. 2026-09-17.
AHORA = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _hash_rapido(monkeypatch):
    monkeypatch.setattr("seguridad.autenticacion._ITERACIONES_PBKDF2", 1_000)


def _momento(dia: str, hora: int = 10) -> str:
    return datetime.fromisoformat(dia).replace(hour=hora, tzinfo=timezone.utc).isoformat()


class Mundo:
    def __init__(self, carpeta: Path):
        self.ruta_usuarios = carpeta / "usuarios.db"
        self.ruta_accesos = carpeta / "pacientes.db"
        self.ruta_expediente = carpeta / "expediente.db"
        self.usuarios = adm.crear_conexion(str(self.ruta_usuarios), check_same_thread=False)
        self.accesos = crear_accesos(str(self.ruta_accesos))
        self.expediente = crear_expediente(str(self.ruta_expediente))
        self.expediente.execute("PRAGMA foreign_keys = OFF")
        inicializar_decisiones(self.expediente)
        for sql in ("estadificacion/schema_confirmacion_estadio.sql", "dx_clinica/schema_juicio_clinico.sql", "ia_clinica/review/schema.sql"):
            self.expediente.executescript((RAIZ / sql).read_text(encoding="utf-8"))
        adm.crear_primer_administrador(self.usuarios, "admin.sistema", CLAVE_ADMIN, "Administrador del Sistema")
        self.admin = Usuario(1, "admin.sistema", Rol.ADMINISTRADOR, True)
        self.nombres: dict[int, str] = {1: "admin.sistema"}
        self._n_alertas = 0

    # --- usuarios -------------------------------------------------------------
    def usuario(self, nombre: str, rol: Rol) -> Usuario:
        creado = adm.crear_usuario(self.usuarios, self.admin, nombre, CLAVE, rol.value, f"Persona {nombre}", f"{nombre}@hospital.org")
        self.nombres[creado.id] = nombre
        return Usuario(creado.id, nombre, rol, True)

    def equipo(self, oncologos: int = 5, enfermeria: int = 5):
        """Cuentas clínicas + un director médico y un auditor. Devuelve (oncologos, enfermeria)."""
        self.director = self.usuario("direccion.medica", Rol.DIRECTOR_MEDICO)
        self.auditor = self.usuario("auditor.uno", Rol.AUDITOR)
        self.oncologos = [self.usuario(f"onco.{i + 1:02d}", Rol.ONCOLOGO) for i in range(oncologos)]
        self.enfermeras = [self.usuario(f"enf.{i + 1:02d}", Rol.ENFERMERIA) for i in range(enfermeria)]
        return self.oncologos, self.enfermeras

    # --- eventos --------------------------------------------------------------
    def acceso(self, quien, dia: str, accion: TipoAccion = TipoAccion.VER, paciente: int = 1, veces: int = 1) -> None:
        uid = quien.id if hasattr(quien, "id") else quien
        for _ in range(veces):
            registrar_acceso(self.accesos, uid, accion, paciente_id=paciente, ahora=datetime.fromisoformat(_momento(dia)))

    def decision(self, oncologo, dia: str, tipo: str = "accept", sugerido: str = "FOLFOX", final: str | None = "FOLFOX") -> None:
        self.expediente.execute(
            "INSERT INTO decisiones_tratamiento (paciente_id, oncologo_id, fecha, tipo_decision, regimen_sugerido_id, regimen_final_id, "
            "motivo_rechazo, recomendacion_ia_snapshot) VALUES (1,?,?,?,?,?,?, '{}')",
            (oncologo.id, _momento(dia), tipo, sugerido, final, "motivo" if tipo == "reject" else None))
        self.expediente.commit()

    def estadificacion(self, autor: str, dia: str, difiere: int = 0, disponible: int = 1) -> None:
        self.expediente.execute(
            "INSERT INTO confirmaciones_estadificacion (paciente_id, estadio_confirmado, autor, registrado_en, difiere_de_sugerencia, sugerencia_disponible) "
            "VALUES (1,'IIA',?,?,?,?)", (autor, _momento(dia), difiere, disponible))
        self.expediente.commit()

    def alerta(self, dia: str, severidad: str = "critica", estado: str = "activa") -> None:
        self._n_alertas += 1
        self.expediente.execute(
            "INSERT INTO alertas_laboratorio (paciente_id, laboratorio_id, prueba, valor, limite_superado, severidad, estado, fecha) "
            "VALUES (1,?, 'Potasio','2.1','< 2.5', ?, ?, ?)", (self._n_alertas, severidad, estado, dia))
        self.expediente.commit()

    def conflicto(self, dia: str, estado: str = "pendiente") -> None:
        self._n_alertas += 1
        self.expediente.execute(
            "INSERT INTO conflictos_laboratorio (paciente_id, prueba_normalizada, momento, laboratorio_a_id, laboratorio_b_id, estado, fecha_deteccion) "
            "VALUES (1,'hemoglobina','x',?,?,?,?)", (self._n_alertas, self._n_alertas + 5000, estado, dia))
        self.expediente.commit()

    def sincronizacion(self, dia: str, estado: str = "exitosa") -> None:
        self.expediente.execute(
            "INSERT INTO sincronizaciones_externas (paciente_id, fuente, formato, estado, fecha) VALUES (1,'lab','fhir',?,?)", (estado, _momento(dia)))
        self.expediente.commit()

    def nota_aprobada(self, dia: str, n: int = 1) -> None:
        for _ in range(n):
            self._n_alertas += 1
            self.expediente.execute(
                "INSERT INTO revision_notas (nota_id, paciente_ref, contenido_ia_original, contenido_actual, estado, creado_en, aprobado_por, aprobado_en) "
                "VALUES (?, 'P', '{}', '{}', 'APPROVED', ?, 'x', ?)", (f"n{self._n_alertas}", _momento(dia), _momento(dia)))
        self.expediente.commit()

    # --- fuentes --------------------------------------------------------------
    def fuentes(self, *, con_accesos: bool = True, con_expediente: bool = True) -> FuentesMetricas:
        otras = ([self.accesos] if con_accesos else []) + ([self.expediente] if con_expediente else [])
        return FuentesMetricas(self.usuarios, otras)

    def cerrar(self) -> None:
        for c in (self.usuarios, self.accesos, self.expediente):
            try:
                c.close()
            except sqlite3.Error:
                pass


@pytest.fixture()
def mundo(tmp_path):
    m = Mundo(tmp_path)
    yield m
    m.cerrar()
