"""Demo de ADM-02: el tablero de métricas de uso, con datos SINTÉTICOS.

    python -m administracion.demo_metricas                 # institución mediana
    python -m administracion.demo_metricas --pequeno       # pocos médicos: se ven las supresiones de privacidad
    python -m administracion.demo_metricas --salida mi_panel.html

Genera usuarios, accesos, decisiones, alertas y notas inventados (nada de
esto es información real ni toca tus bases), calcula las métricas como el
director médico y escribe el panel en un archivo HTML que se abre con doble clic.
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from administracion import usuarios as adm
from administracion.metricas_uso import FuentesMetricas, MetricasUso, consultar_metricas
from administracion.panel_metricas import renderizar_panel
from auditoria.models import TipoAccion
from auditoria.registro_acceso import crear_conexion as crear_conexion_auditoria
from auditoria.registro_acceso import registrar_acceso
from clinical_decision.registro import inicializar_schema as inicializar_decisiones
from historia_clinica.db import crear_conexion as crear_expediente
from seguridad.models import Rol, Usuario

CLAVE_DEMO = "Demo-Clave-2026"

_RAIZ = Path(__file__).resolve().parent.parent
#: Esquemas SQL de cada fuente, tal cual los usa el sistema (se leen del archivo para no duplicarlos ni
#: importar paquetes clínicos completos solo por crear una tabla).
_ESQUEMAS = (
    _RAIZ / "estadificacion" / "schema_confirmacion_estadio.sql",
    _RAIZ / "dx_clinica" / "schema_juicio_clinico.sql",
    _RAIZ / "ia_clinica" / "review" / "schema.sql",
)


def _hora(rng: random.Random, dia: datetime) -> datetime:
    return dia.replace(hour=rng.randint(8, 18), minute=rng.randint(0, 59), second=0, microsecond=0)


def sembrar(ahora: datetime, *, pequeno: bool = False, semilla: int = 7) -> Tuple[FuentesMetricas, Usuario]:
    """Tres bases en memoria con datos inventados: usuarios, accesos (como los guarda la API de pacientes) y expediente.

    Devuelve las fuentes y el usuario director médico que las consulta."""
    rng = random.Random(semilla)
    dias = 90
    inicio = (ahora - timedelta(days=dias - 1)).replace(hour=0, minute=0, second=0, microsecond=0)

    usuarios = adm.crear_conexion(":memory:")
    adm.crear_primer_administrador(usuarios, "admin.demo", CLAVE_DEMO, "Administración (demo)")
    admin = Usuario(1, "admin.demo", Rol.ADMINISTRADOR, True)
    n_onco, n_enf = (3, 2) if pequeno else (9, 7)
    ids: List[Tuple[int, Rol]] = []
    for i in range(n_onco):
        u = adm.crear_usuario(usuarios, admin, f"onco.{i + 1:02d}", CLAVE_DEMO, "oncologo", f"Oncología {i + 1} (demo)")
        ids.append((u.id, Rol.ONCOLOGO))
    for i in range(n_enf):
        u = adm.crear_usuario(usuarios, admin, f"enf.{i + 1:02d}", CLAVE_DEMO, "enfermeria", f"Enfermería {i + 1} (demo)")
        ids.append((u.id, Rol.ENFERMERIA))
    director = adm.crear_usuario(usuarios, admin, "direccion.medica", CLAVE_DEMO, "director_medico", "Dirección médica (demo)")
    adm.crear_usuario(usuarios, admin, "auditor.demo", CLAVE_DEMO, "auditor", "Auditoría (demo)")

    accesos = crear_conexion_auditoria(":memory:")
    expediente = crear_expediente(":memory:")
    expediente.execute("PRAGMA foreign_keys = OFF")
    inicializar_decisiones(expediente)
    for esquema in _ESQUEMAS:
        expediente.executescript(esquema.read_text(encoding="utf-8"))

    # Adopción gradual: cada usuario empieza a usar el sistema en una semana distinta;
    # unos pocos de la plantilla nunca lo usan.
    for uid, _rol in ids:
        if rng.random() < 0.15:
            continue
        semana_alta = rng.randint(0, 7)
        for d in range(semana_alta * 7, dias):
            if rng.random() < 0.45:
                dia = inicio + timedelta(days=d)
                for _ in range(rng.randint(1, 4)):
                    registrar_acceso(accesos, uid, rng.choice([TipoAccion.VER, TipoAccion.VER, TipoAccion.EDITAR]),
                                     paciente_id=rng.randint(1, 60), ahora=_hora(rng, dia))
    # Un par de personas sin cuenta clínica (auditoría) también miran expedientes: no cuentan como adopción.
    for _ in range(12):
        registrar_acceso(accesos, 999, TipoAccion.VER, paciente_id=rng.randint(1, 60), ahora=_hora(rng, inicio + timedelta(days=rng.randint(0, dias - 1))))

    onco_ids = [uid for uid, rol in ids if rol is Rol.ONCOLOGO]
    n_dec, n_est = (8, 6) if pequeno else (150, 110)
    for _ in range(n_dec):
        d = rng.randint(14, dias - 1)
        azar = rng.random()
        tipo = "accept" if azar < 0.66 else "modify" if azar < 0.86 else "reject"
        sugerido = rng.choice(["FOLFOX", "FOLFIRI", "CAPOX", "Pembrolizumab"])
        final = sugerido if tipo == "accept" else ("FOLFIRI" if tipo == "modify" else None)
        expediente.execute(
            "INSERT INTO decisiones_tratamiento (paciente_id, oncologo_id, fecha, tipo_decision, regimen_sugerido_id, regimen_final_id, "
            "motivo_rechazo, recomendacion_ia_snapshot) VALUES (?,?,?,?,?,?,?,?)",
            (rng.randint(1, 60), rng.choice(onco_ids), _hora(rng, inicio + timedelta(days=d)).isoformat(), tipo, sugerido, final,
             "Preferencia del paciente" if tipo == "reject" else None, "{}"))
    for _ in range(n_est):
        d = rng.randint(14, dias - 1)
        difiere = 1 if rng.random() < 0.18 else 0
        expediente.execute(
            "INSERT INTO confirmaciones_estadificacion (paciente_id, estadio_confirmado, autor, registrado_en, estadio_sugerido_por_sistema, "
            "difiere_de_sugerencia, sugerencia_disponible) VALUES (?,?,?,?,?,?,1)",
            (rng.randint(1, 60), "IIIA", f"onco.{rng.randint(1, n_onco):02d}", _hora(rng, inicio + timedelta(days=d)).isoformat(), "IIIA", difiere))
    for i in range(18 if pequeno else 55):
        d = rng.randint(7, dias - 1)
        momento = _hora(rng, inicio + timedelta(days=d)).isoformat()
        expediente.execute(
            "INSERT INTO revision_notas (nota_id, paciente_ref, contenido_ia_original, contenido_actual, estado, creado_en, aprobado_por, aprobado_en) "
            "VALUES (?,?,?,?, 'APPROVED', ?, ?, ?)", (f"demo-{i}", f"P{i}", "{}", "{}", momento, "onco", momento))
    for _ in range(30 if pequeno else 40):
        d = rng.randint(0, dias - 1)
        expediente.execute(
            "INSERT INTO sincronizaciones_externas (paciente_id, fuente, formato, estado, fecha) VALUES (?,?,?,?,?)",
            (rng.randint(1, 60), "lab-central", "fhir", "exitosa" if rng.random() < 0.9 else "fallida", _hora(rng, inicio + timedelta(days=d)).isoformat()))
    for i in range(34):
        d = rng.randint(0, dias - 1)
        expediente.execute(
            "INSERT INTO alertas_laboratorio (paciente_id, laboratorio_id, prueba, valor, unidad, limite_superado, severidad, estado, fecha) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (rng.randint(1, 60), 1000 + i, "Potasio", "2.1", "mmol/L", "< 2.5 mmol/L (crítico bajo)",
             "critica" if rng.random() < 0.8 else "alta", "revisada" if rng.random() < 0.7 else "activa",
             (inicio + timedelta(days=d)).date().isoformat()))
    for i in range(6):
        d = rng.randint(0, dias - 1)
        expediente.execute(
            "INSERT INTO conflictos_laboratorio (paciente_id, prueba_normalizada, momento, laboratorio_a_id, laboratorio_b_id, estado, fecha_deteccion) "
            "VALUES (?,?,?,?,?,?,?)",
            (rng.randint(1, 60), "hemoglobina", "2026-01-01T00:00", 2000 + i, 3000 + i, "pendiente" if i < 2 else "resuelto",
             (inicio + timedelta(days=d)).date().isoformat()))
    expediente.commit()

    quien = Usuario(director.id, director.nombre_usuario, Rol.DIRECTOR_MEDICO, True)
    return FuentesMetricas(usuarios, [accesos, expediente]), quien


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pequeno", action="store_true", help="institución pequeña: se ven las supresiones de privacidad")
    ap.add_argument("--salida", default="panel_metricas_demo.html", help="archivo HTML de salida")
    ap.add_argument("--dias", type=int, default=30, help="duración del periodo mostrado (por defecto 30)")
    args = ap.parse_args(argv)

    ahora = datetime.now(timezone.utc)
    fuentes, director = sembrar(ahora, pequeno=args.pequeno)
    hasta = ahora.date()
    metricas: MetricasUso = consultar_metricas(fuentes, director, desde=hasta - timedelta(days=args.dias - 1), hasta=hasta, via="demo", ahora=ahora)

    a, t, al = metricas.adopcion, metricas.tiempo_ahorrado, metricas.alertas
    print("DATOS SINTÉTICOS — nada de esto es información real.\n")
    print(f"Periodo: {metricas.periodo.desde} a {metricas.periodo.hasta} ({metricas.periodo.dias} días)")
    print(f"Adopción: {a.usuarios_activos} de {a.usuarios_elegibles} usuarios clínicos ({(a.tasa_adopcion or 0) * 100:.0f} %)")
    print(f"Tiempo ahorrado (ESTIMADO): {t.horas_min}–{t.horas_max} h")
    print(f"Alertas generadas: {al.generadas} (pendientes hoy: {al.pendientes_actuales})")
    for d in metricas.aceptacion_ia.dominios:
        if d.suprimida:
            print(f"Aceptación {d.dominio}: SUPRIMIDA por privacidad — {d.motivo}")
        else:
            print(f"Aceptación {d.dominio}: " + ", ".join(f"{etq}={n}" for _, etq, n in d.categorias))
    ruta = Path(args.salida)
    ruta.write_text(renderizar_panel(metricas), encoding="utf-8")
    print(f"\nPanel escrito en {ruta.resolve()} — ábrelo con doble clic.")
    eventos = fuentes.usuarios.execute("SELECT accion, detalle FROM eventos_acceso WHERE accion = ?", (TipoAccion.CONSULTAR_METRICAS.value,)).fetchall()
    print(f"La consulta quedó en la auditoría: {json.loads(eventos[-1][1])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
