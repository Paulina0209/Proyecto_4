"""Catálogo de evidencia derivado de los módulos de `guidelines/` ya existentes.

Esta es, a propósito, una implementación mínima de lo que eventualmente
será IA-04 (explicabilidad/trazabilidad de evidencia para toda salida de
IA). Aquí solo cubre lo que DX-02 necesita: poder "consultar la evidencia
asociada" a una alternativa diagnóstica (criterio de aceptación 3 de
DX-02). Cuando IA-04 exista como historia propia, este catálogo puede
convertirse en su fuente de datos en vez de duplicarse.

Ningún dato de evidencia se inventa en tiempo de ejecución: todo proviene
de leer los `metadata.yaml` ya versionados en `guidelines/`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import yaml

_GUIDELINES_ROOT = Path(__file__).resolve().parent.parent / "guidelines"


@dataclass(frozen=True)
class EvidenceReference:
    """Una referencia de evidencia consultable, trazable a un archivo real del repo."""

    module_id: str
    organization: str
    title: str
    publication_year: Optional[int]
    doi: Optional[str]
    clinical_validation_status: Optional[str]
    ruta_metadata: str

    def resumen_citable(self) -> str:
        """Texto listo para mostrar como cita, incluyendo el aviso de validación."""

        cita = f"{self.organization} — {self.title}"
        if self.publication_year:
            cita += f" ({self.publication_year})"
        if self.doi:
            cita += f", DOI: {self.doi}"
        aviso_validacion = (
            f" [Estado de validación clínica de este módulo: {self.clinical_validation_status or 'no especificado'} "
            "— no se debe interpretar como evidencia clínicamente validada hasta que ese estado sea 'validado']"
        )
        return cita + aviso_validacion


def _leer_metadata(carpeta_modulo: Path) -> Optional[dict]:
    metadata_path = carpeta_modulo / "metadata.yaml"
    if not metadata_path.exists():
        return None
    with metadata_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _estado_validacion_clinica(metadata: dict) -> Optional[str]:
    validation = metadata.get("validation") or {}
    # Los metadata.yaml existentes no son 100% consistentes en el nombre
    # de esta llave (la mayoría usa 'clinical_validation_status', uno usa
    # 'clinical'); se soportan ambas en vez de asumir una sola forma.
    return validation.get("clinical_validation_status") or validation.get("clinical")


def catalogar_evidencia_desde_guias(guidelines_root: Path = _GUIDELINES_ROOT) -> Dict[str, EvidenceReference]:
    """Construye el catálogo de evidencia leyendo cada `guidelines/<modulo>/metadata.yaml`.

    La clave del diccionario es la carpeta del módulo (por ejemplo
    ``"breast_early_tnbc"``), no el ``module_id`` interno del YAML, para
    que se pueda referenciar con el mismo nombre que ya usa el resto del
    repositorio (rutas de carpeta) al hablar de un módulo de guías.
    """

    catalogo: Dict[str, EvidenceReference] = {}
    if not guidelines_root.exists():
        return catalogo

    for carpeta_modulo in sorted(p for p in guidelines_root.iterdir() if p.is_dir()):
        metadata = _leer_metadata(carpeta_modulo)
        if metadata is None:
            continue
        source = metadata.get("source") or {}
        catalogo[carpeta_modulo.name] = EvidenceReference(
            module_id=metadata.get("module_id", carpeta_modulo.name),
            organization=metadata.get("organization", "organización no especificada"),
            title=source.get("title", metadata.get("name", "título no especificado")),
            publication_year=source.get("publication_year"),
            doi=source.get("doi"),
            clinical_validation_status=_estado_validacion_clinica(metadata),
            ruta_metadata=str(carpeta_modulo / "metadata.yaml"),
        )
    return catalogo


# Catálogo cargado una sola vez al importar el módulo. Es información
# versionada en disco (los metadata.yaml), no una llamada de red, así que
# cachearlo a nivel de módulo es seguro y evita releer archivos en cada
# alternativa diagnóstica evaluada.
_CATALOGO = catalogar_evidencia_desde_guias()


def obtener_evidencia(module_folder: str) -> Optional[EvidenceReference]:
    """Devuelve la referencia de evidencia para una carpeta de `guidelines/`, si existe."""

    return _CATALOGO.get(module_folder)


# Asociación explícita y curada entre el diagnóstico principal registrado
# en `historia_clinica_mock` y el módulo de guías más relevante. Es
# deliberadamente una tabla explícita (no un emparejamiento difuso por
# texto libre) para no inferir una asociación clínica que nadie validó.
_DIAGNOSTICO_A_MODULO: Dict[str, str] = {
    "Cáncer de mama triple negativo": "breast_early_tnbc",
    "Cáncer de pulmón no microcítico metastásico": "nsclc_metastatic_oncogene_addicted",
}


def evidencia_por_diagnostico_principal(diagnostico_principal: Optional[str]) -> Optional[EvidenceReference]:
    """Resuelve la evidencia asociada al contexto oncológico del paciente.

    Si el diagnóstico principal del paciente no tiene una asociación
    explícita registrada, devuelve ``None`` en vez de adivinar el módulo
    de guías más parecido: es preferible mostrar "sin evidencia
    disponible" a citar una guía que no corresponde al caso.
    """

    if not diagnostico_principal:
        return None
    module_folder = _DIAGNOSTICO_A_MODULO.get(diagnostico_principal)
    if module_folder is None:
        return None
    return obtener_evidencia(module_folder)
