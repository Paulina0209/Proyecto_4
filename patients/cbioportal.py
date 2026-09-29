"""Importación de pacientes reales (desidentificados) desde cBioPortal.

Lee un estudio público de la API REST de cBioPortal
(https://www.cbioportal.org/api) y lo carga en las MISMAS tablas de
db/schema.sql, así que registro (HC-01), búsqueda (PAC-02) y resumen 360
(PAC-03) funcionan igual sobre estos pacientes que sobre los registrados a mano.

    python -m patients.cbioportal --tipo-cancer "Non-Small Cell Lung Cancer" --limite 30

Correspondencia (pensada para msk_chord_2024, que trae línea de tiempo
clínica; los estudios TCGA solo aportan diagnóstico, estadio y mutaciones):

    Muestra CANCER_TYPE_DETAILED + estadio        → diagnosticos
    Eventos "Treatment" (por agente)              → tratamientos
    Eventos "Lab_Test" y secuenciación tumoral    → estudios (laboratorio)
    Eventos de progresión en TC/RM/PET            → estudios (imagen)
    Eventos de estado funcional (ECOG)            → consultas
    Alertas                                       → ninguna: cBioPortal no las tiene

Limitaciones de la fuente, que se respetan en vez de inventar datos:
- Sin nombre, documento, contacto ni fecha de nacimiento: el paciente se
  llama "Paciente <id>", su identificación es de tipo `cbioportal` y la
  edad desidentificada va en los antecedentes.
- Las fechas son relativas al diagnóstico (días). Se anclan de modo que el
  último evento del paciente caiga en la fecha de importación: los
  intervalos entre eventos son reales, las fechas absolutas no.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

import requests

from . import db
from .models import EstadoTratamiento, TipoIdentificacion

URL_API = "https://www.cbioportal.org/api"
ESTUDIO_DEFECTO = "msk_chord_2024"
LIMITE_DEFECTO = 20

#: Dos administraciones del mismo agente separadas por más de esto son
#: tratamientos distintos (p. ej. una segunda línea con el mismo fármaco).
DIAS_ENTRE_CURSOS = 90
#: Un tratamiento que terminó a menos de esto del último evento registrado
#: se considera en curso.
DIAS_TRATAMIENTO_EN_CURSO = 30
#: Mutaciones listadas en el resumen de la secuenciación; el resto se cuenta.
MAX_MUTACIONES_RESUMEN = 8

_MODALIDADES_IMAGEN = {"CT": "TC", "MR": "RM", "PET": "PET"}
_PROGRESION = {
    "Y": "Progresión según el informe",
    "N": "Sin progresión según el informe",
    "Indeterminate": "Progresión indeterminada según el informe",
}
_SEXOS = {"male": "masculino", "female": "femenino"}
# Eventos "Treatment" que no son una línea oncológica: el marcador de
# medicación previa a MSK y el tratamiento óseo de soporte.
_SUBTIPOS_EXCLUIDOS = {"Prior Medications to MSK", "Bone Treatment"}
# AJCC válido ("IV", "IIIA", "2B"...); los códigos de registro 88/99 no lo son.
_REGEX_ESTADIO_AJCC = re.compile(r"^(0|I{1,3}|IV|[1-4])[A-C]?\d?$", re.IGNORECASE)


class ErrorCBioPortal(Exception):
    """La API de cBioPortal no respondió o respondió con un error."""


# ---------------------------------------------------------------------------
# Cliente HTTP
# ---------------------------------------------------------------------------

class ClienteCBioPortal:
    def __init__(self, url_base: str = URL_API, timeout: float = 60):
        self.url_base = url_base.rstrip("/")
        self.timeout = timeout
        self._sesion = requests.Session()

    def _pedir(self, metodo: str, ruta: str, **kwargs):
        try:
            respuesta = self._sesion.request(
                metodo, f"{self.url_base}{ruta}", timeout=self.timeout, **kwargs
            )
            respuesta.raise_for_status()
            return respuesta.json()
        except requests.RequestException as e:
            raise ErrorCBioPortal(f"cBioPortal {metodo} {ruta}: {e}") from e

    def tipo_cancer_por_muestra(self, estudio: str) -> list[dict]:
        """Una fila por muestra del estudio: sampleId, patientId y value (CANCER_TYPE)."""
        return self._pedir(
            "GET",
            f"/studies/{estudio}/clinical-data",
            params={"clinicalDataType": "SAMPLE", "attributeId": "CANCER_TYPE", "pageSize": 10_000_000},
        )

    def datos_clinicos(self, estudio: str, tipo: str, ids: list[str]) -> list[dict]:
        """tipo: "PATIENT" (ids de paciente) o "SAMPLE" (ids de muestra)."""
        return self._pedir(
            "POST",
            f"/studies/{estudio}/clinical-data/fetch",
            params={"clinicalDataType": tipo},
            json={"ids": ids},
        )

    def eventos(self, estudio: str, paciente: str) -> list[dict]:
        return self._pedir(
            "GET",
            f"/studies/{estudio}/patients/{paciente}/clinical-events",
            params={"pageSize": 100_000},
        )

    def mutaciones(self, estudio: str, muestras: list[str]) -> list[dict]:
        """[] si el estudio no tiene perfil de mutaciones."""
        try:
            return self._pedir(
                "POST",
                f"/molecular-profiles/{estudio}_mutations/mutations/fetch",
                params={"projection": "DETAILED"},
                json={"sampleIds": muestras},
            )
        except ErrorCBioPortal:
            return []


# ---------------------------------------------------------------------------
# Traducción al modelo local (sin red ni SQL: fácil de probar)
# ---------------------------------------------------------------------------

@dataclass
class ExpedienteImportado:
    """Un paciente de cBioPortal ya traducido a filas de las tablas locales.
    Las fechas se guardan como días desde el diagnóstico; se anclan al guardar."""
    estudio: str
    paciente_externo: str
    sexo: str
    antecedentes: str
    diagnosticos: list[tuple[int, str, Optional[str]]] = field(default_factory=list)  # (día, descripción, estadio)
    tratamientos: list[tuple[int, str, str]] = field(default_factory=list)  # (día inicio, estado, régimen)
    estudios: list[tuple[int, str, str, str]] = field(default_factory=list)  # (día, tipo, nombre, resumen)
    consultas: list[tuple[int, str]] = field(default_factory=list)  # (día, nota)

    @property
    def ultimo_dia(self) -> int:
        dias = [0]
        dias += [d[0] for d in self.diagnosticos]
        dias += [t[0] for t in self.tratamientos]
        dias += [e[0] for e in self.estudios]
        dias += [c[0] for c in self.consultas]
        return max(dias)


def _atributos(evento: dict) -> dict[str, str]:
    return {a["key"]: a["value"] for a in evento.get("attributes", [])}


def _estadio(evento_primario: Optional[dict], clinicos: dict[str, str]) -> Optional[str]:
    if evento_primario:
        ajcc = (evento_primario.get("AJCC") or "").strip()
        if _REGEX_ESTADIO_AJCC.match(ajcc):
            return ajcc.upper()
        if evento_primario.get("STAGE_CDM_DERIVED"):
            return evento_primario["STAGE_CDM_DERIVED"]
    for atributo in ("AJCC_PATHOLOGIC_TUMOR_STAGE", "STAGE_HIGHEST_RECORDED"):
        valor = (clinicos.get(atributo) or "").strip()
        if valor and valor.lower() not in ("unknown", "na", "[not available]", "[discrepancy]"):
            return valor.removeprefix("STAGE ").removeprefix("Stage ") if atributo.startswith("AJCC") else valor
    return None


def _lineas_de_tratamiento(eventos: list[dict]) -> list[tuple[str, int, int]]:
    """(régimen, inicio, fin) por línea de tratamiento, en orden cronológico.

    cBioPortal trae un evento por administración de cada agente. Primero se
    agrupan en cursos por agente; luego los cursos que se solapan en el
    tiempo forman una línea ("Carboplatin + Pemetrexed"). Así el
    tratamiento más reciente que usan PAC-02 y PAC-03 no es, por ejemplo,
    una radioterapia corta que ocultaría una terapia dirigida aún en curso.
    """
    por_agente: dict[str, list[tuple[int, int]]] = {}
    for evento in eventos:
        atributos = _atributos(evento)
        agente = (atributos.get("AGENT") or atributos.get("SUBTYPE") or "Tratamiento sin especificar").capitalize()
        inicio = evento["startNumberOfDaysSinceDiagnosis"]
        fin = evento.get("endNumberOfDaysSinceDiagnosis")
        por_agente.setdefault(agente, []).append((inicio, fin if fin is not None else inicio))

    cursos: list[tuple[int, int, str]] = []
    for agente, tramos in por_agente.items():
        tramos.sort()
        inicio, fin = tramos[0]
        for siguiente_inicio, siguiente_fin in tramos[1:]:
            if siguiente_inicio - fin > DIAS_ENTRE_CURSOS:
                cursos.append((inicio, fin, agente))
                inicio = siguiente_inicio
            fin = max(fin, siguiente_fin)
        cursos.append((inicio, fin, agente))

    lineas: list[tuple[list[str], int, int]] = []
    for inicio, fin, agente in sorted(cursos):
        if lineas and inicio <= lineas[-1][2]:
            agentes, inicio_linea, fin_linea = lineas[-1]
            if agente not in agentes:
                agentes.append(agente)
            lineas[-1] = (agentes, inicio_linea, max(fin_linea, fin))
        else:
            lineas.append(([agente], inicio, fin))
    return [(" + ".join(agentes), inicio, fin) for agentes, inicio, fin in lineas]


def _resumen_mutaciones(mutaciones: list[dict]) -> str:
    if not mutaciones:
        return "Sin mutaciones somáticas reportadas en el panel."
    alteraciones = sorted(
        f"{m['gene']['hugoGeneSymbol']} {m.get('proteinChange') or m.get('mutationType', '')}".strip()
        for m in mutaciones
    )
    texto = ", ".join(alteraciones[:MAX_MUTACIONES_RESUMEN])
    if len(alteraciones) > MAX_MUTACIONES_RESUMEN:
        texto += f" (+{len(alteraciones) - MAX_MUTACIONES_RESUMEN} más)"
    return texto


def traducir_paciente(
    estudio: str,
    paciente: str,
    clinicos_paciente: dict[str, str],
    clinicos_muestras: dict[str, dict[str, str]],
    eventos: list[dict],
    mutaciones_por_muestra: dict[str, list[dict]],
) -> ExpedienteImportado:
    sexo_fuente = (clinicos_paciente.get("GENDER") or clinicos_paciente.get("SEX") or "").lower()
    edad = clinicos_paciente.get("CURRENT_AGE_DEID") or clinicos_paciente.get("AGE")
    fallecido = (clinicos_paciente.get("OS_STATUS") or "").startswith("1")

    antecedentes = [f"Importado de cBioPortal (estudio {estudio}, paciente {paciente})."]
    if edad:
        antecedentes.append(f"Edad desidentificada: {edad} años.")
    if clinicos_paciente.get("OS_STATUS"):
        antecedentes.append(f"Estado vital: {'fallecido' if fallecido else 'vivo'}.")

    expediente = ExpedienteImportado(
        estudio=estudio,
        paciente_externo=paciente,
        sexo=_SEXOS.get(sexo_fuente, "otro"),
        antecedentes=" ".join(antecedentes),
    )

    # --- diagnóstico: tipo detallado de la muestra + estadio ---
    primario = next(
        (e for e in eventos if e["eventType"] == "Diagnosis" and _atributos(e).get("SUBTYPE") == "Primary"),
        None,
    )
    tipos = [m.get("CANCER_TYPE_DETAILED") or m.get("CANCER_TYPE") for m in clinicos_muestras.values()]
    descripcion = next((t for t in tipos if t), None)
    if descripcion is None and primario:
        descripcion = _atributos(primario).get("DX_DESCRIPTION")
    if descripcion:
        dia = primario["startNumberOfDaysSinceDiagnosis"] if primario else 0
        estadio = _estadio(_atributos(primario) if primario else None, clinicos_paciente)
        expediente.diagnosticos.append((dia, descripcion, estadio))

    # --- eventos de la línea de tiempo ---
    dia_secuenciacion: dict[str, int] = {}
    tratamientos: list[dict] = []
    for evento in eventos:
        tipo = evento["eventType"]
        dia = evento["startNumberOfDaysSinceDiagnosis"]
        atributos = _atributos(evento)
        subtipo = atributos.get("SUBTYPE")

        if tipo == "Treatment":
            if subtipo not in _SUBTIPOS_EXCLUIDOS:
                tratamientos.append(evento)
        elif tipo == "Lab_Test" and atributos.get("TEST"):
            resultado = f"{atributos.get('RESULT', '')} {atributos.get('LR_UNIT_MEASURE', '')}".strip()
            expediente.estudios.append((dia, "laboratorio", atributos["TEST"], resultado or "Sin resultado"))
        elif tipo == "Diagnosis" and subtipo == "Progression":
            modalidad = _MODALIDADES_IMAGEN.get(atributos.get("PROCEDURE_TYPE", ""), atributos.get("PROCEDURE_TYPE"))
            hallazgo = _PROGRESION.get(atributos.get("PROGRESSION", ""))
            if modalidad and hallazgo:
                expediente.estudios.append((dia, "imagen", modalidad, f"{hallazgo} (NLP)."))
        elif tipo == "Diagnosis" and subtipo == "Performance Status" and atributos.get("ECOG"):
            expediente.consultas.append((dia, f"Estado funcional ECOG {atributos['ECOG']}."))
        elif tipo in ("Sequencing", "Sample Acquisition", "Sample acquisition") and atributos.get("SAMPLE_ID"):
            dia_secuenciacion.setdefault(atributos["SAMPLE_ID"], dia)

    for muestra, mutaciones in mutaciones_por_muestra.items():
        expediente.estudios.append((
            dia_secuenciacion.get(muestra, 0),
            "laboratorio",
            f"Secuenciación tumoral {muestra}",
            _resumen_mutaciones(mutaciones),
        ))

    # El estado se decide contra el último evento del expediente completo.
    ultimo_dia = max(
        [expediente.ultimo_dia]
        + [e.get("endNumberOfDaysSinceDiagnosis") or e["startNumberOfDaysSinceDiagnosis"] for e in tratamientos]
    )
    # Última línea: en curso si llega hasta el final del expediente; si ya
    # terminó y el paciente vive, está en seguimiento. Las anteriores y las
    # de pacientes fallecidos quedan finalizadas.
    lineas = _lineas_de_tratamiento(tratamientos)
    for i, (regimen, inicio, fin) in enumerate(lineas):
        estado = EstadoTratamiento.FINALIZADO
        if i == len(lineas) - 1 and not fallecido:
            en_curso = fin >= ultimo_dia - DIAS_TRATAMIENTO_EN_CURSO
            estado = EstadoTratamiento.EN_TRATAMIENTO if en_curso else EstadoTratamiento.EN_SEGUIMIENTO
        expediente.tratamientos.append((inicio, estado.value, regimen))

    return expediente


# ---------------------------------------------------------------------------
# Persistencia
# ---------------------------------------------------------------------------

def ya_importado(conn: sqlite3.Connection, estudio: str, paciente: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM pacientes_cbioportal WHERE estudio_id = ? AND paciente_externo_id = ?",
        (estudio, paciente),
    ).fetchone() is not None


def guardar_expediente(
    conn: sqlite3.Connection, expediente: ExpedienteImportado, oncologo_id: int, hoy: Optional[date] = None
) -> int:
    """Inserta el paciente y todo su expediente en una sola transacción.
    Devuelve el id local del paciente."""
    hoy = hoy or date.today()
    ancla = hoy - timedelta(days=expediente.ultimo_dia)

    def fecha(dia: int) -> str:
        return (ancla + timedelta(days=dia)).isoformat()

    with conn:
        cur = conn.execute(
            """
            INSERT INTO pacientes (
                nombre_completo, sexo, tipo_identificacion, numero_identificacion,
                antecedentes_personales, oncologo_id, registro_completo, fecha_registro
            ) VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                f"Paciente {expediente.paciente_externo}",
                expediente.sexo,
                TipoIdentificacion.CBIOPORTAL.value,
                f"{expediente.estudio}:{expediente.paciente_externo}",
                expediente.antecedentes,
                oncologo_id,
                datetime.now().isoformat(),
            ),
        )
        paciente_id = cur.lastrowid

        conn.execute(
            "INSERT INTO pacientes_cbioportal (paciente_id, estudio_id, paciente_externo_id, fecha_importacion) "
            "VALUES (?, ?, ?, ?)",
            (paciente_id, expediente.estudio, expediente.paciente_externo, datetime.now().isoformat()),
        )
        conn.executemany(
            "INSERT INTO diagnosticos (paciente_id, descripcion, estadio, fecha) VALUES (?, ?, ?, ?)",
            [(paciente_id, desc, estadio, fecha(dia)) for dia, desc, estadio in expediente.diagnosticos],
        )
        conn.executemany(
            "INSERT INTO tratamientos (paciente_id, estado, regimen, fecha_inicio) VALUES (?, ?, ?, ?)",
            [(paciente_id, estado, regimen, fecha(dia)) for dia, estado, regimen in expediente.tratamientos],
        )
        conn.executemany(
            "INSERT INTO estudios (paciente_id, tipo, nombre, resumen, fecha) VALUES (?, ?, ?, ?, ?)",
            [(paciente_id, tipo, nombre, resumen, fecha(dia)) for dia, tipo, nombre, resumen in expediente.estudios],
        )
        conn.executemany(
            "INSERT INTO consultas (paciente_id, fecha, nota) VALUES (?, ?, ?)",
            [(paciente_id, fecha(dia), nota) for dia, nota in expediente.consultas],
        )
    return paciente_id


