"""HC-01 — Integración de historia clínica externa.

Como oncólogo, quiero integrar la historia clínica previa del paciente (de
otros sistemas o en PDF/HL7), para no reconstruir manualmente sus
antecedentes.

Tres vías de entrada, según lo que ofrezca la institución de origen:

    - **FHIR R4** (``importar_bundle_fhir`` / ``FuenteFHIR``): un Bundle con
      Observation (laboratorio), DiagnosticReport/ImagingStudy (imagen) y
      Condition/Procedure/MedicationStatement (antecedentes).
    - **HL7 v2** (``importar_mensaje_hl7``): mensajes ORU^R01 con segmentos
      PID/OBR/OBX, el formato de resultados más común en sistemas
      hospitalarios que todavía no exponen FHIR.
    - **PDF** (``cargar_historia_pdf``): cuando no hay integración, el
      documento se asocia al paciente reutilizando DOC-01
      (``documentos_clinicos.carga_documentos``) y queda consultable
      aunque no esté estructurado (AC2).

Decisiones de diseño:

    - Nada se importa sin verificar primero que el paciente del mensaje
      externo es el mismo del expediente (identificación). Un mensaje de
      otro paciente se rechaza completo: es el error más grave posible en
      una integración clínica.
    - La importación de un mensaje es todo-o-nada (una transacción). Si
      algo falla a mitad de camino no quedan datos a medias.
    - ``sincronizar_paciente`` nunca propaga excepciones de la fuente
      externa: el fallo queda en ``sincronizaciones_externas`` y se
      devuelve un ``ResultadoSincronizacion`` con el mensaje para el
      usuario (AC3). El resto del expediente sigue siendo accesible porque
      no se tocó.
    - Re-sincronizar es idempotente: cada recurso externo se registra en
      ``registros_importados`` con su identificador de origen y no se
      vuelve a insertar.
    - Los laboratorios se guardan tal como llegan (con ``alterado`` según
      su rango de referencia). Las alertas por valor crítico y los
      conflictos de marcador son responsabilidad de HC-02.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple, Union

from historia_clinica.db import ahora_iso
from historia_clinica_mock.repository import Paciente, obtener_paciente

FORMATO_FHIR = "fhir"
FORMATO_HL7V2 = "hl7v2"
FORMATO_PDF = "pdf"


class ErrorIntegracion(Exception):
    """La fuente externa respondió algo que no se puede importar con seguridad."""


class PacienteNoCoincideError(ErrorIntegracion):
    """El mensaje externo corresponde a otro paciente (identificación distinta)."""


@dataclass(frozen=True)
class ResultadoSincronizacion:
    exito: bool
    sincronizacion_id: Optional[int]
    registros_importados: int = 0
    registros_omitidos: int = 0
    #: Mensaje listo para mostrar al usuario (éxito o causa del fallo).
    mensaje: str = ""
    #: Id del documento en DOC-01 cuando la vía fue un PDF.
    documento_id: Optional[int] = None


@dataclass(frozen=True)
class Sincronizacion:
    id: int
    paciente_id: int
    fuente: str
    formato: str
    estado: str
    registros_importados: int
    registros_omitidos: int
    mensaje: Optional[str]
    fecha: str


@dataclass(frozen=True)
class AntecedenteExterno:
    id: int
    paciente_id: int
    tipo: str
    descripcion: str
    fecha: Optional[str]
    fuente: str


class FuenteHistoriaExterna(Protocol):
    """Un sistema externo del que se puede traer la historia de un paciente.

    ``obtener_historia`` puede lanzar cualquier excepción (red, timeout,
    respuesta inválida): ``sincronizar_paciente`` la captura y la registra.

    Una fuente con un formato propio (p. ej. ``cbioportal.FuenteCBioPortal``)
    expone además ``traducir(contenido, paciente) -> (registros, omitidos)``,
    que convierte su respuesta en ``RegistroExterno``; así reutiliza la
    verificación, la idempotencia y la transacción de esta historia.
    """

    nombre: str
    formato: str

    def obtener_historia(self, identificacion: str) -> Union[str, Dict[str, Any]]:
        ...


class FuenteFHIR:
    """Servidor FHIR R4: busca el Patient por identificación y trae su
    ``$everything``. ``session`` es inyectable (``requests.Session`` o un
    doble de prueba)."""

    formato = FORMATO_FHIR

    def __init__(self, nombre: str, base_url: str, session: Any = None, timeout: float = 10.0):
        self.nombre = nombre
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        if session is None:
            import requests

            session = requests.Session()
        self.session = session

    def _get(self, url: str, **params: Any) -> Dict[str, Any]:
        respuesta = self.session.get(
            url, params=params or None, headers={"Accept": "application/fhir+json"}, timeout=self.timeout
        )
        if respuesta.status_code != 200:
            raise ErrorIntegracion(f"El servidor FHIR respondió HTTP {respuesta.status_code} en {url}.")
        return respuesta.json()

    def obtener_historia(self, identificacion: str) -> Dict[str, Any]:
        busqueda = self._get(f"{self.base_url}/Patient", identifier=identificacion)
        entradas = busqueda.get("entry") or []
        if not entradas:
            raise ErrorIntegracion(
                f"El sistema externo no tiene ningún paciente con identificación {identificacion}."
            )
        if len(entradas) > 1:
            raise ErrorIntegracion(
                f"El sistema externo devolvió {len(entradas)} pacientes con la identificación "
                f"{identificacion}; no se importa nada hasta resolver la ambigüedad."
            )
        paciente_externo_id = entradas[0]["resource"]["id"]
        return self._get(f"{self.base_url}/Patient/{paciente_externo_id}/$everything")


# ---------------------------------------------------------------------------
# Punto de entrada principal (AC1 + AC3)
# ---------------------------------------------------------------------------


def sincronizar_paciente(
    conn: sqlite3.Connection,
    paciente_id: int,
    fuente: FuenteHistoriaExterna,
    ahora: Optional[datetime] = None,
) -> ResultadoSincronizacion:
    """Trae la historia del paciente desde ``fuente`` y la carga en su expediente.

    Nunca lanza por un fallo de la fuente o del contenido: lo registra y lo
    devuelve como ``exito=False`` con un mensaje para el usuario.
    """
    paciente = _paciente_o_error(conn, paciente_id)
    try:
        contenido = fuente.obtener_historia(paciente.identificacion)
    except Exception as exc:  # noqa: BLE001 -- cualquier fallo de la fuente es un fallo de sincronización
        return _registrar_fallo(conn, paciente_id, fuente.nombre, fuente.formato, _describir(exc), ahora)

    if getattr(fuente, "traducir", None) is not None:
        return importar_historia(conn, paciente_id, contenido, fuente, ahora)
    if fuente.formato == FORMATO_FHIR:
        return importar_bundle_fhir(conn, paciente_id, contenido, fuente.nombre, ahora)
    if fuente.formato == FORMATO_HL7V2:
        return importar_mensaje_hl7(conn, paciente_id, contenido, fuente.nombre, ahora)
    return _registrar_fallo(
        conn, paciente_id, fuente.nombre, fuente.formato, f"Formato de fuente no soportado: {fuente.formato!r}.", ahora
    )


def importar_historia(
    conn: sqlite3.Connection,
    paciente_id: int,
    contenido: Any,
    fuente: FuenteHistoriaExterna,
    ahora: Optional[datetime] = None,
) -> ResultadoSincronizacion:
    """Importa un ``contenido`` ya obtenido de una fuente con ``traducir``
    (evita volver a pedirlo a la red cuando quien llama ya lo tiene)."""
    return _importar(conn, paciente_id, fuente.nombre, fuente.formato, contenido, fuente.traducir, ahora)


def importar_bundle_fhir(
    conn: sqlite3.Connection,
    paciente_id: int,
    bundle: Union[str, Dict[str, Any]],
    fuente: str,
    ahora: Optional[datetime] = None,
) -> ResultadoSincronizacion:
    return _importar(conn, paciente_id, fuente, FORMATO_FHIR, bundle, _registros_desde_fhir, ahora)


def importar_mensaje_hl7(
    conn: sqlite3.Connection,
    paciente_id: int,
    mensaje: str,
    fuente: str,
    ahora: Optional[datetime] = None,
) -> ResultadoSincronizacion:
    return _importar(conn, paciente_id, fuente, FORMATO_HL7V2, mensaje, _registros_desde_hl7, ahora)


# ---------------------------------------------------------------------------
# AC2: sin integración -> PDF asociado al paciente (vía DOC-01)
# ---------------------------------------------------------------------------


def cargar_historia_pdf(
    conn: sqlite3.Connection,
    conn_documentos: sqlite3.Connection,
    paciente_id: int,
    nombre_archivo: str,
    contenido: bytes,
    cargado_por: str,
    directorio_almacenamiento: Union[str, Path],
    fuente: str = "carga manual",
    ahora: Optional[datetime] = None,
) -> ResultadoSincronizacion:
    """Asocia un PDF de historia clínica al paciente, aunque no esté estructurado.

    El almacenamiento, la verificación de la firma real del PDF y el
    historial de documentos son los de DOC-01; aquí solo se exige que sea
    un PDF y se deja constancia en el historial de sincronizaciones, para
    que el expediente muestre de dónde salió cada parte de la historia.
    """
    from documentos_clinicos.carga_documentos import DocumentoInvalidoError, cargar_documento_clinico

    _paciente_o_error(conn, paciente_id)
    if Path(nombre_archivo).suffix.lower() != ".pdf":
        return _registrar_fallo(
            conn, paciente_id, fuente, FORMATO_PDF,
            f"La historia clínica externa debe cargarse como PDF (.pdf); se recibió '{nombre_archivo}'.",
            ahora,
        )
    try:
        documento = cargar_documento_clinico(
            conn_documentos, conn, paciente_id, nombre_archivo, contenido, cargado_por,
            directorio_almacenamiento, ahora=ahora,
        )
    except DocumentoInvalidoError as exc:
        return _registrar_fallo(conn, paciente_id, fuente, FORMATO_PDF, str(exc), ahora)

    mensaje = (
        f"Historia clínica '{nombre_archivo}' asociada al paciente como documento no estructurado "
        f"(documento #{documento.id}); disponible para consulta en su historial de documentos."
    )
    sincronizacion_id = _insertar_sincronizacion(
        conn, paciente_id, fuente, FORMATO_PDF, "documento_no_estructurado", 0, 0, mensaje, ahora
    )
    conn.commit()
    return ResultadoSincronizacion(
        exito=True, sincronizacion_id=sincronizacion_id, mensaje=mensaje, documento_id=documento.id
    )


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------


def listar_sincronizaciones(conn: sqlite3.Connection, paciente_id: int) -> Tuple[Sincronizacion, ...]:
    """Historial de integraciones del paciente, de la más reciente a la más antigua."""
    filas = conn.execute(
        "SELECT * FROM sincronizaciones_externas WHERE paciente_id = ? ORDER BY id DESC", (paciente_id,)
    ).fetchall()
    return tuple(Sincronizacion(**dict(f)) for f in filas)


def antecedentes_externos_de_paciente(
    conn: sqlite3.Connection, paciente_id: int
) -> Tuple[AntecedenteExterno, ...]:
    filas = conn.execute(
        "SELECT * FROM antecedentes_externos WHERE paciente_id = ? ORDER BY fecha, id", (paciente_id,)
    ).fetchall()
    return tuple(AntecedenteExterno(**dict(f)) for f in filas)


# ---------------------------------------------------------------------------
# Núcleo de importación
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegistroExterno:
    """Un recurso externo ya traducido a una fila local."""

    identificador_externo: str
    #: laboratorios | imagenologia | biomarcadores | datos_clinicos_estructurados | antecedentes_externos
    tabla: str
    valores: Dict[str, Any]


_Registro = RegistroExterno


def _importar(conn, paciente_id, fuente, formato, contenido, traductor, ahora) -> ResultadoSincronizacion:
    paciente = _paciente_o_error(conn, paciente_id)
    try:
        registros, omitidos = traductor(contenido, paciente)
    except Exception as exc:  # noqa: BLE001
        return _registrar_fallo(conn, paciente_id, fuente, formato, _describir(exc), ahora)

    try:
        sincronizacion_id = _insertar_sincronizacion(conn, paciente_id, fuente, formato, "exitosa", 0, 0, None, ahora)
        importados = 0
        for registro in registros:
            ya_importado = conn.execute(
                "SELECT 1 FROM registros_importados WHERE fuente = ? AND identificador_externo = ?",
                (fuente, registro.identificador_externo),
            ).fetchone()
            if ya_importado:
                omitidos += 1
                continue
            fila_id = _insertar_registro(conn, paciente_id, fuente, registro)
            conn.execute(
                "INSERT INTO registros_importados "
                "(sincronizacion_id, fuente, identificador_externo, tabla_destino, fila_id) VALUES (?, ?, ?, ?, ?)",
                (sincronizacion_id, fuente, registro.identificador_externo, registro.tabla, fila_id),
            )
            importados += 1
        mensaje = (
            f"Historia sincronizada desde {fuente}: {importados} registro(s) nuevo(s) "
            f"cargado(s) al expediente, {omitidos} omitido(s)."
        )
        conn.execute(
            "UPDATE sincronizaciones_externas SET registros_importados = ?, registros_omitidos = ?, mensaje = ? "
            "WHERE id = ?",
            (importados, omitidos, mensaje, sincronizacion_id),
        )
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        return _registrar_fallo(conn, paciente_id, fuente, formato, _describir(exc), ahora)

    return ResultadoSincronizacion(
        exito=True,
        sincronizacion_id=sincronizacion_id,
        registros_importados=importados,
        registros_omitidos=omitidos,
        mensaje=mensaje,
    )


def _insertar_registro(conn: sqlite3.Connection, paciente_id: int, fuente: str, registro: _Registro) -> int:
    valores = dict(registro.valores, paciente_id=paciente_id)
    if registro.tabla == "antecedentes_externos":
        valores["fuente"] = fuente
    columnas = ", ".join(valores)
    marcadores = ", ".join("?" for _ in valores)
    cursor = conn.execute(
        f"INSERT INTO {registro.tabla} ({columnas}) VALUES ({marcadores})", tuple(valores.values())
    )
    return cursor.lastrowid


def _insertar_sincronizacion(conn, paciente_id, fuente, formato, estado, importados, omitidos, mensaje, ahora) -> int:
    cursor = conn.execute(
        "INSERT INTO sincronizaciones_externas "
        "(paciente_id, fuente, formato, estado, registros_importados, registros_omitidos, mensaje, fecha) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (paciente_id, fuente, formato, estado, importados, omitidos, mensaje, ahora_iso(ahora)),
    )
    return cursor.lastrowid


def _registrar_fallo(conn, paciente_id, fuente, formato, causa, ahora) -> ResultadoSincronizacion:
    mensaje = (
        f"No se pudo sincronizar la historia clínica desde {fuente}: {causa} "
        "El resto del expediente sigue disponible; puede reintentar más tarde o cargar la historia en PDF."
    )
    sincronizacion_id = _insertar_sincronizacion(conn, paciente_id, fuente, formato, "fallida", 0, 0, mensaje, ahora)
    conn.commit()
    return ResultadoSincronizacion(exito=False, sincronizacion_id=sincronizacion_id, mensaje=mensaje)


def _paciente_o_error(conn: sqlite3.Connection, paciente_id: int) -> Paciente:
    paciente = obtener_paciente(conn, paciente_id)
    if paciente is None:
        raise ValueError(f"No existe ningún paciente con id={paciente_id}.")
    return paciente


def _describir(exc: Exception) -> str:
    texto = str(exc).strip()
    if isinstance(exc, ErrorIntegracion) and texto:
        return texto
    return f"{type(exc).__name__}: {texto}" if texto else type(exc).__name__


def _verificar_identidad(paciente: Paciente, identificaciones_externas: List[str]) -> None:
    if paciente.identificacion not in {i.strip() for i in identificaciones_externas if i}:
        raise PacienteNoCoincideError(
            "El mensaje externo corresponde a otro paciente (identificación "
            f"{', '.join(identificaciones_externas) or 'ausente'}; se esperaba {paciente.identificacion}). "
            "No se importó ningún dato."
        )


def _calcular_alterado(valor: str, rango: Optional[str]) -> bool:
    """True si ``valor`` numérico cae fuera de un rango ``bajo-alto``."""
    if not rango:
        return False
    coincidencia = re.fullmatch(r"\s*(-?[\d.]+)\s*-\s*(-?[\d.]+)\s*", rango)
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return False
    if not coincidencia:
        return False
    bajo, alto = float(coincidencia.group(1)), float(coincidencia.group(2))
    return not (bajo <= numero <= alto)


def _fecha(valor: Optional[str]) -> Optional[str]:
    return valor[:10] if valor else None


# ---------------------------------------------------------------------------
# FHIR R4
# ---------------------------------------------------------------------------

_INTERPRETACIONES_ANORMALES = {"H", "HH", "L", "LL", "A", "AA", "HU", "LU"}
_CATEGORIAS_IMAGEN = {"RAD", "imaging", "radiology"}
_TIPOS_ANTECEDENTE = {
    "Condition": "condicion",
    "Procedure": "procedimiento",
    "MedicationStatement": "medicacion",
}


def _texto_codigo(concepto: Optional[Dict[str, Any]]) -> str:
    if not concepto:
        return ""
    if concepto.get("text"):
        return concepto["text"]
    for coding in concepto.get("coding") or []:
        if coding.get("display"):
            return coding["display"]
        if coding.get("code"):
            return coding["code"]
    return ""


def _codigos_categoria(recurso: Dict[str, Any]) -> set:
    codigos = set()
    for categoria in recurso.get("category") or []:
        for coding in categoria.get("coding") or []:
            if coding.get("code"):
                codigos.add(coding["code"])
    return codigos


def _registros_desde_fhir(contenido, paciente: Paciente) -> Tuple[List[_Registro], int]:
    bundle = json.loads(contenido) if isinstance(contenido, str) else contenido
    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
        raise ErrorIntegracion("La respuesta del sistema externo no es un Bundle FHIR válido.")

    recursos = [e.get("resource") or {} for e in bundle.get("entry") or []]
    pacientes = [r for r in recursos if r.get("resourceType") == "Patient"]
    if not pacientes:
        raise ErrorIntegracion("El Bundle FHIR no incluye el recurso Patient; no se puede verificar la identidad.")
    identificaciones = [i.get("value", "") for p in pacientes for i in p.get("identifier") or []]
    _verificar_identidad(paciente, identificaciones)

    registros: List[_Registro] = []
    omitidos = 0
    for recurso in recursos:
        tipo = recurso.get("resourceType")
        externo = f"{tipo}/{recurso.get('id')}"
        if tipo == "Patient":
            continue
        if tipo == "Observation" and "laboratory" in _codigos_categoria(recurso):
            registro = _laboratorio_fhir(externo, recurso)
        elif tipo == "DiagnosticReport" and _codigos_categoria(recurso) & _CATEGORIAS_IMAGEN:
            registro = _imagen_desde_reporte_fhir(externo, recurso)
        elif tipo == "ImagingStudy":
            registro = _imagen_desde_estudio_fhir(externo, recurso)
        elif tipo in _TIPOS_ANTECEDENTE:
            registro = _antecedente_fhir(externo, tipo, recurso)
        else:
            registro = None
        if registro is None:
            omitidos += 1
        else:
            registros.append(registro)
    return registros, omitidos


def _laboratorio_fhir(externo: str, obs: Dict[str, Any]) -> Optional[_Registro]:
    prueba = _texto_codigo(obs.get("code"))
    fecha = _fecha(obs.get("effectiveDateTime") or obs.get("issued"))
    cantidad = obs.get("valueQuantity") or {}
    if "value" in cantidad:
        valor, unidad = str(cantidad["value"]), cantidad.get("unit") or cantidad.get("code")
    elif obs.get("valueString"):
        valor, unidad = obs["valueString"], None
    else:
        return None
    if not prueba or not fecha:
        return None

    rango = None
    for referencia in obs.get("referenceRange") or []:
        bajo, alto = (referencia.get("low") or {}).get("value"), (referencia.get("high") or {}).get("value")
        if bajo is not None and alto is not None:
            rango = f"{bajo}-{alto}"
            break
    interpretaciones = {
        c.get("code") for i in obs.get("interpretation") or [] for c in i.get("coding") or []
    }
    alterado = bool(interpretaciones & _INTERPRETACIONES_ANORMALES) or _calcular_alterado(valor, rango)
    return _Registro(
        externo,
        "laboratorios",
        dict(fecha=fecha, prueba=prueba, valor=valor, unidad=unidad, rango_referencia=rango, alterado=int(alterado)),
    )


def _imagen_desde_reporte_fhir(externo: str, reporte: Dict[str, Any]) -> Optional[_Registro]:
    hallazgos = reporte.get("conclusion") or ""
    fecha = _fecha(reporte.get("effectiveDateTime") or reporte.get("issued"))
    if not hallazgos or not fecha:
        return None
    descripcion = _texto_codigo(reporte.get("code"))
    modalidad, _, region = descripcion.partition(" ")
    return _Registro(
        externo,
        "imagenologia",
        dict(fecha=fecha, modalidad=modalidad or "No especificada", region=region or "No especificada", hallazgos=hallazgos),
    )


def _imagen_desde_estudio_fhir(externo: str, estudio: Dict[str, Any]) -> Optional[_Registro]:
    fecha = _fecha(estudio.get("started"))
    if not fecha:
        return None
    modalidades = [m.get("code") for m in estudio.get("modality") or [] if m.get("code")]
    series = estudio.get("series") or []
    region = next((s["bodySite"].get("display") for s in series if (s.get("bodySite") or {}).get("display")), None)
    descripcion = estudio.get("description") or "Estudio de imagen importado (sin reporte asociado)."
    return _Registro(
        externo,
        "imagenologia",
        dict(
            fecha=fecha,
            modalidad="/".join(modalidades) or "No especificada",
            region=region or "No especificada",
            hallazgos=descripcion,
        ),
    )


def _antecedente_fhir(externo: str, tipo: str, recurso: Dict[str, Any]) -> Optional[_Registro]:
    concepto = recurso.get("code") or recurso.get("medicationCodeableConcept")
    descripcion = _texto_codigo(concepto)
    if not descripcion:
        return None
    fecha = _fecha(
        recurso.get("onsetDateTime")
        or recurso.get("recordedDate")
        or recurso.get("performedDateTime")
        or (recurso.get("effectivePeriod") or {}).get("start")
        or recurso.get("effectiveDateTime")
    )
    return _Registro(
        externo, "antecedentes_externos", dict(tipo=_TIPOS_ANTECEDENTE[tipo], descripcion=descripcion, fecha=fecha)
    )


# ---------------------------------------------------------------------------
# HL7 v2 (ORU^R01)
# ---------------------------------------------------------------------------


def _fecha_hl7(valor: str) -> Optional[str]:
    digitos = re.sub(r"\D", "", valor or "")
    if len(digitos) < 8:
        return None
    return f"{digitos[0:4]}-{digitos[4:6]}-{digitos[6:8]}"


_ESCAPES_HL7 = {"\\F\\": "|", "\\S\\": "^", "\\T\\": "&", "\\R\\": "~", "\\E\\": "\\"}


def _desescapar_hl7(valor: str) -> str:
    r"""Decodifica las secuencias de escape estándar de HL7 v2 (p. ej. ``10\S\3/uL``)."""
    return re.sub(r"\\[FSTRE]\\", lambda m: _ESCAPES_HL7[m.group(0)], valor)


def _registros_desde_hl7(contenido, paciente: Paciente) -> Tuple[List[_Registro], int]:
    if not isinstance(contenido, str) or not contenido.lstrip().startswith("MSH"):
        raise ErrorIntegracion("El mensaje HL7 v2 no empieza con un segmento MSH.")
    segmentos = [s for s in re.split(r"\r\n|\r|\n", contenido.strip()) if s]
    separador = segmentos[0][3]
    campos_msh = segmentos[0].split(separador)
    componente = campos_msh[1][0] if len(campos_msh) > 1 and campos_msh[1] else "^"
    # MSH-1 es el propio separador, así que MSH-n queda en el índice n-1.
    control_id = campos_msh[9] if len(campos_msh) > 9 else ""
    tipo_mensaje = campos_msh[8] if len(campos_msh) > 8 else ""
    if not tipo_mensaje.startswith(f"ORU{componente}R01"):
        raise ErrorIntegracion(f"Tipo de mensaje HL7 no soportado: {tipo_mensaje!r} (se espera ORU^R01).")
    if not control_id:
        raise ErrorIntegracion("El mensaje HL7 no trae identificador de control (MSH-10).")

    def campo(partes: List[str], n: int) -> str:
        return partes[n] if len(partes) > n else ""

    pids = [s.split(separador) for s in segmentos if s.startswith("PID")]
    if not pids:
        raise ErrorIntegracion("El mensaje HL7 no incluye el segmento PID; no se puede verificar la identidad.")
    identificaciones = [
        repeticion.split(componente)[0] for repeticion in campo(pids[0], 3).split("~")
    ]
    _verificar_identidad(paciente, identificaciones)

    registros: List[_Registro] = []
    omitidos = 0
    fecha_obr: Optional[str] = None
    for segmento in segmentos:
        partes = segmento.split(separador)
        if partes[0] == "OBR":
            fecha_obr = _fecha_hl7(campo(partes, 7))
        elif partes[0] == "OBX":
            identificador = campo(partes, 3).split(componente)
            prueba = _desescapar_hl7(
                identificador[1] if len(identificador) > 1 and identificador[1] else identificador[0]
            )
            valor = _desescapar_hl7(campo(partes, 5))
            fecha = _fecha_hl7(campo(partes, 14)) or fecha_obr
            if not prueba or not valor or not fecha:
                omitidos += 1
                continue
            rango = campo(partes, 7) or None
            banderas = set(campo(partes, 8).split("~")) - {""}
            alterado = bool(banderas & _INTERPRETACIONES_ANORMALES) or _calcular_alterado(valor, rango)
            registros.append(
                _Registro(
                    f"{control_id}/OBX-{campo(partes, 1) or len(registros) + 1}",
                    "laboratorios",
                    dict(
                        fecha=fecha,
                        prueba=prueba,
                        valor=valor,
                        unidad=_desescapar_hl7(campo(partes, 6).split(componente)[0]) or None,
                        rango_referencia=rango,
                        alterado=int(alterado),
                    ),
                )
            )
    return registros, omitidos
