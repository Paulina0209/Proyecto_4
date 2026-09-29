"""Cliente HTTP de la API pública de cBioPortal (https://www.cbioportal.org/api).

Solo lectura. Cada método devuelve la respuesta ya reducida a lo que usa
el importador; cualquier respuesta distinta de HTTP 200 se convierte en
``ErrorIntegracion`` para que HC-01 la registre como sincronización
fallida en vez de propagarla.

``session`` es inyectable (``requests.Session`` o un doble de prueba). Sin
ella se crea una sesión con reintentos para 429/5xx, porque la API pública
responde 502 ocasionalmente bajo carga.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set

from historia_clinica.integracion_externa import ErrorIntegracion

URL_PUBLICA = "https://www.cbioportal.org/api"

#: Tamaño de página suficiente para traer todos los eventos de un paciente
#: de una vez (el más cargado de MSK-CHORD tiene unos pocos miles).
_PAGINA_EVENTOS = 100_000


def _sesion_con_reintentos():
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    reintentos = Retry(
        total=4,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=reintentos))
    session.mount("http://", HTTPAdapter(max_retries=reintentos))
    return session


class ClienteCBioPortal:
    """``token``: solo para instancias privadas de cBioPortal (portal
    institucional); la pública no lo necesita."""

    def __init__(
        self,
        base_url: str = URL_PUBLICA,
        session: Any = None,
        timeout: float = 60.0,
        token: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session if session is not None else _sesion_con_reintentos()
        self._cabeceras = {"Accept": "application/json"}
        if token:
            self._cabeceras["Authorization"] = f"Bearer {token}"
        self._paneles: Dict[str, Set[str]] = {}
        self._entrez: Dict[str, int] = {}

    # -- HTTP ---------------------------------------------------------------

    def _get(self, ruta: str, **params: Any) -> Any:
        respuesta = self.session.get(
            f"{self.base_url}{ruta}", params=params or None, headers=self._cabeceras, timeout=self.timeout
        )
        return self._json(respuesta, ruta)

    def _post(self, ruta: str, cuerpo: Any, **params: Any) -> Any:
        respuesta = self.session.post(
            f"{self.base_url}{ruta}",
            params=params or None,
            json=cuerpo,
            headers=dict(self._cabeceras, **{"Content-Type": "application/json"}),
            timeout=self.timeout,
        )
        return self._json(respuesta, ruta)

    @staticmethod
    def _json(respuesta: Any, ruta: str) -> Any:
        if respuesta.status_code == 404:
            raise ErrorIntegracion(f"cBioPortal no encontró el recurso {ruta}.")
        if respuesta.status_code != 200:
            raise ErrorIntegracion(f"cBioPortal respondió HTTP {respuesta.status_code} en {ruta}.")
        return respuesta.json()

    # -- Estudios y selección de pacientes -----------------------------------

    def estudio(self, estudio: str) -> Dict[str, Any]:
        return self._get(f"/studies/{estudio}")

    def tipo_de_cancer_por_muestra(self, estudio: str) -> List[Dict[str, str]]:
        """``[{"paciente", "muestra", "tipo_cancer"}]`` de todo el estudio,
        en una sola llamada (sirve para elegir pacientes por tipo)."""
        filas = self._post(
            f"/studies/{estudio}/clinical-data/fetch",
            {"attributeIds": ["CANCER_TYPE"]},
            clinicalDataType="SAMPLE",
        )
        return [
            {"paciente": f["patientId"], "muestra": f["sampleId"], "tipo_cancer": f["value"]} for f in filas
        ]

    def perfiles_moleculares(self, estudio: str) -> Dict[str, str]:
        """``{tipo de alteración: id del perfil}``, p. ej.
        ``{"MUTATION_EXTENDED": "msk_chord_2024_mutations"}``."""
        perfiles = self._get(f"/studies/{estudio}/molecular-profiles")
        return {p["molecularAlterationType"]: p["molecularProfileId"] for p in perfiles}

    # -- Un paciente ---------------------------------------------------------

    def datos_clinicos_paciente(self, estudio: str, paciente: str) -> Dict[str, str]:
        filas = self._get(f"/studies/{estudio}/patients/{paciente}/clinical-data")
        return {f["clinicalAttributeId"]: f["value"] for f in filas}

    def muestras_de_paciente(self, estudio: str, paciente: str) -> List[str]:
        return sorted(m["sampleId"] for m in self._get(f"/studies/{estudio}/patients/{paciente}/samples"))

    def datos_clinicos_muestra(self, estudio: str, muestra: str) -> Dict[str, str]:
        filas = self._get(f"/studies/{estudio}/samples/{muestra}/clinical-data")
        return {f["clinicalAttributeId"]: f["value"] for f in filas}

    def eventos_clinicos(self, estudio: str, paciente: str) -> List[Dict[str, Any]]:
        """Línea de tiempo del paciente. Los días son relativos (el estudio
        está desidentificado y no publica fechas reales)."""
        eventos = self._get(
            f"/studies/{estudio}/patients/{paciente}/clinical-events", pageSize=_PAGINA_EVENTOS
        )
        return [
            {
                "tipo": e["eventType"],
                "inicio": e.get("startNumberOfDaysSinceDiagnosis"),
                "fin": e.get("endNumberOfDaysSinceDiagnosis"),
                "atributos": {a["key"]: a["value"] for a in e.get("attributes") or []},
            }
            for e in eventos
        ]

    # -- Genómica ------------------------------------------------------------

    def entrez_ids(self, simbolos: Iterable[str]) -> Dict[str, int]:
        faltantes = sorted(set(simbolos) - set(self._entrez))
        if faltantes:
            genes = self._post("/genes/fetch", faltantes, geneIdType="HUGO_GENE_SYMBOL")
            self._entrez.update({g["hugoGeneSymbol"]: g["entrezGeneId"] for g in genes})
        return {s: self._entrez[s] for s in simbolos if s in self._entrez}

    def genes_de_panel(self, panel: str) -> Set[str]:
        if panel not in self._paneles:
            datos = self._get(f"/gene-panels/{panel}")
            self._paneles[panel] = {g["hugoGeneSymbol"] for g in datos.get("genes") or []}
        return self._paneles[panel]

    def mutaciones(self, perfil: str, muestras: List[str], genes: Dict[str, int]) -> List[Dict[str, str]]:
        if not muestras or not genes:
            return []
        por_entrez = {v: k for k, v in genes.items()}
        filas = self._post(
            f"/molecular-profiles/{perfil}/mutations/fetch",
            {"sampleIds": muestras, "entrezGeneIds": sorted(genes.values())},
            projection="SUMMARY",
        )
        return [
            {
                "muestra": f["sampleId"],
                "gen": por_entrez.get(f["entrezGeneId"], str(f["entrezGeneId"])),
                "cambio_proteico": f.get("proteinChange") or "",
                "tipo": f.get("mutationType") or "",
            }
            for f in filas
        ]

    def fusiones(self, perfil: str, muestras: List[str], genes: Dict[str, int]) -> List[Dict[str, str]]:
        if not muestras or not genes:
            return []
        filas = self._post(
            "/structural-variant/fetch",
            {
                "entrezGeneIds": sorted(genes.values()),
                "sampleMolecularIdentifiers": [{"molecularProfileId": perfil, "sampleId": m} for m in muestras],
            },
        )
        return [
            {
                "muestra": f["sampleId"],
                "gen_1": f.get("site1HugoSymbol") or "",
                "gen_2": f.get("site2HugoSymbol") or "",
                "descripcion": f.get("eventInfo") or "",
            }
            for f in filas
        ]
