"""DOC-01 — Carga de documentos clínicos (PDF, imágenes, DICOM).

Como oncólogo, quiero cargar documentos clínicos al expediente del
paciente, para centralizar toda la documentación.

Dos decisiones de diseño reutilizan patrones ya establecidos en el resto
del proyecto:

    - La tabla ``documentos_clinicos_cargados`` es de solo-inserción,
      igual que ``juicios_clinicos_dx`` (DX-03): un documento cargado
      nunca se sobreescribe. El "historial de documentos" del AC1 es,
      simplemente, listar todas las filas de un paciente.
    - Nunca se confía únicamente en la extensión del archivo para decidir
      si "es" un PDF/imagen/DICOM real: además de exigir una extensión
      soportada, se verifica la firma binaria del contenido (los primeros
      bytes reales del archivo). Un archivo de texto renombrado a
      ``informe.pdf`` no pasa la validación -- la misma filosofía de "no
      aceptar una afirmación sin verificarla contra el dato real" que ya
      aplica el resto del proyecto (trazabilidad de ``ia_clinica``,
      evidencia citable de ``dx_clinica``).

El contenido binario se guarda en disco bajo un directorio configurable
(``directorio_almacenamiento``, nunca hardcodeado, para que las pruebas
puedan usar un directorio temporal); solo los metadatos y la ruta
resultante se guardan en SQLite.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple, Union

from expediente.adapters import PacienteNoEncontradoError
from expediente.repository import obtener_paciente

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema_documentos_clinicos.sql"


class DocumentoInvalidoError(Exception):
    """El documento no cumple los requisitos mínimos para cargarse.

    Clase base de las dos razones concretas de rechazo (formato no
    soportado, contenido que no corresponde al formato declarado), más
    validaciones básicas de forma (archivo vacío, autor vacío).
    """


class FormatoNoSoportadoError(DocumentoInvalidoError):
    """La extensión del archivo no está en :data:`FORMATOS_SOPORTADOS` (AC2).

    El mensaje siempre incluye explícitamente los formatos esperados,
    tal como exige el criterio de aceptación ("displays a clear message
    indicating the expected format").
    """


class ContenidoNoCoincideConFormatoError(DocumentoInvalidoError):
    """La extensión es reconocida, pero el contenido real no le corresponde.

    Por ejemplo, un archivo llamado ``informe.pdf`` cuyo contenido no
    empieza con la firma binaria de un PDF real. Es un rechazo distinto
    de :class:`FormatoNoSoportadoError`: aquí el formato declarado sí es
    uno soportado, el problema es que el archivo no es genuinamente de
    ese tipo (renombrado por error, corrupto, o alterado).
    """


def _es_pdf(contenido: bytes) -> bool:
    return contenido.startswith(b"%PDF-")


def _es_jpeg(contenido: bytes) -> bool:
    return contenido.startswith(b"\xff\xd8\xff")


def _es_png(contenido: bytes) -> bool:
    return contenido.startswith(b"\x89PNG\r\n\x1a\n")


def _es_dicom(contenido: bytes) -> bool:
    # Los archivos DICOM "Parte 10" tienen un preámbulo de 128 bytes
    # (típicamente ceros, sin significado clínico) seguido literalmente
    # de b"DICM" -- esa es la firma real que se verifica aquí, no la
    # extensión ``.dcm``.
    return len(contenido) >= 132 and contenido[128:132] == b"DICM"


@dataclass(frozen=True)
class PerfilFormatoSoportado:
    """Un formato aceptado por DOC-01: su etiqueta y cómo verificar su firma real."""

    tipo_documento: str  # "PDF" | "Imagen" | "DICOM"
    descripcion: str
    validar_firma: Callable[[bytes], bool]


#: Catálogo explícito de formatos soportados, tal como pide la historia
#: ("PDF, imágenes, DICOM"). Ampliar esta historia a un formato adicional
#: es agregar una entrada aquí -- no hay ninguna lista duplicada en otro
#: lugar del módulo.
FORMATOS_SOPORTADOS: Dict[str, PerfilFormatoSoportado] = {
    ".pdf": PerfilFormatoSoportado("PDF", "Documento PDF", _es_pdf),
    ".jpg": PerfilFormatoSoportado("Imagen", "Imagen JPEG", _es_jpeg),
    ".jpeg": PerfilFormatoSoportado("Imagen", "Imagen JPEG", _es_jpeg),
    ".png": PerfilFormatoSoportado("Imagen", "Imagen PNG", _es_png),
    ".dcm": PerfilFormatoSoportado("DICOM", "Estudio DICOM", _es_dicom),
}


def _descripcion_formatos_aceptados() -> str:
    extensiones_por_tipo: Dict[str, list] = {}
    for extension, perfil in FORMATOS_SOPORTADOS.items():
        extensiones_por_tipo.setdefault(perfil.tipo_documento, []).append(extension)
    partes = [
        f"{tipo} ({'/'.join(sorted(extensiones))})"
        for tipo, extensiones in sorted(extensiones_por_tipo.items())
    ]
    return ", ".join(partes)


@dataclass(frozen=True)
class DocumentoClinicoCargado:
    """Snapshot de solo lectura de un documento ya cargado al expediente."""

    id: int
    paciente_id: int
    nombre_archivo_original: str
    tipo_documento: str
    extension: str
    tamano_bytes: int
    ruta_almacenamiento: str
    cargado_por: str
    cargado_en: str


def crear_conexion(ruta: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(ruta)
    conn.row_factory = sqlite3.Row
    inicializar_esquema(conn)
    return conn


def inicializar_esquema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def cargar_documento_clinico(
    conn: sqlite3.Connection,
    conn_historia: sqlite3.Connection,
    paciente_id: int,
    nombre_archivo: str,
    contenido: bytes,
    cargado_por: str,
    directorio_almacenamiento: Union[str, Path],
    ahora: Optional[datetime] = None,
) -> DocumentoClinicoCargado:
    """Carga un documento clínico al expediente de un paciente (AC1/AC2).

    Orden de validación, cada una con un error explícito propio:

    1. El paciente debe existir en ``expediente`` (mismo
       ``PacienteNoEncontradoError`` que ya usan los demás adaptadores de
       ``expediente`` y ``documentos_clinicos.adaptadores``) --
       nunca se asocia un documento a un paciente que no existe.
    2. ``cargado_por`` y ``contenido`` no pueden estar vacíos
       (``DocumentoInvalidoError``).
    3. La extensión de ``nombre_archivo`` debe estar en
       :data:`FORMATOS_SOPORTADOS` (AC2 -- ``FormatoNoSoportadoError`` en
       caso contrario, con la lista de formatos esperados en el mensaje).
    4. El contenido debe tener la firma binaria real de ese formato
       (``ContenidoNoCoincideConFormatoError`` en caso contrario).

    Solo si las cuatro validaciones pasan se escribe el archivo en disco
    (bajo ``directorio_almacenamiento``, con un nombre generado) y se
    inserta la fila de metadatos -- nunca se guarda un archivo a medias
    ni una fila sin el archivo real correspondiente.
    """

    paciente = obtener_paciente(conn_historia, paciente_id)
    if paciente is None:
        raise PacienteNoEncontradoError(
            f"No existe ningún paciente con id={paciente_id}; no se puede asociar el documento."
        )

    if not cargado_por or not cargado_por.strip():
        raise DocumentoInvalidoError(
            "Quien carga el documento no puede estar vacío: se necesita un identificador "
            "explícito del médico o personal autorizado que lo está cargando."
        )

    if not contenido:
        raise DocumentoInvalidoError("El archivo está vacío; no hay ningún documento que cargar.")

    if not nombre_archivo or "." not in nombre_archivo:
        raise FormatoNoSoportadoError(
            f"'{nombre_archivo}' no tiene una extensión reconocible. Formatos aceptados: "
            f"{_descripcion_formatos_aceptados()}."
        )

    extension = "." + nombre_archivo.rsplit(".", 1)[-1].lower()
    perfil = FORMATOS_SOPORTADOS.get(extension)
    if perfil is None:
        raise FormatoNoSoportadoError(
            f"El formato '{extension}' no está soportado. Formatos aceptados: "
            f"{_descripcion_formatos_aceptados()}."
        )

    if not perfil.validar_firma(contenido):
        raise ContenidoNoCoincideConFormatoError(
            f"El archivo '{nombre_archivo}' tiene extensión '{extension}' ({perfil.descripcion}), "
            "pero su contenido no corresponde a ese formato. Verifique que el archivo no esté "
            "corrupto ni haya sido renombrado por error."
        )

    directorio_paciente = Path(directorio_almacenamiento) / f"paciente_{paciente_id}"
    directorio_paciente.mkdir(parents=True, exist_ok=True)
    nombre_interno = f"{uuid.uuid4().hex}{extension}"
    ruta_destino = directorio_paciente / nombre_interno
    ruta_destino.write_bytes(contenido)

    cargado_en = (ahora or datetime.now(timezone.utc)).isoformat()

    cursor = conn.execute(
        """
        INSERT INTO documentos_clinicos_cargados (
            paciente_id, nombre_archivo_original, tipo_documento, extension,
            tamano_bytes, ruta_almacenamiento, cargado_por, cargado_en
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            paciente_id,
            nombre_archivo,
            perfil.tipo_documento,
            extension,
            len(contenido),
            str(ruta_destino),
            cargado_por,
            cargado_en,
        ),
    )
    conn.commit()
    return obtener_documento_por_id(conn, cursor.lastrowid)


