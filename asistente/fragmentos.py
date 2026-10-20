"""Qué conoce el asistente: fragmentos con un id estable y su origen.

Los fragmentos del expediente usan EXACTAMENTE los mismos ids que el resto del
sistema (``consulta-3-nota-2``, ``lab-14``, ``imagen-7``, ``biomarcador-2``,
``antecedente-5``) y que la historia clínica que muestra la interfaz, así una
cita del asistente se resalta en el registro de donde salió. Además:

    dato-{id}        un dato clínico estructurado (T/N/M, línea de tratamiento...)
    doc-{id}-{n}     un trozo del texto de un documento cargado (DOC-01)
    guia-{modulo}-{archivo}-{n}   un trozo de una guía clínica versionada

El texto del expediente sale de ``obtener_hallazgos_de_paciente``: exige el
consentimiento de IA (SEC-03) y llega seudonimizado (NFR-04). Nada sin
consentimiento llega al índice ni al modelo.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from asistente.config import RAIZ

TAMANO_TROZO = 900
SOLAPE = 120


@dataclass(frozen=True)
class Fragmento:
    id: str
    texto: str
    tipo: str            # expediente | documento | guia
    origen: str          # consulta | laboratorio | imagenologia | biomarcador | antecedente | dato | documento | guia
    paciente_id: Optional[int] = None
    fecha: Optional[str] = None
    titulo: Optional[str] = None
    metadatos: Dict[str, str] = field(default_factory=dict)

    def metadatos_chroma(self) -> Dict[str, object]:
        datos: Dict[str, object] = {"tipo": self.tipo, "origen": self.origen, "fecha": self.fecha or "", "titulo": self.titulo or ""}
        if self.paciente_id is not None:
            datos["paciente_id"] = int(self.paciente_id)
        datos.update({k: str(v) for k, v in self.metadatos.items()})
        return datos


def trocear(texto: str, tamano: int = TAMANO_TROZO, solape: int = SOLAPE) -> List[str]:
    """Divide un texto en trozos de ~``tamano`` caracteres, cortando en espacios, con solape."""
    texto = " ".join((texto or "").split())
    if not texto:
        return []
    trozos, inicio = [], 0
    while inicio < len(texto):
        fin = min(len(texto), inicio + tamano)
        if fin < len(texto):
            espacio = texto.rfind(" ", inicio + tamano // 2, fin)
            fin = espacio if espacio > inicio else fin
        trozos.append(texto[inicio:fin].strip())
        if fin >= len(texto):
            break
        inicio = max(fin - solape, inicio + 1)
    return [t for t in trozos if t]


def huella(fragmentos: Iterable[Fragmento]) -> str:
    h = hashlib.sha256()
    for f in sorted(fragmentos, key=lambda f: f.id):
        h.update(f.id.encode("utf-8"))
        h.update(f.texto.encode("utf-8"))
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Expediente de un paciente
# ---------------------------------------------------------------------------


def fragmentos_del_expediente(conn: sqlite3.Connection, paciente_id: int) -> List[Fragmento]:
    """Hallazgos (con consentimiento y seudonimizados) + datos estructurados del paciente."""
    from expediente.adapters import obtener_hallazgos_de_paciente
    from privacidad.minimizacion import seudonimizar_texto

    fragmentos = [
        Fragmento(id=h.id, texto=h.texto, tipo="expediente", origen=h.origen, paciente_id=paciente_id, fecha=h.fecha)
        for h in obtener_hallazgos_de_paciente(conn, paciente_id)  # lanza ConsentimientoIARequerido sin consentimiento
    ]
    paciente = conn.execute("SELECT nombre, identificacion, diagnostico_principal, estadio FROM pacientes WHERE id = ?", (paciente_id,)).fetchone()
    if paciente is not None and (paciente[2] or paciente[3]):
        fragmentos.append(Fragmento(id=f"paciente-{paciente_id}", texto=f"Diagnóstico principal registrado: {paciente[2] or 'sin registrar'}. "
                                    f"Estadio registrado: {paciente[3] or 'sin registrar'}.", tipo="expediente", origen="ficha",
                                    paciente_id=paciente_id))
    for fila in conn.execute(
        "SELECT id, variable, valor, fecha FROM datos_clinicos_estructurados WHERE paciente_id = ? ORDER BY id", (paciente_id,)
    ).fetchall():
        fragmentos.append(Fragmento(id=f"dato-{fila[0]}", texto=f"Dato clínico registrado: {fila[1]} = {fila[2]}",
                                    tipo="expediente", origen="dato", paciente_id=paciente_id, fecha=fila[3]))
    if paciente is not None:
        nombre, identificacion = paciente[0], paciente[1]
        fragmentos = [Fragmento(f.id, seudonimizar_texto(f.texto, nombre=nombre, identificaciones=[identificacion] if identificacion else []),
                                f.tipo, f.origen, f.paciente_id, f.fecha, f.titulo, f.metadatos) for f in fragmentos]
    return fragmentos


def fragmentos_de_documento(documento_id: int, paciente_id: int, nombre: str, contenido: bytes, extension: str) -> List[Fragmento]:
    """Texto de un documento cargado (PDF o texto), en trozos. Imágenes y DICOM no tienen texto que extraer."""
    texto = extraer_texto(contenido, extension)
    return [Fragmento(id=f"doc-{documento_id}-{n}", texto=t, tipo="documento", origen="documento", paciente_id=paciente_id,
                      titulo=nombre, metadatos={"documento_id": str(documento_id)})
            for n, t in enumerate(trocear(texto), 1)]


def extraer_texto(contenido: bytes, extension: str) -> str:
    extension = (extension or "").lower()
    if extension in (".txt", ".md", ".csv"):
        return contenido.decode("utf-8", errors="replace")
    if extension == ".pdf":
        try:
            import io

            from pypdf import PdfReader
        except ImportError:  # pragma: no cover - dependencia opcional
            return ""
        try:
            lector = PdfReader(io.BytesIO(contenido))
            return "\n".join((pagina.extract_text() or "") for pagina in lector.pages)
        except Exception:  # noqa: BLE001 - un PDF dañado no se indexa, pero se conserva en el expediente
            return ""
    return ""


# ---------------------------------------------------------------------------
# Guías clínicas
# ---------------------------------------------------------------------------


def fragmentos_de_guias(carpeta: Path = RAIZ / "guidelines") -> List[Fragmento]:
    import yaml

    fragmentos: List[Fragmento] = []
    for modulo in sorted(p for p in carpeta.iterdir() if p.is_dir() and (p / "metadata.yaml").is_file()):
        try:
            meta = yaml.safe_load((modulo / "metadata.yaml").read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        fuente = meta.get("source") or {}
        titulo = f"{meta.get('organization', '')} — {fuente.get('title') or meta.get('name') or modulo.name}".strip(" —")
        comunes = {"modulo": meta.get("module_id") or modulo.name, "organizacion": str(meta.get("organization") or ""),
                   "anio": str(fuente.get("publication_year") or ""), "doi": str(fuente.get("doi") or "")}
        for archivo in sorted(modulo.rglob("*.yaml")):
            relativo = archivo.relative_to(modulo).as_posix().replace("/", "_").removesuffix(".yaml")
            texto = archivo.read_text(encoding="utf-8")
            for n, trozo in enumerate(trocear(texto), 1):
                fragmentos.append(Fragmento(id=f"guia-{modulo.name}-{relativo}-{n}", texto=f"{titulo}. {trozo}", tipo="guia",
                                            origen="guia", titulo=titulo, metadatos={**comunes, "archivo": archivo.relative_to(carpeta).as_posix()}))
    return fragmentos
