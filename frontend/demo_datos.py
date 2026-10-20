"""Datos SINTÉTICOS para probar la interfaz web sin tocar bases reales.

Todo lo de este archivo es inventado (personas, resultados, estudios): no representa pacientes reales.
Se crea con las mismas funciones que usa el sistema (registro de pacientes, laboratorios HC-02, biopsias y
biomarcadores HC-04, índice de estudios del PACS HC-03), de modo que la interfaz se prueba contra el
comportamiento real de las APIs y no contra respuestas copiadas a mano.

    entorno = sembrar_demo(Path("salida_demo_frontend"))

Usuarios (todos con la misma contraseña ``CLAVE_DEMO``):

    admin.demo   administrador del sistema   (solo ve el mensaje de «sin pantallas clínicas»)
    dra.rios     oncología (seis pacientes)
    dr.vega      oncología (dos pacientes: la Dra. Ríos NO debe verlos)
    enf.mora     enfermería                  (sin asignación de pacientes todavía)
    direccion    dirección médica            (tablero de métricas)
    onco.03..09, enf.02..07, auditor.demo: plantilla de relleno para que las métricas de la demo tengan sentido.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from administracion import usuarios as adm
from historia_clinica import biopsias_biomarcadores as hc04
from historia_clinica import imagenes_pacs as hc03
from historia_clinica import laboratorios as hc02
from historia_clinica.db import conectar_expediente
from patients import db as pdb
from patients.busqueda import registrar_consulta, registrar_diagnostico, registrar_tratamiento
from patients.expediente import paciente_en_expediente
from patients.models import AntecedentesMedicos, DatosContacto, EstadoTratamiento, Paciente, Sexo, TipoIdentificacion
from patients.registro import registrar_paciente
from seguridad.models import Rol, Usuario

CLAVE_DEMO = "Demo-Clave-2026"
PLANTILLA_VISOR_DEMO = "https://127.0.0.1:8443/demo/visor?StudyInstanceUIDs={study_uid}"


@dataclass
class EntornoDemo:
    carpeta: Path
    usuarios_db: Path
    pacientes_db: Path
    expediente_db: Path
    usuarios: Dict[str, int] = field(default_factory=dict)
    pacientes: Dict[str, int] = field(default_factory=dict)
    pacs: Optional["PacsDemo"] = None


class PacsDemo:
    """Un PACS de juguete: devuelve estudios inventados por identificación (nunca contacta la red)."""

    nombre = "PACS de demostración"

    def __init__(self) -> None:
        self.estudios: Dict[str, List[hc03.EstudioDICOM]] = {}
        self.caido = False

    def agregar(self, identificacion: str, nombre: str, uid: str, fecha: date, modalidad: str, descripcion: str,
                series: int, instancias: int) -> None:
        self.estudios.setdefault(identificacion, []).append(hc03.EstudioDICOM(
            study_uid=uid, patient_id=identificacion, patient_name=nombre, fecha=fecha.isoformat(), modalidad=modalidad,
            descripcion=descripcion, accession_number=f"A{uid[-4:]}", series=series, instancias=instancias))

    def buscar_estudios(self, identificacion: str) -> List[hc03.EstudioDICOM]:
        if self.caido:
            raise ConnectionError("el servidor del PACS no responde")
        return list(self.estudios.get(identificacion, []))


def _paciente(nombre: str, nacimiento: date, sexo: Sexo, documento: str, oncologo_id: int, telefono: str,
              antecedentes: Optional[str] = None, motivo: Optional[str] = None) -> Paciente:
    return Paciente(
        nombre_completo=nombre, fecha_nacimiento=nacimiento, sexo=sexo, tipo_identificacion=TipoIdentificacion.CEDULA,
        numero_identificacion=documento, contacto=DatosContacto(telefono=telefono), oncologo_id=oncologo_id,
        antecedentes=AntecedentesMedicos(personales=antecedentes, familiares=None), motivo_consulta_inicial=motivo)


def sembrar_demo(carpeta: Path, hoy: Optional[date] = None) -> EntornoDemo:
    """Crea (o recrea) las tres bases de la demo en ``carpeta`` y devuelve dónde quedó cada cosa."""
    hoy = hoy or date.today()
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    entorno = EntornoDemo(carpeta, carpeta / "usuarios.db", carpeta / "pacientes.db", carpeta / "expediente.db")
    for ruta in (entorno.usuarios_db, entorno.pacientes_db, entorno.expediente_db):
        ruta.unlink(missing_ok=True)

    def antes(dias: int) -> date:
        return hoy - timedelta(days=dias)

    # --- Usuarios -------------------------------------------------------------------------------
    conn_u = adm.crear_conexion(str(entorno.usuarios_db))
    try:
        admin = adm.crear_primer_administrador(conn_u, "admin.demo", CLAVE_DEMO, "Administración (demo)")
        actor = Usuario(admin.id, admin.nombre_usuario, Rol.ADMINISTRADOR, True)
        entorno.usuarios["admin.demo"] = admin.id
        # Mismo orden y cantidad que ``administracion.demo_metricas.sembrar`` (admin 1, oncología 2-10, enfermería
        # 11-17, dirección 18, auditoría 19): así el tablero de métricas de la demo, que usa esos accesos inventados,
        # se corresponde con estas cuentas.
        cuentas = [("dra.rios", Rol.ONCOLOGO, "Dra. Camila Ríos"), ("dr.vega", Rol.ONCOLOGO, "Dr. Andrés Vega")]
        cuentas += [(f"onco.{i:02d}", Rol.ONCOLOGO, f"Oncología {i} (demo)") for i in range(3, 10)]
        cuentas += [("enf.mora", Rol.ENFERMERIA, "Enf. Laura Mora")]
        cuentas += [(f"enf.{i:02d}", Rol.ENFERMERIA, f"Enfermería {i} (demo)") for i in range(2, 8)]
        cuentas += [("direccion", Rol.DIRECTOR_MEDICO, "Dirección médica (demo)"), ("auditor.demo", Rol.AUDITOR, "Auditoría (demo)")]
        for nombre, rol, completo in cuentas:
            creado = adm.crear_usuario(conn_u, actor, nombre, CLAVE_DEMO, rol.value, completo)
            entorno.usuarios[nombre] = creado.id
    finally:
        conn_u.close()
    rios, vega = entorno.usuarios["dra.rios"], entorno.usuarios["dr.vega"]

    # --- Pacientes (base de pacientes) ------------------------------------------------------------
    pacs = PacsDemo()
    entorno.pacs = pacs
    conn = pdb.conectar(entorno.pacientes_db)
    pdb.inicializar(conn)
    conn_exp = conectar_expediente(entorno.expediente_db)

    def alta(clave: str, nombre: str, nacimiento: date, sexo: Sexo, documento: str, oncologo: int, telefono: str,
             diagnostico: Optional[str] = None, estadio: Optional[str] = None, dx_hace: int = 200,
             tratamiento: Optional[tuple] = None, consultas: tuple = (), completo: bool = True) -> int:
        resultado = registrar_paciente(conn, _paciente(
            nombre, nacimiento, sexo, documento, oncologo, telefono,
            antecedentes="Sin antecedentes relevantes (dato sintético)." if completo else None,
            motivo="Primera consulta oncológica (dato sintético)." if completo else None))
        if not resultado.exito:  # pragma: no cover - los datos son fijos; si falla, el mensaje dice por qué
            raise RuntimeError("No se pudo sembrar a %s: %s" % (nombre, [e.mensaje for e in resultado.errores]))
        pid = resultado.paciente.id
        if diagnostico:
            registrar_diagnostico(conn, pid, diagnostico, antes(dx_hace), estadio)
        if tratamiento:
            estado, regimen, hace = tratamiento
            registrar_tratamiento(conn, pid, estado, antes(hace), regimen)
        for hace, nota in consultas:
            registrar_consulta(conn, pid, antes(hace), nota)
        entorno.pacientes[clave] = pid
        return pid

    def expediente(pid: int) -> int:
        return paciente_en_expediente(conn, conn_exp, pid, crear=True)

    def lab(pid: int, exp_id: int, doc: str, nombre: str, prueba: str, valor: str, unidad: str, hace: int,
            rango: Optional[str] = None) -> None:
        hc02.registrar_resultado_laboratorio(
            conn_exp, exp_id, identificacion=doc, nombre=nombre, prueba=prueba, valor=valor, unidad=unidad,
            fecha=antes(hace), rango_referencia=rango)

    def nota_expediente(exp_id: int, hace: int, motivo: str, notas: str) -> None:
        conn_exp.execute("INSERT INTO consultas (paciente_id, fecha, motivo, notas_libres) VALUES (?, ?, ?, ?)",
                         (exp_id, antes(hace).isoformat(), motivo, notas))
        conn_exp.commit()

    def estudio_360(pid: int, hace: int, nombre: str, resumen: str) -> None:
        """Lo que el resumen 360 muestra como «imágenes recientes» (vive en la base de pacientes, no en el expediente)."""
        conn.execute("INSERT INTO estudios (paciente_id, tipo, nombre, resumen, fecha) VALUES (?, 'imagen', ?, ?, ?)",
                     (pid, nombre, resumen, antes(hace).isoformat()))
        conn.commit()

    def alerta_360(pid: int, tipo: str, severidad: str, descripcion: str, hace: int = 1) -> None:
        conn.execute("INSERT INTO alertas (paciente_id, tipo, severidad, descripcion, fecha) VALUES (?, ?, ?, ?, ?)",
                     (pid, tipo, severidad, descripcion, antes(hace).isoformat()))
        conn.commit()

    def informe(exp_id: int, hace: int, modalidad: str, region: str, hallazgos: str) -> None:
        conn_exp.execute("INSERT INTO imagenologia (paciente_id, fecha, modalidad, region, hallazgos) VALUES (?, ?, ?, ?, ?)",
                         (exp_id, antes(hace).isoformat(), modalidad, region, hallazgos))
        conn_exp.commit()

    # 1. Mama triple negativo, en tratamiento: tendencia de hemoglobina a la baja y un potasio crítico.
    doc, nombre = "1020304050", "Lucía Herrera Posada"
    pid = alta("lucia", nombre, date(1968, 3, 14), Sexo.FEMENINO, doc, rios, "3001112233",
               "Carcinoma ductal invasor de mama, triple negativo", "IIB", 70,
               (EstadoTratamiento.EN_TRATAMIENTO, "Pembrolizumab + quimioterapia neoadyuvante", 56),
               ((50, "Ciclo 2 sin incidentes; refiere fatiga leve."), (14, "Ciclo 4. Náusea grado 1 controlada.")))
    exp = expediente(pid)
    nota_expediente(exp, 14, "Control de ciclo 4", "Náusea grado 1 controlada con ondansetrón. Sin fiebre. Examen físico sin cambios (dato sintético).")
    for hace, hb, plt in ((56, "12.8", "262"), (35, "11.9", "231"), (14, "10.4", "198"), (3, "9.6", "176")):
        lab(pid, exp, doc, nombre, "Hemoglobina", hb, "g/dL", hace, "12.0-16.0")
        lab(pid, exp, doc, nombre, "Plaquetas", plt, "10^3/uL", hace, "150-400")
    lab(pid, exp, doc, nombre, "Potasio", "6.8", "mmol/L", 2, "3.5-5.1")  # crítico: genera alerta
    lab(pid, exp, doc, nombre, "Creatinina", "0.9", "mg/dL", 2, "0.5-1.1")
    try:
        ep = hc04.registrar_episodio(conn_exp, exp, "Carcinoma ductal invasor de mama", "breast", antes(70))
        bp = hc04.registrar_biopsia(conn_exp, exp, fecha=antes(70), sitio="Mama izquierda", procedimiento="Biopsia con aguja gruesa",
                                    diagnostico_histologico="Carcinoma ductal invasor grado 3", episodio_id=ep.id, registrado_por="dra.rios")
        hc04.registrar_biomarcador(conn_exp, exp, biopsia_id=bp.id, biomarcador="HER2", estado="negativo", confirmacion="negativo",
                                   metodo="IHC", ihc_score="0", registrado_por="dra.rios")
        hc04.registrar_biomarcador(conn_exp, exp, biopsia_id=bp.id, biomarcador="RE", estado="negativo", confirmacion="negativo",
                                   metodo="IHC", registrado_por="dra.rios")
    except Exception as exc:  # noqa: BLE001 - sin catálogo de guías disponible la demo sigue sin biomarcadores
        print("(Demo: se omiten biomarcadores: %s)" % exc)
    informe(exp, 62, "RM", "Mama izquierda", "Lesión espiculada de 2.4 cm en cuadrante superoexterno (dato sintético).")
    informe(exp, 20, "PET-CT", "Cuerpo completo", "Respuesta metabólica parcial; sin captación a distancia (dato sintético).")
    estudio_360(pid, 62, "RM mama", "Lesión espiculada de 2.4 cm (dato sintético)")
    estudio_360(pid, 20, "PET-CT", "Respuesta metabólica parcial (dato sintético)")
    alerta_360(pid, "estudio_pendiente", "media", "Ecocardiograma de control pendiente antes del ciclo 5.")
    # Antecedentes traídos de otra institución con fecha incompleta: la línea de tiempo (HC-06) los marca aproximados.
    for tipo, descripcion, cuando in (("condicion", "Hipotiroidismo en tratamiento con levotiroxina", str(hoy.year - 17)),
                                      ("procedimiento", "Colecistectomía laparoscópica", f"{hoy.year - 6}-06")):
        conn_exp.execute("INSERT INTO antecedentes_externos (paciente_id, tipo, descripcion, fecha, fuente) VALUES (?, ?, ?, ?, ?)",
                         (exp, tipo, f"{descripcion} (dato sintético)", cuando, "Historia clínica externa (FHIR)"))
    conn_exp.commit()
    pacs.agregar(doc, nombre, "1.2.826.0.1.3680043.8.498.10001", antes(62), "MR", "RM mama bilateral con contraste", 6, 312)
    pacs.agregar(doc, nombre, "1.2.826.0.1.3680043.8.498.10002", antes(20), "PT", "PET-CT cuerpo completo", 3, 740)

    # 2. Pulmón con EGFR L858R.
    doc, nombre = "1030405060", "Mateo Quintero Ruiz"
    pid = alta("mateo", nombre, date(1957, 9, 2), Sexo.MASCULINO, doc, rios, "3002223344",
               "Adenocarcinoma de pulmón", "IV", 120,
               (EstadoTratamiento.EN_TRATAMIENTO, "Osimertinib 80 mg/día", 100), ((90, "Inicio de ITK."), (30, "Tolerancia buena; rash leve.")))
    exp = expediente(pid)
    nota_expediente(exp, 30, "Seguimiento mensual", "Rash acneiforme leve. Disnea estable. ECOG 1 (dato sintético).")
    for hace, cr in ((100, "0.9"), (60, "1.0"), (20, "1.1")):
        lab(pid, exp, doc, nombre, "Creatinina", cr, "mg/dL", hace, "0.7-1.3")
    lab(pid, exp, doc, nombre, "Hemoglobina", "13.4", "g/dL", 20, "13.5-17.5")
    try:
        ep = hc04.registrar_episodio(conn_exp, exp, "Adenocarcinoma de pulmón", "NSCLC", antes(120))
        bp = hc04.registrar_biopsia(conn_exp, exp, fecha=antes(118), sitio="Pulmón derecho", procedimiento="Biopsia guiada por TC",
                                    diagnostico_histologico="Adenocarcinoma", episodio_id=ep.id, registrado_por="dra.rios")
        hc04.registrar_biomarcador(conn_exp, exp, biopsia_id=bp.id, biomarcador="EGFR", estado="detectada", confirmacion="detectada",
                                   metodo="NGS", variante="L858R", registrado_por="dra.rios")
    except Exception as exc:  # noqa: BLE001
        print("(Demo: se omiten biomarcadores: %s)" % exc)
    informe(exp, 45, "TC", "Tórax", "Reducción del 38 % de la lesión dominante (dato sintético).")
    estudio_360(pid, 45, "TC tórax", "Reducción del 38 % de la lesión dominante (dato sintético)")
    alerta_360(pid, "interaccion", "media", "Osimertinib y hierba de San Juan: evitar, reduce la exposición al fármaco (inductor de CYP3A4).")
    pacs.agregar(doc, nombre, "1.2.826.0.1.3680043.8.498.20001", antes(45), "CT", "TC de tórax con contraste", 4, 220)

    # 3. Melanoma en seguimiento, sin estudios de imagen.
    doc, nombre = "1040506070", "Valentina Osorio Peña"
    pid = alta("valentina", nombre, date(1981, 11, 23), Sexo.FEMENINO, doc, rios, "3003334455",
               "Melanoma cutáneo", "IIIA", 400, (EstadoTratamiento.EN_SEGUIMIENTO, "Vigilancia clínica cada 3 meses", 300),
               ((20, "Sin lesiones nuevas en dermatoscopia."),))
    exp = expediente(pid)
    lab(pid, exp, doc, nombre, "Hemoglobina", "13.9", "g/dL", 20, "12.0-16.0")
    lab(pid, exp, doc, nombre, "LDH", "180", "U/L", 20, "140-280")

    # 4. Riñón, suspendido: dos creatininas distintas el mismo día (conflicto de laboratorio por resolver).
    doc, nombre = "1050607080", "Samuel Arango Bedoya"
    pid = alta("samuel", nombre, date(1962, 6, 30), Sexo.MASCULINO, doc, rios, "3004445566",
               "Carcinoma de células renales", "IV", 300, (EstadoTratamiento.SUSPENDIDO, "Pazopanib (suspendido por toxicidad)", 150),
               ((10, "Tratamiento suspendido por hipertensión no controlada."),))
    exp = expediente(pid)
    lab(pid, exp, doc, nombre, "Creatinina", "1.6", "mg/dL", 5, "0.7-1.3")
    lab(pid, exp, doc, nombre, "Creatinina", "2.3", "mg/dL", 5, "0.7-1.3")
    lab(pid, exp, doc, nombre, "Sodio", "139", "mmol/L", 5, "135-145")
    estudio_360(pid, 40, "TC abdomen y pelvis", "Enfermedad estable (dato sintético)")
    pacs.agregar(doc, nombre, "1.2.826.0.1.3680043.8.498.40001", antes(40), "CT", "TC abdomen y pelvis", 3, 410)

    # 5. Registro incompleto: sin estadio ni tratamiento (el 360 debe avisarlo).
    alta("isabela", "Isabela Cardona Mejía", date(1975, 1, 8), Sexo.FEMENINO, "1060708090", rios, "3005556677",
         "Carcinoma pulmonar de células pequeñas", None, 12, None, (), completo=False)

    # 6. Sin datos clínicos todavía.
    alta("tomas", "Tomás Villegas Franco", date(1990, 5, 17), Sexo.MASCULINO, "1070809010", rios, "3006667788",
         "Linfoma de Hodgkin", "IIA", 30, (EstadoTratamiento.EN_TRATAMIENTO, "ABVD", 20), ())

    # Pacientes del Dr. Vega (la Dra. Ríos no debe poder verlos).
    alta("renata", "Renata Londoño Gil", date(1970, 2, 2), Sexo.FEMENINO, "1080901020", vega, "3007778899",
         "Cáncer de ovario", "IIIC", 90, (EstadoTratamiento.EN_TRATAMIENTO, "Carboplatino + paclitaxel", 80), ())
    alta("esteban", "Esteban Zapata Mora", date(1959, 12, 12), Sexo.MASCULINO, "1090102030", vega, "3008889900",
         "Cáncer de próstata", "II", 500, (EstadoTratamiento.EN_SEGUIMIENTO, "Vigilancia activa", 400), ())

    # Índice de estudios del PACS (HC-03): lo que el expediente muestra como «estudios».
    for clave, pid in entorno.pacientes.items():
        if clave in ("lucia", "mateo", "samuel"):
            exp_id = paciente_en_expediente(conn, conn_exp, pid, crear=True)
            hc03.sincronizar_estudios(conn_exp, exp_id, pacs)
    conn.close()
    conn_exp.close()
    return entorno
