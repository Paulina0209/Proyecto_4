from __future__ import annotations

from pathlib import Path
from typing import Iterable

import yaml

from .models import EvidenceDocument


def _portable(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def load_guideline_catalog(root: Path | str = Path('.')) -> list[EvidenceDocument]:
    root = Path(root).resolve()
    guidelines_dir = root / 'guidelines'
    documents: list[EvidenceDocument] = []

    for metadata_path in sorted(guidelines_dir.glob('*/metadata.yaml')):
        payload = yaml.safe_load(metadata_path.read_text(encoding='utf-8')) or {}
        source = payload.get('source') or {}
        validation = payload.get('validation') or {}
        publication_year = source.get('publication_year')
        publication_date = source.get('published_online') or (
            str(publication_year) if publication_year is not None else None
        )
        documents.append(
            EvidenceDocument(
                module_id=str(payload.get('module_id') or metadata_path.parent.name),
                organization=str(payload.get('organization') or ''),
                title=str(source.get('title') or payload.get('name') or ''),
                publication_date=str(publication_date) if publication_date is not None else None,
                publication_year=int(publication_year) if publication_year is not None else None,
                doi=str(source.get('doi')) if source.get('doi') else None,
                source_path=_portable(metadata_path, root),
                clinical_scope=dict(payload.get('clinical_scope') or {}),
                development_status=payload.get('development_status'),
                licensing_status=payload.get('licensing_status') or 'not_recorded',
                validation_status=validation.get('clinical_validation_status') or 'not_recorded',
            )
        )
    return documents
