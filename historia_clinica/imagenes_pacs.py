"""HC-03 — Integración de imágenes diagnósticas (DICOM/PACS).

Como oncólogo, quiero integrar las imágenes diagnósticas del paciente
(idealmente por DICOM/PACS) para revisarlas junto al resto de su historia
clínica.

Qué hace (y qué no):

    - **No es un visor DICOM.** El riesgo de la historia es construir uno
      completo; la decisión (ver ``docs/historia_clinica_imagenes_pacs.md``)
      es *incrustar un visor de terceros* (OHIF, el de la propia
      institución…). Este módulo solo le entrega al visor el
      ``StudyInstanceUID`` mediante una plantilla de URL configurable.
    - Habla con el PACS por **DICOMweb (QIDO-RS)**, la interfaz HTTP
      estándar de cualquier PACS moderno (Orthanc, dcm4chee, PACS
      comerciales). ``FuenteDICOMweb`` recibe la sesión HTTP inyectada, igual
      que ``FuenteFHIR`` de HC-01, y cualquier otra fuente que cumpla
      ``FuentePACS`` sirve (p. ej. un doble de prueba).
    - Cada estudio se enlaza a su **informe** (la fila de ``imagenologia``
      que ya existe en el expediente, p. ej. por HC-01) solo cuando el
      enlace es único: misma fecha y modalidad compatible. Si hay cero o
      varios candidatos no se adivina (mismo criterio que IA-06): el estudio
      queda sin informe asociado.

Decisiones de diseño (misma línea que HC-01):

    - Identidad primero: cada estudio devuelto por el PACS debe traer el
      mismo ``PatientID`` del expediente y, si trae nombre, coincidir con
      él. Un estudio de otro paciente se rechaza y se cuenta; nunca se
      muestra.
    - AC2 — fallo explícito: ``sincronizar_estudios``, ``estudios_del_expediente``
      y ``abrir_visor`` nunca propagan excepciones del PACS ni fallan en
      silencio: devuelven un resultado con ``disponible=False`` y un mensaje
      listo para el usuario, y dejan una fila ``fallida`` en
      ``consultas_pacs``. El expediente y los informes siguen accesibles.
    - Degradación elegante: el índice local ``estudios_pacs`` permite seguir
      listando los estudios (marcados como "última sincronización") cuando
      el PACS no responde.
"""

from __future__ import annotations

import base64
import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol, Tuple
from urllib.parse import quote, urlparse

from expediente.repository import imagenologia_de_paciente, obtener_paciente
from historia_clinica.db import ahora_iso, normalizar_texto
from historia_clinica.laboratorios import nombres_coinciden

TIPO_LISTADO = "listado"
TIPO_VISOR = "visor"
ESTADO_EXITOSA = "exitosa"
ESTADO_FALLIDA = "fallida"

#: Variables de entorno de la integración real (ninguna es obligatoria: sin
#: ellas la integración se informa como "no configurada", no como un error).
ENV_PACS_URL = "COPILOTO_PACS_URL"
ENV_PACS_NOMBRE = "COPILOTO_PACS_NOMBRE"
ENV_PACS_TOKEN = "COPILOTO_PACS_TOKEN"
ENV_PACS_USUARIO = "COPILOTO_PACS_USUARIO"
ENV_PACS_PASSWORD = "COPILOTO_PACS_PASSWORD"
ENV_VISOR_URL = "COPILOTO_VISOR_URL"

# Etiquetas DICOM (formato DICOM JSON: grupo+elemento en mayúsculas).
_TAG_STUDY_UID = "0020000D"
_TAG_FECHA = "00080020"
_TAG_ACCESSION = "00080050"
_TAG_MODALIDADES_ESTUDIO = "00080061"
_TAG_MODALIDAD = "00080060"
_TAG_DESCRIPCION = "00081030"
_TAG_PATIENT_NAME = "00100010"
_TAG_PATIENT_ID = "00100020"
_TAG_N_SERIES = "00201206"
_TAG_N_INSTANCIAS = "00201208"

_UID_RE = re.compile(r"^[0-9]+(\.[0-9]+)*$")
_UID_MAX = 64

