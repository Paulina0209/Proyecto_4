from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Iterable

from historia_clinica_mock.repository import Paciente

from .catalog import load_guideline_catalog
from .models import EvidenceDocument, EvidenceSearchResult


STOPWORDS = {
    'de', 'del', 'la', 'el', 'los', 'las', 'y', 'o', 'para', 'por', 'con', 'sin',
    'un', 'una', 'the', 'and', 'for', 'of', 'in', 'to', 'clinical', 'practice',
    'guideline', 'guidelines', 'diagnosis', 'treatment', 'follow', 'up',
    'evidence', 'term', 'nonexistent', 'cancer', 'clinical', 'clinica', 'paciente', 'patient', 'que',
}


def _normalize(text: str) -> str:
    text = unicodedata.normalize('NFKD', text or '')
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = re.sub(r'[^a-z0-9]+', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def _tokens(text: str) -> list[str]:
    return [t for t in _normalize(text).split() if len(t) >= 3 and t not in STOPWORDS]



CLINICAL_EXPANSIONS = {
    'cancer de mama': ('breast',),
    'mama': ('breast',),
    'triple negativo': ('triple negative', 'tnbc'),
    'pulmon no microcitico': ('nsclc', 'non small cell lung'),
    'no microcitico': ('nsclc',),
    'metastasico': ('metastatic',),
    'metastasis': ('metastatic',),
    'egfr': ('oncogene addicted', 'oncogene'),
    'her2': ('breast',),
    'pembrolizumab': ('pembrolizumab',),
}

def _expand_clinical_query(text: str) -> str:
    normalized = _normalize(text)
    additions: list[str] = []
    for phrase, expansions in CLINICAL_EXPANSIONS.items():
        if phrase in normalized:
            additions.extend(expansions)
    return text + ' ' + ' '.join(additions)

def _document_text(doc: EvidenceDocument) -> str:
    scope = ' '.join(f'{k} {v}' for k, v in doc.clinical_scope.items())
    return ' '.join([doc.module_id, doc.organization, doc.title, scope, doc.doi or ''])


class EvidenceSearchService:
    """EV-01 MVP: búsqueda local sobre evidencia versionada incluida en la plataforma."""

    def __init__(self, root: Path | str = Path('.')):
        self.root = Path(root)
        self.documents = load_guideline_catalog(self.root)

    def search(self, query: str, *, limit: int = 5) -> list[EvidenceSearchResult]:
        query_tokens = _tokens(_expand_clinical_query(query))
        if not query_tokens:
            return []

        results: list[EvidenceSearchResult] = []
        for doc in self.documents:
            doc_norm = _normalize(_document_text(doc))
            matched = []
            score = 0
            for token in query_tokens:
                if token in doc_norm:
                    matched.append(token)
                    # Los términos presentes en alcance clínico/módulo pesan más que una coincidencia genérica.
                    scope_norm = _normalize(' '.join(map(str, doc.clinical_scope.values())) + ' ' + doc.module_id)
                    score += 3 if token in scope_norm else 1
            if score:
                results.append(EvidenceSearchResult(doc, score, tuple(sorted(set(matched)))))

        results.sort(
            key=lambda r: (r.score, r.document.publication_year or 0, r.document.module_id),
            reverse=True,
        )
        if not results:
            return []

        # Evita llenar la pantalla con coincidencias débiles (p. ej. solo
        # "metastatic" en una guía de otro tumor). Se conserva lo que tenga
        # al menos la mitad del puntaje del mejor resultado.
        threshold = max(1, (results[0].score + 1) // 2)
        relevant = [r for r in results if r.score >= threshold]
        return relevant[:limit]

    def search_for_patient(
        self,
        patient: Paciente,
        clinical_terms: Iterable[str] = (),
        *,
        limit: int = 5,
    ) -> list[EvidenceSearchResult]:
        query_parts = [patient.diagnostico_principal or '', patient.estadio or '', *clinical_terms]
        return self.search(' '.join(query_parts), limit=limit)
