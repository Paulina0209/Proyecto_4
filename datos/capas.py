"""Capa base (cBioPortal, intocable) y capa de trabajo (lo que usa el sistema).

La capa base se arma una vez desde cBioPortal:

    1. el índice de MSK-CHORD (13.159 pacientes de mama y pulmón, datos básicos);
    2. el detalle completo (laboratorios, biomarcadores, imágenes, tratamientos,
       episodios y biopsias de HC-04) de una COHORTE: los tres pacientes de la
       demo unificada y otros, mitad pulmón y mitad mama, elegidos de forma
       determinista. Así ningún paciente de la cohorte depende de internet
       cuando un médico lo abre (NFR-01).

La capa de trabajo es una copia de la base (con la API de backup de SQLite)
a la que se le aplica el escenario. Lo que el sistema registre después
(consultas, decisiones, consentimientos) queda solo en la capa de trabajo:
``reiniciar`` lo descarta y vuelve a empezar desde la base.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

RAIZ = Path(__file__).resolve().parent.parent
#: ``COPILOTO_CAPA_BASE`` la cambia (pruebas, o una base en otro disco).
CARPETA_BASE = Path(os.environ.get("COPILOTO_CAPA_BASE") or RAIZ / "data" / "cbioportal")
BASE_EXPEDIENTE = CARPETA_BASE / "copiloto.db"
BASE_PACIENTES = CARPETA_BASE / "pacientes.db"

ESTUDIO = "msk_chord_2024"
#: Pacientes de la demo unificada (demo.py): siempre en la cohorte.
PACIENTES_DEMO = ("P-0012063", "P-0016350", "P-0008538")
TAMANO_COHORTE = 60
#: Oncólogo al que el índice asigna los pacientes al importarlos (el escenario los reparte después).
ONCOLOGO_IMPORTACION = 1


@dataclass(frozen=True)
class RutasTrabajo:
    expediente: Path
    pacientes: Path
    usuarios: Path

    @classmethod
    def por_defecto(cls) -> "RutasTrabajo":
        """Las rutas que usa el sistema (respetan ``COPILOTO_EXPEDIENTE_DB``,
        ``COPILOTO_PACIENTES_DB`` y ``COPILOTO_USUARIOS_DB``)."""
        import os

        from historia_clinica.db import ruta_expediente
        from patients import db

        usuarios = os.environ.get("COPILOTO_USUARIOS_DB") or RAIZ / "data" / "usuarios.db"
        return cls(Path(ruta_expediente()), Path(db.RUTA_DB), Path(usuarios))

    def todas(self) -> List[Path]:
        return [self.expediente, self.pacientes, self.usuarios]


@dataclass
class ResultadoBase:
    pacientes_indice: int = 0
    cohorte: List[str] = field(default_factory=list)
    detalle_cargado: List[str] = field(default_factory=list)
    detalle_fallido: Dict[str, str] = field(default_factory=dict)


def copiar_base_sqlite(origen: Path, destino: Path) -> None:
    """Copia consistente (aunque la base esté abierta) y sin archivos WAL a medias."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    for sufijo in ("", "-wal", "-shm"):
        Path(f"{destino}{sufijo}").unlink(missing_ok=True)
    with contextlib.closing(sqlite3.connect(str(origen))) as fuente, contextlib.closing(sqlite3.connect(str(destino))) as copia:
        fuente.backup(copia)


def base_existe() -> bool:
    return BASE_EXPEDIENTE.is_file() and BASE_PACIENTES.is_file()


def trabajo_existe(rutas: RutasTrabajo) -> bool:
    return all(r.is_file() for r in rutas.todas())


# ---------------------------------------------------------------------------
# Capa base
# ---------------------------------------------------------------------------