#: Modalidad DICOM -> palabras con las que el expediente nombra ese estudio.
_MODALIDADES: Dict[str, Tuple[str, ...]] = {
    "CT": ("tomografia", "tc", "ct", "tac"),
    "MR": ("resonancia", "rm", "mri", "rmn"),
    "US": ("ecografia", "ultrasonido", "eco"),
    "MG": ("mamografia", "mastografia"),
    "PT": ("pet", "pet/ct", "pet ct"),
    "NM": ("gammagrafia", "spect", "medicina nuclear"),
    "CR": ("radiografia", "rx", "rayos x"),
    "DX": ("radiografia", "rx", "rayos x"),
    "XA": ("angiografia",),
}


class ErrorPACS(Exception):
    """El PACS respondió algo que no se puede usar (HTTP, JSON o formato)."""


class ErrorConfiguracionVisor(ValueError):
    """La plantilla de URL del visor no es válida."""


# --------------------------------------------------------------------------
# Modelos
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class EstudioDICOM:
    """Un estudio tal como lo describe el PACS, ya normalizado."""

    study_uid: str
    patient_id: str
    patient_name: Optional[str]
    fecha: Optional[str]
    modalidad: Optional[str]
    descripcion: Optional[str]
    accession_number: Optional[str] = None
    series: Optional[int] = None
    instancias: Optional[int] = None


@dataclass(frozen=True)
class InformeImagen:
    """Informe de imagen del expediente asociado a un estudio."""

    imagenologia_id: int
    fecha: str
    modalidad: str
    region: str
    texto: str


@dataclass(frozen=True)
class EstudioPACS:
    """Estudio indexado, listo para mostrarse en el expediente (AC1)."""

    id: int
    paciente_id: int
    pacs: str
    study_uid: str
    fecha: Optional[str]
    modalidad: Optional[str]
    descripcion: Optional[str]
    accession_number: Optional[str]
    series: Optional[int]
    instancias: Optional[int]
    sincronizado_en: str
    informe: Optional[InformeImagen] = None
    #: URL del visor incrustable; ``None`` si no hay visor configurado.
    visor_url: Optional[str] = None


@dataclass(frozen=True)
class ResultadoSincronizacionPACS:
    exito: bool
    pacs: str
    estudios_indexados: int = 0
    estudios_rechazados: int = 0
    mensaje: str = ""


@dataclass(frozen=True)
class VistaImagenes:
    """Lo que ve el oncólogo al abrir el expediente (AC1 y AC2)."""

    paciente_id: int
    #: ``True`` si el PACS respondió en esta consulta.
    integracion_disponible: bool
    #: ``True`` si ``estudios`` viene del índice local y no del PACS en vivo.
    desde_indice_local: bool
    estudios: List[EstudioPACS] = field(default_factory=list)
    #: Informes de imagen del expediente sin estudio del PACS asociado: se
    #: pueden leer aunque la integración no esté disponible.
    informes_sin_estudio: List[InformeImagen] = field(default_factory=list)
    #: Aviso para el usuario cuando algo no salió bien (vacío si todo bien).
    mensaje: str = ""


@dataclass(frozen=True)
class ResultadoVisor:
    disponible: bool
    study_uid: str
    url: Optional[str] = None
    informe: Optional[InformeImagen] = None
    mensaje: str = ""


class FuentePACS(Protocol):
    """Un PACS del que se pueden buscar los estudios de un paciente.

    ``buscar_estudios`` puede lanzar cualquier excepción (red, timeout,
    respuesta inválida): este módulo la captura y la informa.
    """

    nombre: str

    def buscar_estudios(self, identificacion: str) -> List[EstudioDICOM]:
        ...


# --------------------------------------------------------------------------
# Fuente DICOMweb (QIDO-RS)
# --------------------------------------------------------------------------


def _valor(dataset: Dict[str, Any], tag: str) -> Any:
    """Primer valor de una etiqueta en DICOM JSON (``None`` si falta o vacía)."""
    elemento = dataset.get(tag)
    if not isinstance(elemento, dict):
        return None
    valores = elemento.get("Value")
    if not valores:
        return None
    primero = valores[0]
    if isinstance(primero, dict):  # PersonName: {"Alphabetic": "Pérez^Juan"}
        return primero.get("Alphabetic") or next(iter(primero.values()), None)
    return primero