# ---------------------------------------------------------------------------
# Caso de uso
# ---------------------------------------------------------------------------

@dataclass
class ResultadoImportacion:
    importados: list[int] = field(default_factory=list)  # ids locales
    omitidos: int = 0  # ya estaban importados


def _por_entidad(filas: list[dict], clave: str) -> dict[str, dict[str, str]]:
    resultado: dict[str, dict[str, str]] = {}
    for fila in filas:
        resultado.setdefault(fila[clave], {})[fila["clinicalAttributeId"]] = fila["value"]
    return resultado


def importar_estudio(
    conn: sqlite3.Connection,
    estudio: str = ESTUDIO_DEFECTO,
    oncologo_id: int = 1,
    limite: int = LIMITE_DEFECTO,
    tipo_cancer: Optional[str] = None,
    cliente: Optional[ClienteCBioPortal] = None,
    progreso=None,
) -> ResultadoImportacion:
    """Importa hasta `limite` pacientes nuevos del estudio. Los que ya se
    importaron antes se saltan, así que se puede ejecutar varias veces para
    traer más. `tipo_cancer` filtra por CANCER_TYPE (texto parcial)."""
    cliente = cliente or ClienteCBioPortal()
    resultado = ResultadoImportacion()

    muestras_por_paciente: dict[str, list[str]] = {}
    for fila in cliente.tipo_cancer_por_muestra(estudio):
        if tipo_cancer and tipo_cancer.casefold() not in (fila["value"] or "").casefold():
            continue
        muestras_por_paciente.setdefault(fila["patientId"], []).append(fila["sampleId"])

    seleccionados: list[str] = []
    for paciente in muestras_por_paciente:
        if len(seleccionados) >= limite:
            break
        if ya_importado(conn, estudio, paciente):
            resultado.omitidos += 1
        else:
            seleccionados.append(paciente)
    if not seleccionados:
        return resultado

    todas_las_muestras = [m for p in seleccionados for m in muestras_por_paciente[p]]
    clinicos_pacientes = _por_entidad(cliente.datos_clinicos(estudio, "PATIENT", seleccionados), "patientId")
    clinicos_muestras = _por_entidad(cliente.datos_clinicos(estudio, "SAMPLE", todas_las_muestras), "sampleId")
    mutaciones: dict[str, list[dict]] = {m: [] for m in todas_las_muestras}
    for mutacion in cliente.mutaciones(estudio, todas_las_muestras):
        mutaciones.setdefault(mutacion["sampleId"], []).append(mutacion)

    for i, paciente in enumerate(seleccionados, 1):
        muestras = muestras_por_paciente[paciente]
        expediente = traducir_paciente(
            estudio,
            paciente,
            clinicos_pacientes.get(paciente, {}),
            {m: clinicos_muestras.get(m, {}) for m in muestras},
            cliente.eventos(estudio, paciente),
            {m: mutaciones[m] for m in muestras},
        )
        resultado.importados.append(guardar_expediente(conn, expediente, oncologo_id))
        if progreso:
            progreso(i, len(seleccionados), paciente)
    return resultado


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m patients.cbioportal",
        description="Importa pacientes de un estudio público de cBioPortal a patients/db/pacientes.db.",
    )
    parser.add_argument("--estudio", default=ESTUDIO_DEFECTO, help=f"studyId de cBioPortal (defecto: {ESTUDIO_DEFECTO})")
    parser.add_argument("--tipo-cancer", help='Filtra por CANCER_TYPE, p. ej. "Non-Small Cell Lung Cancer"')
    parser.add_argument("--limite", type=int, default=LIMITE_DEFECTO, help="Pacientes nuevos a importar")
    parser.add_argument("--oncologo", type=int, default=1, help="Oncólogo al que se asignan los pacientes")
    parser.add_argument("--db", default=str(db.RUTA_DB), help="Ruta de la base (defecto: patients/db/pacientes.db)")
    args = parser.parse_args(argv)

    conn = db.conectar(args.db)
    try:
        db.inicializar(conn)
        resultado = importar_estudio(
            conn,
            estudio=args.estudio,
            oncologo_id=args.oncologo,
            limite=args.limite,
            tipo_cancer=args.tipo_cancer,
            progreso=lambda i, total, p: print(f"  [{i}/{total}] {p}"),
        )
    except ErrorCBioPortal as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    print(
        f"Listo: {len(resultado.importados)} paciente(s) importado(s) de {args.estudio} "
        f"para el oncólogo {args.oncologo}; {resultado.omitidos} ya estaban."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
