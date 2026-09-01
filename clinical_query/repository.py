from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

from historia_clinica_mock.repository import (
    biomarcadores_de_paciente,
    laboratorios_de_paciente,
    listar_pacientes,
)

from .ambiguity import PacienteRef
from .models import ClinicalDatum, ClinicalRecord
from .normalizer import normalize_text


class ClinicalRepository(ABC):
    """Port for retrieving structured clinical facts from an active record."""

    @abstractmethod
    def find_by_concept(self, patient_id: str, concept: str) -> list[ClinicalDatum]:
        raise NotImplementedError

    def directorio_pacientes(self) -> list[PacienteRef]:
        """Identidades de los pacientes conocidos, para desambiguar (IA-06).

        Por defecto vacío: solo el adaptador sobre la base real lo implementa.
        """

        return []


class JsonClinicalRepository(ClinicalRepository):
    """Legacy JSON adapter kept for backwards compatibility with early IA-01 tests."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._records = self._load_records()

    def _load_records(self) -> dict[str, ClinicalRecord]:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        patients = raw.get("patients", [])
        records: dict[str, ClinicalRecord] = {}

        for patient in patients:
            data = [
                ClinicalDatum(
                    concept=item["concept"],
                    value=str(item["value"]),
                    unit=item.get("unit"),
                    observed_at=datetime.fromisoformat(item["observed_at"]),
                    source=item["source"],
                    source_id=item["source_id"],
                )
                for item in patient.get("data", [])
            ]
            record = ClinicalRecord(patient_id=patient["patient_id"], data=data)
            records[record.patient_id] = record

        return records

    def find_by_concept(self, patient_id: str, concept: str) -> list[ClinicalDatum]:
        record = self._records.get(patient_id)
        if record is None:
            return []
        return [item for item in record.data if item.concept.casefold() == concept.casefold()]


class MockSQLiteClinicalRepository(ClinicalRepository):
    """IA-01 adapter over the project's SQLite synthetic clinical-record mock.

    The application service remains unaware of SQLite. Every returned value is
    scoped by ``patient_id`` and carries the exact source row identifier.
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    @staticmethod
    def _matches(stored_name: str, concept: str) -> bool:
        stored = normalize_text(stored_name)
        requested = normalize_text(concept)
        # Exact match covers biomarkers (HER2, EGFR). Containment covers labels
        # such as "Hemograma - neutrófilos" and "... función hepática (ALT)".
        return stored == requested or requested in stored.split() or requested in stored

    def find_by_concept(self, patient_id: str, concept: str) -> list[ClinicalDatum]:
        try:
            pid = int(patient_id)
        except (TypeError, ValueError):
            return []

        data: list[ClinicalDatum] = []

        for lab in laboratorios_de_paciente(self.conn, pid):
            if self._matches(lab.prueba, concept):
                data.append(
                    ClinicalDatum(
                        concept=concept,
                        value=lab.valor,
                        unit=lab.unidad,
                        observed_at=datetime.fromisoformat(lab.fecha),
                        source=f"Laboratorio: {lab.prueba}",
                        source_id=f"lab-{lab.id}",
                        episode_id=f"consulta-{lab.consulta_id}" if lab.consulta_id else None,
                    )
                )

        for biomarker in biomarcadores_de_paciente(self.conn, pid):
            if self._matches(biomarker.biomarcador, concept):
                data.append(
                    ClinicalDatum(
                        concept=concept,
                        value=biomarker.resultado,
                        unit=None,
                        observed_at=datetime.fromisoformat(biomarker.fecha),
                        source=f"Biomarcador: {biomarker.biomarcador}",
                        source_id=f"biomarcador-{biomarker.id}",
                        episode_id=f"consulta-{biomarker.consulta_id}" if biomarker.consulta_id else None,
                    )
                )

        return data

    def directorio_pacientes(self) -> list[PacienteRef]:
        return [
            PacienteRef(id=str(p.id), nombre=p.nombre, identificacion=p.identificacion)
            for p in listar_pacientes(self.conn)
        ]