def elegir_cohorte(conn_pacientes: sqlite3.Connection, tamano: int = TAMANO_COHORTE) -> List[str]:
    """Los pacientes de la demo y, hasta ``tamano``, mitad pulmón y mitad mama,
    repartidos a lo largo del índice (cada k-ésimo id, siempre los mismos)."""
    elegidos = list(PACIENTES_DEMO)
    restantes = max(0, tamano - len(elegidos))
    for patron, cuantos in (("%lung%", restantes - restantes // 2), ("%breast%", restantes // 2)):
        filas = [
            f[0].rsplit(":", 1)[-1]
            for f in conn_pacientes.execute(
                "SELECT p.numero_identificacion FROM pacientes p JOIN diagnosticos d ON d.paciente_id = p.id "
                "WHERE p.tipo_identificacion = 'externo' AND lower(d.descripcion) LIKE ? GROUP BY p.id ORDER BY p.id",
                (patron,),
            )
        ]
        candidatos = [f for f in filas if f not in elegidos]
        paso = max(1, len(candidatos) // max(1, cuantos))
        elegidos += candidatos[::paso][:cuantos]
    return elegidos


def construir_base(
    cliente=None,
    tamano_cohorte: int = TAMANO_COHORTE,
    fecha_referencia: Optional[date] = None,
    aviso: Callable[[str], None] = print,
) -> ResultadoBase:
    """Arma la capa base desde cBioPortal (necesita internet). Re-ejecutarlo
    completa lo que falte: el índice solo agrega pacientes nuevos y el detalle
    solo se trae para los de la cohorte que todavía no lo tienen."""
    from cbioportal import ClienteCBioPortal, identificacion_cbioportal, importar_indice
    from cbioportal.importador import TIPOS_POR_DEFECTO, FuenteCBioPortal, importar_paciente
    from cbioportal.indice import detalle_cargado, fecha_referencia_de
    from cbioportal.modulo_pacientes import agregar_detalle
    from historia_clinica.db import crear_conexion
    from patients import db as db_pacientes

    cliente = cliente or ClienteCBioPortal()
    CARPETA_BASE.mkdir(parents=True, exist_ok=True)
    resultado = ResultadoBase()
    conn_exp = crear_conexion(str(BASE_EXPEDIENTE))
    conn_pac = db_pacientes.conectar(BASE_PACIENTES)
    db_pacientes.inicializar(conn_pac)
    try:
        aviso("  Índice de MSK-CHORD (mama y pulmón) desde cBioPortal...")
        indice = importar_indice(conn_exp, conn_pac, cliente, ESTUDIO, ONCOLOGO_IMPORTACION,
                                 fecha_referencia or date.today(), TIPOS_POR_DEFECTO, None)
        resultado.pacientes_indice = conn_pac.execute("SELECT COUNT(*) FROM pacientes").fetchone()[0]
        aviso(f"  {resultado.pacientes_indice} pacientes en el índice ({indice.pacientes} nuevos).")

        resultado.cohorte = elegir_cohorte(conn_pac, tamano_cohorte)
        fecha = fecha_referencia_de(conn_exp, ESTUDIO) or date.today()
        fuente = FuenteCBioPortal(cliente, fecha)
        pendientes = [p for p in resultado.cohorte if not detalle_cargado(conn_exp, identificacion_cbioportal(ESTUDIO, p))]
        aviso(f"  Cohorte de {len(resultado.cohorte)} pacientes con detalle completo; faltan {len(pendientes)}.")
        for numero, paciente in enumerate(pendientes, 1):
            identificacion = identificacion_cbioportal(ESTUDIO, paciente)
            importado = importar_paciente(conn_exp, fuente, ESTUDIO, paciente)
            if importado.sincronizacion.exito and importado.contenido is not None:
                fila = conn_pac.execute("SELECT id FROM pacientes WHERE numero_identificacion = ?", (identificacion,)).fetchone()
                if fila is not None:
                    agregar_detalle(conn_pac, fila[0], importado, fecha)
                resultado.detalle_cargado.append(paciente)
            else:
                resultado.detalle_fallido[paciente] = importado.sincronizacion.mensaje or "sin detalle"
            if numero % 10 == 0 or numero == len(pendientes):
                aviso(f"    {numero}/{len(pendientes)} pacientes traídos")
    finally:
        conn_exp.close()
        conn_pac.close()
    return resultado


def adoptar_como_base(expediente: Path, pacientes: Path) -> None:
    """Sin internet: toma unas bases existentes (las de antes de separar capas) como base."""
    copiar_base_sqlite(expediente, BASE_EXPEDIENTE)
    copiar_base_sqlite(pacientes, BASE_PACIENTES)


# ---------------------------------------------------------------------------
# Capa de trabajo
# ---------------------------------------------------------------------------


def respaldar(rutas: RutasTrabajo, momento: Optional[datetime] = None) -> Optional[Path]:
    """Copia la capa de trabajo actual a ``respaldo_<fecha>/`` junto al expediente (``data/``)."""
    existentes = [r for r in rutas.todas() if r.is_file()]
    if not existentes:
        return None
    carpeta = rutas.expediente.parent / f"respaldo_{(momento or datetime.now()):%Y%m%d_%H%M%S}"
    carpeta.mkdir(parents=True, exist_ok=True)
    for ruta in existentes:
        destino = carpeta / f"{ruta.parent.name}_{ruta.name}" if (carpeta / ruta.name).exists() else carpeta / ruta.name
        copiar_base_sqlite(ruta, destino)
    return carpeta


def construir_trabajo(rutas: RutasTrabajo, fecha_referencia: Optional[date] = None):
    """Copia la base a las rutas de trabajo y aplica el escenario. Reemplaza lo que haya:
    quien llama decide si antes se respalda (``preparar``) o se descarta (``reiniciar``)."""
    from datos.escenario import aplicar_escenario

    if not base_existe():
        raise FileNotFoundError("Falta la capa base (data/cbioportal/). Ármela con: python -m datos base")
    copiar_base_sqlite(BASE_EXPEDIENTE, rutas.expediente)
    copiar_base_sqlite(BASE_PACIENTES, rutas.pacientes)
    for sufijo in ("", "-wal", "-shm"):
        Path(f"{rutas.usuarios}{sufijo}").unlink(missing_ok=True)
    return aplicar_escenario(rutas, fecha_referencia=fecha_referencia)


def es_trabajo_de_escenario(rutas: RutasTrabajo) -> bool:
    """¿La capa de trabajo ya se armó con ``datos`` (y no es la base vieja de antes de separar)?"""
    from datos.escenario import version_aplicada

    if not trabajo_existe(rutas):
        return False
    with contextlib.closing(sqlite3.connect(f"file:{rutas.expediente.as_posix()}?mode=ro", uri=True)) as conn:
        return version_aplicada(conn) is not None
