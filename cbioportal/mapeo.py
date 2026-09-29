"""Traducción de la historia de un paciente de cBioPortal al expediente local.

Funciones puras: reciben el ``contenido`` que arma ``FuenteCBioPortal`` y
devuelven filas (``RegistroExterno``) para las tablas que ya leen DX, EST,
TX, IA y HC-05. No hacen llamadas de red.

Reglas clínicas del mapeo (fail-closed, igual que HC-05):

    - Solo se guarda lo que la fuente afirma. Nada que requiera juicio del
      oncólogo se deriva aquí: ni ``disease_setting``, ni categorías T/N/M,
      ni ``molecular_pathway_status``. Esos ítems quedan como faltantes y
      HC-05 los señala.
    - Las variantes genómicas se guardan como hechos ("mutación detectada:
      L858R", "fusión detectada: EML4-ALK"), nunca como "positivo": no
      toda variante en un gen es un driver accionable, y clasificarla es
      responsabilidad del oncólogo o de una herramienta de anotación.
    - "No detectada" solo se afirma para genes que el panel de la muestra
      realmente secuenció. Sin panel conocido, solo se guardan hallazgos.
    - Si el paciente tiene muestras de más de un tipo de cáncer, no se
      registra ``cancer_type`` (HC-05 dirá que no puede evaluar), y si tiene
      más de un diagnóstico primario, no se toma ningún estadio.
    - Los hallazgos de imagen de MSK-CHORD vienen de NLP sobre informes
      radiológicos; el texto guardado lo dice explícitamente.

Fechas: cBioPortal está desidentificado y publica días relativos, no
fechas. Se ubican en el calendario de forma que el último evento del
paciente caiga en ``fecha_referencia``; los intervalos entre eventos son
reales, las fechas absolutas no.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from historia_clinica.integracion_externa import PacienteNoCoincideError, RegistroExterno

FORMATO_CBIOPORTAL = "cbioportal"

#: Tipo de cáncer de cBioPortal -> código de ``cancer_type`` que usan las
#: guías y el checklist de HC-05. Los demás se guardan con su nombre
#: original (HC-05 dirá que no tiene checklist para ellos).
TIPOS_CANCER = {
    "Breast Cancer": "breast",
    "Non-Small Cell Lung Cancer": "NSCLC",
    "Melanoma": "melanoma",
    "Renal Cell Carcinoma": "renal_cell_carcinoma",
}

#: Genes que se consultan según el tipo de cáncer: los que piden las guías
#: cargadas en ``guidelines/`` y el checklist de HC-05. ERBB2 no está en
#: mama a propósito: su nombre coincide con el ítem HER2 de HC-05, y "sin
#: mutación en ERBB2" no equivale al estado HER2 (IHC/ISH).
GENES_POR_TIPO: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "breast": {"mutaciones": ("PIK3CA", "ESR1", "BRCA1", "BRCA2"), "fusiones": ()},
    "NSCLC": {
        "mutaciones": ("EGFR", "KRAS", "BRAF", "MET", "ERBB2"),
        "fusiones": ("ALK", "ROS1", "RET", "NTRK1", "NTRK2", "NTRK3"),
    },
    "melanoma": {"mutaciones": ("BRAF", "NRAS", "KIT"), "fusiones": ()},
}

#: Límite superior de referencia habitual en adultos. Ilustrativo: cada
#: institución debe reemplazarlo por los rangos de su laboratorio.
RANGOS_LABORATORIO = {
    "CEA": ("ng/ml", "0-5.0"),
    "CA 15-3": ("units/ml", "0-30"),
    "CA 19-9": ("units/ml", "0-37"),
    "PSA": ("ng/ml", "0-4.0"),
}

_MODALIDADES = {"CT": "TAC", "MR": "Resonancia magnética", "PET": "PET-CT"}
_REGIONES = (("HEAD", "cabeza"), ("CHEST", "tórax"), ("ABDOMEN", "abdomen"), ("PELVIS", "pelvis"), ("OTHER", "otra"))
_SITIOS = {
    "Bone": "hueso", "Lung": "pulmón", "Lymph Nodes": "ganglios linfáticos", "Liver": "hígado",
    "CNS/Brain": "sistema nervioso central", "Pleura": "pleura", "Intra-Abdominal": "intraabdominal",
    "Adrenal Glands": "glándulas suprarrenales", "Reproductive Organs": "órganos reproductivos", "Other": "otro",
}
CLASES_TRATAMIENTO = {
    "Chemo": "quimioterapia", "Hormone": "hormonoterapia", "Immuno": "inmunoterapia",
    "Targeted": "terapia dirigida", "Biologic": "terapia biológica", "Bone Treatment": "tratamiento óseo",
    "Investigational": "fármaco en investigación",
}
#: Sitios que, marcados en el paciente, indican enfermedad a distancia
#: (los ganglios y el pulmón se excluyen: pueden ser regionales o el primario).
_SITIOS_DISTANTES = ("BONE", "LIVER", "CNS_BRAIN", "ADRENAL_GLANDS")


def identificacion_cbioportal(estudio: str, paciente: str) -> str:
    """Identificación local de un paciente de cBioPortal (única por estudio)."""
    return f"CBIO:{estudio}:{paciente}"


def partes_identificacion(identificacion: str) -> Tuple[str, str]:
    prefijo, _, resto = identificacion.partition(":")
    estudio, _, paciente = resto.partition(":")
    if prefijo != "CBIO" or not estudio or not paciente:
        raise ValueError(f"'{identificacion}' no es una identificación de cBioPortal (CBIO:<estudio>:<paciente>).")
    return estudio, paciente


@dataclass(frozen=True)
class FichaPaciente:
    """Fila de ``pacientes`` para un paciente de cBioPortal."""

    identificacion: str
    nombre: str
    fecha_nacimiento: str
    sexo: str
    diagnostico_principal: Optional[str]
    estadio: Optional[str]
    #: Código de ``cancer_type`` o ``None`` si es ambiguo/desconocido.
    tipo_cancer: Optional[str]


# ---------------------------------------------------------------------------
# Calendario
# ---------------------------------------------------------------------------


def calendario(contenido: Dict[str, Any], fecha_referencia: date) -> Callable[[Optional[int]], str]:
    """Convierte "día relativo" en fecha ISO, anclando el último evento a
    ``fecha_referencia``."""
    dias = [d for e in contenido.get("eventos") or [] for d in (e.get("inicio"), e.get("fin")) if d is not None]
    ancla = fecha_referencia - timedelta(days=max(dias, default=0))

    def fecha(dia: Optional[int]) -> str:
        return (ancla + timedelta(days=dia)).isoformat() if dia is not None else fecha_referencia.isoformat()

    return fecha


# ---------------------------------------------------------------------------
# Ficha del paciente
# ---------------------------------------------------------------------------


def tipos_de_cancer(contenido: Dict[str, Any]) -> List[str]:
    return sorted({m["datos"]["CANCER_TYPE"] for m in contenido.get("muestras") or [] if m["datos"].get("CANCER_TYPE")})


def tipo_cancer(contenido: Dict[str, Any]) -> Optional[str]:
    tipos = tipos_de_cancer(contenido)
    return TIPOS_CANCER.get(tipos[0], tipos[0]) if len(tipos) == 1 else None


def _diagnosticos_primarios(contenido: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        e for e in contenido.get("eventos") or []
        if e["tipo"] == "Diagnosis" and e["atributos"].get("SUBTYPE") == "Primary"
    ]


def _estadio(contenido: Dict[str, Any]) -> Optional[str]:
    primarios = _diagnosticos_primarios(contenido)
    if len(primarios) == 1:
        ajcc = primarios[0]["atributos"].get("AJCC")
        if ajcc and ajcc.upper() not in {"NA", "N/A", "UNK", "UNKNOWN"}:
            return ajcc
    return None


def ficha_paciente(contenido: Dict[str, Any], fecha_referencia: date) -> FichaPaciente:
    estudio, paciente = contenido["estudio"], contenido["paciente"]
    datos = contenido.get("datos_paciente") or {}
    detallados = sorted(
        {m["datos"].get("CANCER_TYPE_DETAILED") or m["datos"].get("CANCER_TYPE") for m in contenido.get("muestras") or []}
        - {None}
    )
    return FichaPaciente(
        identificacion=identificacion_cbioportal(estudio, paciente),
        nombre=f"Paciente {paciente} (cBioPortal {estudio})",
        fecha_nacimiento=_fecha_nacimiento(datos, fecha_referencia),
        sexo=_sexo(datos.get("GENDER") or datos.get("SEX")),
        diagnostico_principal=" / ".join(detallados) or None,
        estadio=_estadio(contenido),
        tipo_cancer=tipo_cancer(contenido),
    )


def _sexo(valor: Optional[str]) -> str:
    return {"female": "femenino", "male": "masculino"}.get((valor or "").strip().lower(), "otro")


def _fecha_nacimiento(datos: Dict[str, str], fecha_referencia: date) -> str:
    """Aproximada: solo se conoce la edad (el estudio está desidentificado)."""
    edad = datos.get("CURRENT_AGE_DEID") or datos.get("AGE")
    try:
        anios = int(float(edad))
    except (TypeError, ValueError):
        return "desconocida"
    return date(fecha_referencia.year - anios, 1, 1).isoformat()


# ---------------------------------------------------------------------------
# Registros del expediente
# ---------------------------------------------------------------------------


def registros_desde_cbioportal(
    contenido: Dict[str, Any], paciente: Any, fecha_referencia: date
) -> Tuple[List[RegistroExterno], int]:
    """Traductor para ``historia_clinica.integracion_externa._importar``.

    Devuelve ``(registros, omitidos)``; ``omitidos`` cuenta los eventos que
    no tienen equivalente en el expediente (secuenciación, toma de muestra).
    """
    esperado = identificacion_cbioportal(contenido["estudio"], contenido["paciente"])
    if paciente.identificacion != esperado:
        raise PacienteNoCoincideError(
            f"La historia de cBioPortal corresponde a {esperado}; se esperaba {paciente.identificacion}. "
            "No se importó ningún dato."
        )

    fecha = calendario(contenido, fecha_referencia)
    prefijo = f"{contenido['estudio']}:{contenido['paciente']}"
    registros: List[RegistroExterno] = []

    def agregar(clave: str, tabla: str, **valores: Any) -> None:
        registros.append(RegistroExterno(f"{prefijo}:{clave}", tabla, valores))

    for variable, valor, dia in _datos_estructurados(contenido):
        agregar(f"dato:{variable}={valor}", "datos_clinicos_estructurados", fecha=fecha(dia), variable=variable, valor=valor)

    for nombre, resultado, dia in _biomarcadores(contenido):
        agregar(f"biomarcador:{nombre}={resultado}", "biomarcadores", fecha=fecha(dia), biomarcador=nombre, resultado=resultado)

    omitidos = 0
    for evento in contenido.get("eventos") or []:
        tipo, a, inicio, fin = evento["tipo"], evento["atributos"], evento.get("inicio"), evento.get("fin")
        subtipo = a.get("SUBTYPE")
        if tipo == "Lab_Test" and a.get("TEST") and a.get("RESULT"):
            prueba = a["TEST"].replace("_", " ")
            unidad = a.get("LR_UNIT_MEASURE")
            rango = _rango(prueba, unidad)
            agregar(
                f"lab:{inicio}:{prueba}:{a['RESULT']}", "laboratorios",
                fecha=fecha(inicio), prueba=prueba, valor=a["RESULT"], unidad=unidad,
                rango_referencia=rango, alterado=int(_fuera_de_rango(a["RESULT"], rango)),
            )
        elif tipo == "Treatment" and subtipo == "Radiation Therapy":
            agregar(f"radioterapia:{inicio}:{fin}", "antecedentes_externos",
                    tipo="procedimiento", descripcion=f"Radioterapia{_periodo(fecha, inicio, fin)}", fecha=fecha(inicio))
        elif tipo == "Treatment" and subtipo == "Prior Medications to MSK":
            agregar(f"previo:{inicio}:{a.get('Treatment_TYPE')}", "antecedentes_externos",
                    tipo="medicacion", fecha=fecha(inicio),
                    descripcion=f"Tratamiento previo a MSK (inferido, probabilidad {a.get('INFERRED_TX_PROB', 'no informada')}): "
                                f"{a.get('Treatment_TYPE') or 'sin especificar'}")
        elif tipo == "Treatment":
            agente = a.get("AGENT") or "sin especificar"
            clase = CLASES_TRATAMIENTO.get(subtipo, subtipo or "tratamiento")
            agregar(f"tratamiento:{inicio}:{fin}:{agente}", "antecedentes_externos",
                    tipo="medicacion", descripcion=f"{agente.capitalize()} ({clase}){_periodo(fecha, inicio, fin)}",
                    fecha=fecha(inicio))
        elif tipo == "Surgery":
            nombre = "Toma de muestra quirúrgica" if subtipo == "SAMPLE" else "Procedimiento quirúrgico"
            agregar(f"cirugia:{inicio}:{subtipo}", "antecedentes_externos",
                    tipo="procedimiento", descripcion=nombre, fecha=fecha(inicio))
        elif tipo == "Diagnosis" and subtipo == "Primary":
            agregar(f"primario:{inicio}:{a.get('DX_DESCRIPTION')}", "antecedentes_externos",
                    tipo="condicion", descripcion=_describir_primario(a), fecha=fecha(inicio))
        elif tipo == "Diagnosis" and subtipo in {"Performance Status", "Progression", "HasCancer", "Tumor Sites"}:
            continue  # ECOG va en datos estructurados; las imágenes se agrupan abajo
        elif tipo == "Pathology":
            continue  # PD-L1 va en biomarcadores
        else:
            omitidos += 1

    for dia, modalidad, region, hallazgos in _imagenes(contenido):
        agregar(f"imagen:{dia}:{modalidad}", "imagenologia",
                fecha=fecha(dia), modalidad=modalidad, region=region, hallazgos=hallazgos)

    return registros, omitidos


def _datos_estructurados(contenido: Dict[str, Any]) -> Iterable[Tuple[str, str, Optional[int]]]:
    datos = contenido.get("datos_paciente") or {}
    tipo = tipo_cancer(contenido)
    if tipo:
        yield "cancer_type", tipo, None

    detallados = {m["datos"].get("CANCER_TYPE_DETAILED", "") for m in contenido.get("muestras") or []}
    if tipo == "NSCLC" and len(detallados) == 1:
        histologia = _histologia_nsclc(detallados.pop())
        if histologia:
            yield "histology", histologia, None

    ecog = [e for e in contenido.get("eventos") or []
            if e["tipo"] == "Diagnosis" and e["atributos"].get("SUBTYPE") == "Performance Status"
            and (e["atributos"].get("ECOG") or "").isdigit()]
    if ecog:
        ultimo = max(ecog, key=lambda e: e.get("inicio") or 0)
        yield "ecog_ps", ultimo["atributos"]["ECOG"], ultimo.get("inicio")

    primarios = _diagnosticos_primarios(contenido)
    estadio = _estadio(contenido)
    if estadio:
        yield "ajcc_stage_at_diagnosis", estadio, primarios[0].get("inicio")

    if datos.get("STAGE_HIGHEST_RECORDED") == "Stage 4" or any(datos.get(s) == "Yes" for s in _SITIOS_DISTANTES):
        yield "metastatic_disease", "yes", None

    if tipo == "breast":
        her2, hr = _si_no(datos.get("HER2")), _si_no(datos.get("HR"))
        if her2:
            yield "her2_status", her2, None
        if hr:
            yield "hormone_receptor_status", hr, None
        if hr == "negative":
            # HR negativo en MSK-CHORD = RE y RP negativos. Con HR positivo no
            # se sabe cuál de los dos lo es: se deja faltante.
            yield "er_status", "negative", None
            yield "pr_status", "negative", None
        if her2 == "negative" and hr == "negative":
            yield "breast_subtype", "triple_negative", None
        elif her2 == "positive" or hr == "positive":
            yield "breast_subtype", "other", None

    pdl1 = [e for e in contenido.get("eventos") or [] if e["tipo"] == "Pathology" and "PDL1_POSITIVE" in e["atributos"]]
    if pdl1:
        ultimo = max(pdl1, key=lambda e: e.get("inicio") or 0)
        valor = _si_no(ultimo["atributos"]["PDL1_POSITIVE"])
        if valor:
            # Solo positivo/negativo, sin TPS ni CPS. Va como variable propia
            # y no como biomarcador "PD-L1": así no cumple el ítem de TPS de
            # HC-05, del que depende la elección de inmunoterapia.
            yield "pdl1_positive_without_tps", valor, ultimo.get("inicio")

    tabaquismo = datos.get("SMOKING_PREDICTIONS_3_CLASSES")
    if tabaquismo and tabaquismo != "Unknown":
        # Es una predicción por NLP: se guarda aparte de `smoking_status`
        # para que las reglas de tratamiento no la tomen como dato confirmado.
        yield "smoking_status_nlp_prediction", tabaquismo, None

    estado_vital = {"0:LIVING": "vivo", "1:DECEASED": "fallecido"}.get(datos.get("OS_STATUS", ""))
    if estado_vital:
        yield "vital_status", estado_vital, None


def _biomarcadores(contenido: Dict[str, Any]) -> Iterable[Tuple[str, str, Optional[int]]]:
    datos = contenido.get("datos_paciente") or {}
    tipo = tipo_cancer(contenido)
    muestras = {m["id"]: m for m in contenido.get("muestras") or []}
    dia_muestra = {
        e["atributos"].get("SAMPLE_ID"): e.get("inicio")
        for e in contenido.get("eventos") or [] if e["tipo"] == "Sample acquisition"
    }

    if tipo == "breast":
        her2, hr = _si_no(datos.get("HER2")), _si_no(datos.get("HR"))
        if her2:
            yield "HER2", _positivo(her2), None
        if hr:
            yield "Receptores hormonales (HR)", _positivo(hr), None
        if hr == "negative":
            yield "RE", "negativo", None
            yield "RP", "negativo", None

    for muestra_id, muestra in sorted(muestras.items()):
        d = muestra["datos"]
        dia = dia_muestra.get(muestra_id)
        if d.get("MSI_TYPE"):
            msi = {"Stable": "estable (MSS)", "Instable": "inestable (MSI-H)", "Indeterminate": "indeterminado",
                   "Do not report": "no concluyente (el laboratorio indicó no reportarlo)"}
            yield "MSI", f"{msi.get(d['MSI_TYPE'], d['MSI_TYPE'])} — muestra {muestra_id}", dia
        if d.get("TMB_NONSYNONYMOUS"):
            try:
                tmb = f"{float(d['TMB_NONSYNONYMOUS']):.1f} mut/Mb"
            except ValueError:
                tmb = d["TMB_NONSYNONYMOUS"]
            yield "TMB", f"{tmb} — muestra {muestra_id}", dia

    for gen, resultado, muestra_id in _genomica(contenido):
        yield gen, f"{resultado} — muestra {muestra_id}", dia_muestra.get(muestra_id)


def _genomica(contenido: Dict[str, Any]) -> Iterable[Tuple[str, str, str]]:
    """``(gen, resultado, muestra)``. ``genes_evaluados`` es
    ``{muestra: {"mutaciones": [...], "fusiones": [...]}}`` con los genes
    que el panel de esa muestra cubre para cada tipo de alteración."""
    genes_fusiones = set(contenido.get("genes_fusiones") or ())
    hallazgos: Dict[Tuple[str, str], List[str]] = {}
    for m in contenido.get("mutaciones") or []:
        hallazgos.setdefault((m["gen"], m["muestra"]), []).append(
            f"mutación detectada: {m['cambio_proteico'] or 'sin cambio proteico'} ({m['tipo'] or 'tipo no informado'})"
        )
    # Un mismo reordenamiento suele venir dos veces (ALK-EML4 y EML4-ALK):
    # se deja uno por par de genes y muestra, prefiriendo el sentido en que
    # el gen consultado (la quinasa) es el socio 3', que es la notación habitual.
    vistas = set()
    fusiones = sorted(
        contenido.get("fusiones") or [],
        key=lambda f: not any((f["descripcion"] or "").rstrip(") ").endswith(g) for g in genes_fusiones),
    )
    for f in fusiones:
        genes = [g for g in (f["gen_1"], f["gen_2"]) if g]
        par = (frozenset(genes), f["muestra"])
        if par in vistas:
            continue
        vistas.add(par)
        # "Protein fusion: in frame (EML4-ALK)" -> "EML4-ALK (Protein fusion: in frame)"
        partes = re.fullmatch(r"(.*?)\s*\(([^()]+)\)\s*", f["descripcion"] or "")
        texto = f"{partes.group(2)} ({partes.group(1)})" if partes else "-".join(genes) + (
            f" ({f['descripcion']})" if f["descripcion"] else "")
        for gen in set(genes) & genes_fusiones:
            hallazgos.setdefault((gen, f["muestra"]), []).append(f"fusión detectada: {texto}")
    for (gen, muestra), textos in sorted(hallazgos.items()):
        yield gen, "; ".join(sorted(set(textos))), muestra

    paneles = {m["id"]: m["datos"].get("GENE_PANEL") for m in contenido.get("muestras") or []}
    for muestra, por_tipo in sorted((contenido.get("genes_evaluados") or {}).items()):
        sufijo = f" (panel {paneles[muestra]})" if paneles.get(muestra) else ""
        for clave, alteracion in (("mutaciones", "mutación"), ("fusiones", "fusión")):
            for gen in sorted(por_tipo.get(clave) or ()):
                if (gen, muestra) not in hallazgos:
                    yield gen, f"{alteracion} no detectada{sufijo}", muestra


def _imagenes(contenido: Dict[str, Any]) -> Iterable[Tuple[int, str, str, str]]:
    """Agrupa los eventos NLP de radiología por (día, modalidad)."""
    grupos: Dict[Tuple[int, str], List[Dict[str, str]]] = {}
    for e in contenido.get("eventos") or []:
        a = e["atributos"]
        if e["tipo"] != "Diagnosis" or a.get("SUBTYPE") not in {"Progression", "HasCancer", "Tumor Sites"}:
            continue
        procedimiento = a.get("PROCEDURE_TYPE") or a.get("SOURCE_SPECIFIC") or "no especificada"
        grupos.setdefault((e.get("inicio") or 0, procedimiento), []).append(a)

    for (dia, procedimiento), eventos in sorted(grupos.items()):
        regiones = [nombre for clave, nombre in _REGIONES
                    if any(str(a.get(clave, "")).upper() in {"1", "TRUE"} for a in eventos)]
        partes = ["Informe radiológico procesado con NLP (MSK-CHORD); no es el texto original del informe."]
        for a in eventos:
            if a["SUBTYPE"] == "HasCancer":
                partes.append(f"Cáncer presente: {_si_no_es(a.get('HAS_CANCER'))} "
                              f"(probabilidad {_prob(a.get('NLP_HAS_CANCER_PROBABILITY'))}).")
            elif a["SUBTYPE"] == "Progression":
                partes.append(f"Progresión: {_si_no_es(a.get('PROGRESSION'))} "
                              f"(probabilidad {_prob(a.get('NLP_PROGRESSION_PROBABILITY'))}).")
        sitios = sorted({_SITIOS.get(a["TUMOR_SITE"], a["TUMOR_SITE"]) for a in eventos if a.get("TUMOR_SITE")})
        if sitios:
            partes.append(f"Sitios tumorales: {', '.join(sitios)}.")
        yield dia, _MODALIDADES.get(procedimiento, procedimiento), ", ".join(regiones) or "no especificada", " ".join(partes)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------


def _histologia_nsclc(detallado: str) -> Optional[str]:
    texto = detallado.lower()
    if "squamous" in texto:
        return "squamous"
    if "adenocarcinoma" in texto or "large cell" in texto:
        return "non_squamous"
    return None


def _si_no(valor: Optional[str]) -> Optional[str]:
    return {"yes": "positive", "no": "negative"}.get((valor or "").strip().lower())


def _positivo(valor: str) -> str:
    return "positivo" if valor == "positive" else "negativo"


def _si_no_es(valor: Optional[str]) -> str:
    return {"Y": "sí", "N": "no"}.get((valor or "").upper(), "no concluyente")


def _prob(valor: Optional[str]) -> str:
    try:
        return f"{float(valor):.2f}"
    except (TypeError, ValueError):
        return "no informada"


def _rango(prueba: str, unidad: Optional[str]) -> Optional[str]:
    esperado = RANGOS_LABORATORIO.get(prueba.upper())
    if esperado and (unidad or "").strip().lower() == esperado[0]:
        return esperado[1]
    return None


def _fuera_de_rango(valor: str, rango: Optional[str]) -> bool:
    coincidencia = re.fullmatch(r"\s*(-?[\d.]+)\s*-\s*(-?[\d.]+)\s*", rango or "")
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return False
    return bool(coincidencia) and not (float(coincidencia.group(1)) <= numero <= float(coincidencia.group(2)))


def _periodo(fecha: Callable[[Optional[int]], str], inicio: Optional[int], fin: Optional[int]) -> str:
    if inicio is None:
        return ""
    if fin is None or fin == inicio:
        return f", {fecha(inicio)}"
    return f", del {fecha(inicio)} al {fecha(fin)}"


def _describir_primario(a: Dict[str, str]) -> str:
    texto = f"Diagnóstico primario (registro de tumores): {a.get('DX_DESCRIPTION') or 'sin descripción'}"
    extras = []
    if a.get("AJCC"):
        extras.append(f"AJCC {a['AJCC']}")
    if a.get("SUMMARY") not in (None, "", "N/A"):
        extras.append(a["SUMMARY"])
    return f"{texto} ({', '.join(extras)})" if extras else texto