def _fecha_dicom(texto: Any) -> Optional[str]:
    """``20260114`` -> ``2026-01-14`` (se deja tal cual si no tiene ese formato)."""
    if not texto:
        return None
    texto = str(texto).strip()
    if re.fullmatch(r"\d{8}", texto):
        return f"{texto[:4]}-{texto[4:6]}-{texto[6:]}"
    return texto


def _entero(valor: Any) -> Optional[int]:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def uid_valido(uid: Any) -> bool:
    """UID DICOM: números separados por puntos, hasta 64 caracteres."""
    return isinstance(uid, str) and len(uid) <= _UID_MAX and bool(_UID_RE.fullmatch(uid))


def estudio_desde_dicom_json(dataset: Dict[str, Any]) -> EstudioDICOM:
    """Traduce un resultado de QIDO-RS (DICOM JSON) a ``EstudioDICOM``.

    Lanza ``ErrorPACS`` si falta lo imprescindible para hacerlo seguro: el
    UID del estudio (válido) y el ``PatientID`` para verificar identidad.
    """
    if not isinstance(dataset, dict):
        raise ErrorPACS("El PACS devolvió un estudio con formato inesperado.")
    uid = _valor(dataset, _TAG_STUDY_UID)
    if not uid_valido(uid):
        raise ErrorPACS(f"El PACS devolvió un StudyInstanceUID inválido: {uid!r}.")
    patient_id = _valor(dataset, _TAG_PATIENT_ID)
    if not patient_id or not str(patient_id).strip():
        raise ErrorPACS(f"El estudio {uid} no trae PatientID: no se puede verificar a quién pertenece.")

    modalidades = dataset.get(_TAG_MODALIDADES_ESTUDIO, {}).get("Value") if isinstance(
        dataset.get(_TAG_MODALIDADES_ESTUDIO), dict
    ) else None
    modalidad = "/".join(str(m) for m in modalidades) if modalidades else _valor(dataset, _TAG_MODALIDAD)

    nombre = _valor(dataset, _TAG_PATIENT_NAME)
    descripcion = _valor(dataset, _TAG_DESCRIPCION)
    accession = _valor(dataset, _TAG_ACCESSION)
    return EstudioDICOM(
        study_uid=uid,
        patient_id=str(patient_id).strip(),
        patient_name=str(nombre) if nombre else None,
        fecha=_fecha_dicom(_valor(dataset, _TAG_FECHA)),
        modalidad=str(modalidad) if modalidad else None,
        descripcion=str(descripcion) if descripcion else None,
        accession_number=str(accession) if accession else None,
        series=_entero(_valor(dataset, _TAG_N_SERIES)),
        instancias=_entero(_valor(dataset, _TAG_N_INSTANCIAS)),
    )


