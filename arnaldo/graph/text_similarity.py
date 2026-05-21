"""TF-IDF lightweight — similaridade textual sem dependências externas."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, List, Tuple

import numpy as np
from numpy.typing import NDArray

# Stopwords mínimas PT-BR + EN
_STOPWORDS = frozenset(
    "a o e de da do em um uma os as no na que é para por com não se "
    "mais ou seu sua ele ela um uma este esta esse essa aquele aquela "
    "the a an and or is in on of to for it at by be as with from this that "
    "are was were been has have had will would can could should may might".split()
)

_TOKEN_RE = re.compile(r"[a-záàâãéêíóôõúçñ]{2,}", re.IGNORECASE)


def tokenize(text: str) -> List[str]:
    """Tokeniza texto em palavras normalizadas."""
    return [w for w in _TOKEN_RE.findall(text.lower()) if w not in _STOPWORDS]


def _tf(tokens: List[str]) -> Dict[str, float]:
    """Term frequency normalizada."""
    counts = Counter(tokens)
    total = len(tokens) or 1
    return {term: count / total for term, count in counts.items()}


def _idf(corpus_tfs: List[Dict[str, float]]) -> Dict[str, float]:
    """Inverse document frequency."""
    n = len(corpus_tfs) or 1
    df: Dict[str, int] = Counter()
    for tf in corpus_tfs:
        for term in tf:
            df[term] += 1
    return {term: math.log(1 + n / count) for term, count in df.items()}


def cosine_sim(a: Dict[str, float], b: Dict[str, float]) -> float:
    """Cosine similarity entre dois vetores esparsos."""
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot = sum(a[k] * b[k] for k in common)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def tfidf_rank(
    query: str,
    documents: List[Tuple[str, str]],
    *,
    min_score: float = 0.05,
) -> List[Tuple[str, float]]:
    """Rankeia documentos por TF-IDF similarity com a query.

    Args:
        query: texto da query.
        documents: lista de (doc_id, doc_text).
        min_score: threshold mínimo de similaridade.

    Returns:
        Lista de (doc_id, score) ordenada por score desc.
    """
    if not query or not documents:
        return []

    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    doc_tfs = []
    for _, text in documents:
        doc_tfs.append(_tf(tokenize(text)))
    query_tf = _tf(query_tokens)

    # IDF computado sobre corpus + query
    all_tfs = [query_tf, *doc_tfs]
    idf = _idf(all_tfs)

    # TF-IDF vectors
    query_tfidf = {t: f * idf.get(t, 0) for t, f in query_tf.items()}

    results: List[Tuple[str, float]] = []
    for (doc_id, _), dtf in zip(documents, doc_tfs):
        doc_tfidf = {t: f * idf.get(t, 0) for t, f in dtf.items()}
        score = cosine_sim(query_tfidf, doc_tfidf)
        if score >= min_score:
            results.append((doc_id, score))

    results.sort(key=lambda x: x[1], reverse=True)
    return results


def _normalize(v: NDArray[np.float32]) -> NDArray[np.float32]:
    """L2-normaliza um vetor (cosine similarity = dot product após normalização)."""
    norm = float(np.linalg.norm(v))
    if norm == 0:
        return v
    return (v / norm).astype(np.float32)


def node_searchable_text(node: object) -> str:
    """Extrai texto buscável de um nó do grafo."""
    parts: List[str] = []
    label = getattr(node, "label", "")
    if label:
        # Label repetido para mais peso no TF-IDF
        parts.append(str(label))
        parts.append(str(label))
    # Tipo do nó como contexto
    kind = getattr(node, "kind", None)
    if kind is not None:
        parts.append(str(kind.value) if hasattr(kind, "value") else str(kind))
    payload = getattr(node, "payload", {})
    if isinstance(payload, dict):
        for key in (
            "action", "content", "summary", "description",
            "pattern", "searchable_text", "objective", "role",
        ):
            val = payload.get(key, "")
            if val and isinstance(val, str):
                parts.append(val)
        result = payload.get("result", {})
        if isinstance(result, dict):
            for rk in ("summary", "content"):
                rv = result.get(rk, "")
                if rv and isinstance(rv, str):
                    parts.append(rv)
    return " ".join(parts)