def obtener_documento_por_id(conn: sqlite3.Connection, documento_id: int) -> DocumentoClinicoCargado:
    fila = conn.execute(
        "SELECT * FROM documentos_clinicos_cargados WHERE id = ?", (documento_id,)
    ).fetchone()
    if fila is None:
        raise KeyError(f"No existe ningún documento cargado con id={documento_id}.")
    return _fila_a_documento(fila)


def listar_documentos_de_paciente(
    conn: sqlite3.Connection, paciente_id: int
) -> Tuple[DocumentoClinicoCargado, ...]:
    """El historial de documentos de un paciente (AC1), del más reciente al más antiguo."""

    filas = conn.execute(
        "SELECT * FROM documentos_clinicos_cargados WHERE paciente_id = ? ORDER BY id DESC",
        (paciente_id,),
    ).fetchall()
    return tuple(_fila_a_documento(f) for f in filas)


def leer_contenido_documento(documento: DocumentoClinicoCargado) -> bytes:
    """Lee de vuelta el contenido binario real del documento desde disco.

    Útil para confirmar, en pruebas o en una demo, que lo que se guardó
    es exactamente lo que se cargó -- nunca se transforma el contenido
    original al guardarlo.
    """

    return Path(documento.ruta_almacenamiento).read_bytes()


def _fila_a_documento(fila: sqlite3.Row) -> DocumentoClinicoCargado:
    return DocumentoClinicoCargado(
        id=fila["id"],
        paciente_id=fila["paciente_id"],
        nombre_archivo_original=fila["nombre_archivo_original"],
        tipo_documento=fila["tipo_documento"],
        extension=fila["extension"],
        tamano_bytes=fila["tamano_bytes"],
        ruta_almacenamiento=fila["ruta_almacenamiento"],
        cargado_por=fila["cargado_por"],
        cargado_en=fila["cargado_en"],
    )