class FuenteDICOMweb:
    """PACS con interfaz DICOMweb: ``GET {base}/studies?PatientID=...`` (QIDO-RS).

    ``session`` es inyectable (``requests.Session`` o un doble de prueba).
    Respuesta 200 = lista en DICOM JSON; 204 = el paciente no tiene estudios.
    """

    def __init__(
        self,
        nombre: str,
        base_url: str,
        session: Any = None,
        timeout: float = 10.0,
        token: Optional[str] = None,
        usuario: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.nombre = nombre
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.token = token
        self.usuario = usuario
        self.password = password
        if session is None:
            import requests

            session = requests.Session()
        self.session = session

    def buscar_estudios(self, identificacion: str) -> List[EstudioDICOM]:
        cabeceras = {"Accept": "application/dicom+json"}
        if self.token:
            cabeceras["Authorization"] = f"Bearer {self.token}"
        elif self.usuario:  # HTTP Basic (p. ej. Orthanc con RegisteredUsers)
            credencial = base64.b64encode(f"{self.usuario}:{self.password or ''}".encode("utf-8")).decode("ascii")
            cabeceras["Authorization"] = f"Basic {credencial}"
        respuesta = self.session.get(
            f"{self.base_url}/studies",
            params={"PatientID": identificacion, "includefield": "all"},
            headers=cabeceras,
            timeout=self.timeout,
        )
        if respuesta.status_code == 204:
            return []
        if respuesta.status_code != 200:
            raise ErrorPACS(f"El PACS respondió HTTP {respuesta.status_code}.")
        try:
            datos = respuesta.json()
        except ValueError as exc:
            raise ErrorPACS("El PACS devolvió una respuesta que no es JSON.") from exc
        if not isinstance(datos, list):
            raise ErrorPACS("El PACS devolvió una respuesta con formato inesperado (se esperaba una lista).")
        return [estudio_desde_dicom_json(d) for d in datos]


def fuente_desde_entorno(session: Any = None) -> Optional[FuentePACS]:
    """La fuente configurada por variables de entorno, o ``None`` si no hay."""
    url = (os.environ.get(ENV_PACS_URL) or "").strip()
    if not url:
        return None
    return FuenteDICOMweb(
        os.environ.get(ENV_PACS_NOMBRE) or "PACS institucional",
        url,
        session=session,
        token=os.environ.get(ENV_PACS_TOKEN) or None,
        usuario=os.environ.get(ENV_PACS_USUARIO) or None,
        password=os.environ.get(ENV_PACS_PASSWORD) or None,
    )


# --------------------------------------------------------------------------
# Visor incrustable
# --------------------------------------------------------------------------


def validar_plantilla_visor(plantilla: Optional[str]) -> Optional[str]:
    """Devuelve la plantilla validada (o ``None`` si no hay visor).

    Debe ser http(s) y contener ``{study_uid}``. Solo se aceptan esquemas web:
    la URL termina en un ``<iframe>``/enlace del frontend.
    """
    if plantilla is None or not plantilla.strip():
        return None
    plantilla = plantilla.strip()
    if "{study_uid}" not in plantilla:
        raise ErrorConfiguracionVisor("La plantilla del visor debe contener el marcador {study_uid}.")
    analizada = urlparse(plantilla.replace("{study_uid}", "0"))
    if analizada.scheme not in ("http", "https") or not analizada.netloc:
        raise ErrorConfiguracionVisor("La plantilla del visor debe ser una URL http(s) completa.")
    return plantilla


def plantilla_visor_desde_entorno() -> Optional[str]:
    return validar_plantilla_visor(os.environ.get(ENV_VISOR_URL))


def construir_url_visor(plantilla: Optional[str], study_uid: str) -> Optional[str]:
    """URL del visor para un estudio (``None`` si no hay visor configurado)."""
    plantilla = validar_plantilla_visor(plantilla)
    if plantilla is None:
        return None
    if not uid_valido(study_uid):
        raise ErrorPACS(f"StudyInstanceUID inválido: {study_uid!r}.")
    return plantilla.replace("{study_uid}", quote(study_uid, safe=""))


# --------------------------------------------------------------------------
# Enlace estudio <-> informe
# --------------------------------------------------------------------------


def _modalidad_compatible(modalidad_dicom: Optional[str], modalidad_expediente: str) -> bool:
    """La modalidad del PACS (``CT``, ``MR\\CT``) cabe en el texto del expediente
    ("Tomografía de tórax")."""
    if not modalidad_dicom:
        return False
    texto = f" {normalizar_texto(modalidad_expediente)} "
    for codigo in re.split(r"[/\\]", modalidad_dicom):
        palabras = _MODALIDADES.get(codigo.strip().upper(), ()) + (codigo.strip(),)
        if any(f" {normalizar_texto(p)} " in texto for p in palabras if normalizar_texto(p)):
            return True
    return False


def _informe_unico(
    conn: sqlite3.Connection, paciente_id: int, estudio: EstudioDICOM
) -> Optional[int]:
    """Id de la fila de ``imagenologia`` que corresponde al estudio, solo si es
    una y solo una (misma fecha y modalidad compatible). Si no, ``None``."""
    if not estudio.fecha:
        return None
    candidatos = [
        img.id
        for img in imagenologia_de_paciente(conn, paciente_id)
        if img.fecha[:10] == estudio.fecha[:10] and _modalidad_compatible(estudio.modalidad, img.modalidad)
    ]
    return candidatos[0] if len(candidatos) == 1 else None


def _informe(conn: sqlite3.Connection, imagenologia_id: Optional[int]) -> Optional[InformeImagen]:
    if imagenologia_id is None:
        return None
    fila = conn.execute("SELECT * FROM imagenologia WHERE id = ?", (imagenologia_id,)).fetchone()
    if fila is None:
        return None
    return InformeImagen(
        imagenologia_id=fila["id"],
        fecha=fila["fecha"],
        modalidad=fila["modalidad"],
        region=fila["region"],
        texto=fila["hallazgos"],
    )


# --------------------------------------------------------------------------
# Sincronización con el PACS
# --------------------------------------------------------------------------


def _paciente_o_error(conn: sqlite3.Connection, paciente_id: int):
    paciente = obtener_paciente(conn, paciente_id)
    if paciente is None:
        raise ValueError(f"No existe ningún paciente con id={paciente_id}.")
    return paciente


def _registrar_consulta(
    conn: sqlite3.Connection,
    paciente_id: int,
    pacs: str,
    tipo: str,
    estado: str,
    *,
    estudios: int = 0,
    rechazados: int = 0,
    study_uid: Optional[str] = None,
    mensaje: str = "",
    ahora: str,
) -> None:
    conn.execute(
        "INSERT INTO consultas_pacs (paciente_id, pacs, tipo, estado, estudios, rechazados, study_uid, mensaje, fecha) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (paciente_id, pacs, tipo, estado, estudios, rechazados, study_uid, mensaje, ahora),
    )
    conn.commit()


def _describir(exc: BaseException) -> str:
    return str(exc) or exc.__class__.__name__


def _pertenece_al_paciente(estudio: EstudioDICOM, identificacion: str, nombre: str) -> bool:
    if estudio.patient_id != identificacion:
        return False
    if estudio.patient_name and not nombres_coinciden(nombre, estudio.patient_name):
        return False
    return True


def sincronizar_estudios(
    conn: sqlite3.Connection,
    paciente_id: int,
    fuente: FuentePACS,
    *,
    tipo: str = TIPO_LISTADO,
    ahora: Optional[datetime] = None,
) -> ResultadoSincronizacionPACS:
    """Trae del PACS los estudios del paciente y los indexa.

    Nunca propaga excepciones del PACS (AC2): el fallo queda en
    ``consultas_pacs`` y se devuelve ``exito=False`` con el motivo. Solo
    lanza ``ValueError`` si el paciente no existe en el expediente.
    """
    paciente = _paciente_o_error(conn, paciente_id)
    momento = ahora_iso(ahora)
    try:
        estudios = fuente.buscar_estudios(paciente.identificacion)
    except Exception as exc:  # noqa: BLE001 — cualquier fallo del PACS se informa, no se propaga
        mensaje = f"No se pudo consultar el PACS '{fuente.nombre}': {_describir(exc).rstrip('.')}."
        _registrar_consulta(conn, paciente_id, fuente.nombre, tipo, ESTADO_FALLIDA, mensaje=mensaje, ahora=momento)
        return ResultadoSincronizacionPACS(False, fuente.nombre, mensaje=mensaje)

    propios = [e for e in estudios if _pertenece_al_paciente(e, paciente.identificacion, paciente.nombre)]
    rechazados = len(estudios) - len(propios)

    try:
        with conn:
            for estudio in propios:
                conn.execute(
                    "INSERT INTO estudios_pacs (paciente_id, pacs, study_uid, accession_number, fecha, modalidad, "
                    "descripcion, series, instancias, imagenologia_id, sincronizado_en) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT (pacs, study_uid) DO UPDATE SET accession_number = excluded.accession_number, "
                    "fecha = excluded.fecha, modalidad = excluded.modalidad, descripcion = excluded.descripcion, "
                    "series = excluded.series, instancias = excluded.instancias, "
                    "imagenologia_id = excluded.imagenologia_id, sincronizado_en = excluded.sincronizado_en "
                    "WHERE estudios_pacs.paciente_id = excluded.paciente_id",
                    (
                        paciente_id, fuente.nombre, estudio.study_uid, estudio.accession_number, estudio.fecha,
                        estudio.modalidad, estudio.descripcion, estudio.series, estudio.instancias,
                        _informe_unico(conn, paciente_id, estudio), momento,
                    ),
                )
    except sqlite3.Error as exc:
        mensaje = f"No se pudo guardar el índice de estudios del PACS '{fuente.nombre}': {_describir(exc).rstrip('.')}."
        _registrar_consulta(conn, paciente_id, fuente.nombre, tipo, ESTADO_FALLIDA, mensaje=mensaje, ahora=momento)
        return ResultadoSincronizacionPACS(False, fuente.nombre, mensaje=mensaje)

    aviso = ""
    if rechazados:
        aviso = (
            f" Se descartaron {rechazados} estudio(s) del PACS cuyo paciente no coincide con el del expediente."
        )
    mensaje = f"PACS '{fuente.nombre}': {len(propios)} estudio(s) del paciente.{aviso}"
    _registrar_consulta(
        conn, paciente_id, fuente.nombre, tipo, ESTADO_EXITOSA,
        estudios=len(propios), rechazados=rechazados, mensaje=mensaje, ahora=momento,
    )
    return ResultadoSincronizacionPACS(True, fuente.nombre, len(propios), rechazados, mensaje)


# --------------------------------------------------------------------------
# Lectura para el expediente
# --------------------------------------------------------------------------


def listar_estudios(
    conn: sqlite3.Connection,
    paciente_id: int,
    *,
    pacs: Optional[str] = None,
    plantilla_visor: Optional[str] = None,
) -> List[EstudioPACS]:
    """Estudios del índice local, del más reciente al más antiguo."""
    plantilla = validar_plantilla_visor(plantilla_visor)
    consulta = "SELECT * FROM estudios_pacs WHERE paciente_id = ?"
    params: List[Any] = [paciente_id]
    if pacs is not None:
        consulta += " AND pacs = ?"
        params.append(pacs)
    consulta += " ORDER BY COALESCE(fecha, '') DESC, id DESC"
    return [
        EstudioPACS(
            id=fila["id"],
            paciente_id=fila["paciente_id"],
            pacs=fila["pacs"],
            study_uid=fila["study_uid"],
            fecha=fila["fecha"],
            modalidad=fila["modalidad"],
            descripcion=fila["descripcion"],
            accession_number=fila["accession_number"],
            series=fila["series"],
            instancias=fila["instancias"],
            sincronizado_en=fila["sincronizado_en"],
            informe=_informe(conn, fila["imagenologia_id"]),
            visor_url=construir_url_visor(plantilla, fila["study_uid"]),
        )
        for fila in conn.execute(consulta, params).fetchall()
    ]


def _informes_sin_estudio(conn: sqlite3.Connection, paciente_id: int) -> List[InformeImagen]:
    enlazados = {
        fila[0]
        for fila in conn.execute(
            "SELECT imagenologia_id FROM estudios_pacs WHERE paciente_id = ? AND imagenologia_id IS NOT NULL",
            (paciente_id,),
        )
    }
    informes = [
        InformeImagen(i.id, i.fecha, i.modalidad, i.region, i.hallazgos)
        for i in imagenologia_de_paciente(conn, paciente_id)
        if i.id not in enlazados
    ]
    return sorted(informes, key=lambda i: i.fecha, reverse=True)


def estudios_del_expediente(
    conn: sqlite3.Connection,
    paciente_id: int,
    fuente: Optional[FuentePACS] = None,
    *,
    plantilla_visor: Optional[str] = None,
    ahora: Optional[datetime] = None,
) -> VistaImagenes:
    """Imágenes del paciente para mostrar al abrir su expediente.

    AC1: si el PACS tiene estudios del paciente, salen listados con su
    informe y el enlace al visor. AC2: si no hay fuente configurada o el PACS
    no responde, ``integracion_disponible`` es ``False`` y ``mensaje``
    explica por qué; se muestra lo último que se sincronizó y los informes
    del expediente, que siguen siendo legibles.
    """
    _paciente_o_error(conn, paciente_id)
    if fuente is None:
        mensaje = (
            "La integración con el PACS no está disponible: no hay un PACS configurado. "
            "Los informes de imagen del expediente siguen disponibles."
        )
        vivo = False
    else:
        resultado = sincronizar_estudios(conn, paciente_id, fuente, ahora=ahora)
        vivo = resultado.exito
        mensaje = "" if vivo else (
            f"La integración con el PACS no está disponible. {resultado.mensaje} "
            "Se muestra lo último sincronizado y los informes del expediente."
        )
    estudios = listar_estudios(
        conn, paciente_id, pacs=fuente.nombre if (fuente is not None and vivo) else None,
        plantilla_visor=plantilla_visor,
    )
    return VistaImagenes(
        paciente_id=paciente_id,
        integracion_disponible=vivo,
        desde_indice_local=not vivo,
        estudios=estudios,
        informes_sin_estudio=_informes_sin_estudio(conn, paciente_id),
        mensaje=mensaje,
    )


def abrir_visor(
    conn: sqlite3.Connection,
    paciente_id: int,
    study_uid: str,
    fuente: Optional[FuentePACS] = None,
    *,
    plantilla_visor: Optional[str] = None,
    ahora: Optional[datetime] = None,
) -> ResultadoVisor:
    """Abre un estudio en el visor incrustado (AC2 de la historia).

    Se vuelve a consultar el PACS para confirmar que el estudio sigue
    ahí y es del paciente. Si no hay PACS configurado, no responde o no hay
    visor, ``disponible`` es ``False`` y ``mensaje`` lo dice con claridad
    (nunca un fallo silencioso); si el estudio tiene informe, se devuelve
    para que el médico pueda leerlo igual.
    """
    paciente = _paciente_o_error(conn, paciente_id)
    momento = ahora_iso(ahora)
    if not uid_valido(study_uid):
        return ResultadoVisor(False, study_uid, mensaje="El identificador del estudio no es un UID DICOM válido.")

    indexado = next((e for e in listar_estudios(conn, paciente_id) if e.study_uid == study_uid), None)
    informe = indexado.informe if indexado else None
    nombre_pacs = fuente.nombre if fuente is not None else "(sin configurar)"
    leyenda_informe = " El informe asociado sí está disponible." if informe else ""

    def _falla(mensaje: str) -> ResultadoVisor:
        _registrar_consulta(
            conn, paciente_id, nombre_pacs, TIPO_VISOR, ESTADO_FALLIDA,
            study_uid=study_uid, mensaje=mensaje, ahora=momento,
        )
        return ResultadoVisor(False, study_uid, informe=informe, mensaje=mensaje + leyenda_informe)

    if fuente is None:
        return _falla("La integración con el PACS no está disponible: no hay un PACS configurado.")

    sincronizacion = sincronizar_estudios(conn, paciente_id, fuente, tipo=TIPO_VISOR, ahora=ahora)
    if not sincronizacion.exito:
        # Ya quedó la fila ``fallida`` de la sincronización; aquí solo se explica al usuario.
        return ResultadoVisor(
            False, study_uid, informe=informe,
            mensaje=f"La integración con el PACS no está disponible. {sincronizacion.mensaje}{leyenda_informe}",
        )

    estudio = next(
        (e for e in listar_estudios(conn, paciente_id, pacs=fuente.nombre) if e.study_uid == study_uid), None
    )
    if estudio is None:
        return _falla(
            f"El estudio {study_uid} no figura en el PACS '{fuente.nombre}' para el paciente "
            f"{paciente.identificacion}."
        )
    try:
        url = construir_url_visor(plantilla_visor, study_uid)
    except ErrorConfiguracionVisor as exc:
        return _falla(f"El visor de imágenes está mal configurado: {exc}")
    if url is None:
        return _falla("No hay un visor de imágenes configurado para abrir el estudio.")

    _registrar_consulta(
        conn, paciente_id, fuente.nombre, TIPO_VISOR, ESTADO_EXITOSA, estudios=1,
        study_uid=study_uid, mensaje="Visor abierto.", ahora=momento,
    )
    return ResultadoVisor(True, study_uid, url=url, informe=estudio.informe, mensaje="Estudio disponible en el visor.")


def historial_consultas(conn: sqlite3.Connection, paciente_id: int) -> List[Dict[str, Any]]:
    """Bitácora de intentos de hablar con el PACS (más reciente primero)."""
    filas = conn.execute(
        "SELECT * FROM consultas_pacs WHERE paciente_id = ? ORDER BY id DESC", (paciente_id,)
    ).fetchall()
    return [dict(f) for f in filas]
