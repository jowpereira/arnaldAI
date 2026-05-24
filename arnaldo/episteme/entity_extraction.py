"""Extração de entidades a partir de texto — backticks, URLs, proper nouns."""

from __future__ import annotations

import hashlib
import re

# Termos técnicos conhecidos (lowercase → canonical)
_KNOWN_TECH: set[str] = {
    "python",
    "javascript",
    "typescript",
    "react",
    "angular",
    "vue",
    "docker",
    "kubernetes",
    "redis",
    "postgresql",
    "mongodb",
    "fastapi",
    "django",
    "flask",
    "nodejs",
    "java",
    "rust",
    "golang",
    "terraform",
    "azure",
    "aws",
    "gcp",
    "graphql",
    "kafka",
    "rabbitmq",
    "nginx",
    "linux",
    "windows",
    "git",
    "github",
    "numpy",
    "pandas",
    "pytorch",
    "tensorflow",
    "networkx",
    "openai",
    "langchain",
}

_URL_RE = re.compile(r"https?://[^\s\)\"'>]+")
_BACKTICK_RE = re.compile(r"`([^`]+)`")
_PROPER_NOUN_RE = re.compile(r"\b([A-Z][a-zA-Z]*(?:\s+[A-Z][a-zA-Z]*)+)\b")


def extract_entities(text: str) -> list[tuple[str, str]]:
    """Extrai entidades do texto como lista de (name, type).

    Tipos: 'technology', 'url', 'concept'.
    """
    seen: dict[str, str] = {}

    # 1) Backticks → technology
    for match in _BACKTICK_RE.finditer(text):
        name = match.group(1).strip()
        if name and name.lower() not in seen:
            seen[name.lower()] = "technology"

    # 2) URLs
    for match in _URL_RE.finditer(text):
        url = match.group(0).rstrip(".,;:")
        if url.lower() not in seen:
            seen[url.lower()] = "url"

    # 3) Proper nouns (≥2 capitalized words)
    for match in _PROPER_NOUN_RE.finditer(text):
        name = match.group(1).strip()
        key = name.lower()
        if key not in seen:
            seen[key] = "concept"

    # 4) Termos técnicos soltos no texto
    for word in re.findall(r"\b[A-Za-z]+\b", text):
        low = word.lower()
        if low in _KNOWN_TECH and low not in seen:
            seen[low] = "technology"

    # Reconstruir com nomes canônicos
    result: list[tuple[str, str]] = []
    added: set[str] = set()
    # Re-scan na mesma ordem das regex para manter determinismo
    for match in _BACKTICK_RE.finditer(text):
        name = match.group(1).strip()
        key = name.lower()
        if key not in added and key in seen:
            result.append((name, seen[key]))
            added.add(key)
    for match in _URL_RE.finditer(text):
        url = match.group(0).rstrip(".,;:")
        key = url.lower()
        if key not in added and key in seen:
            result.append((url, seen[key]))
            added.add(key)
    for match in _PROPER_NOUN_RE.finditer(text):
        name = match.group(1).strip()
        key = name.lower()
        if key not in added and key in seen:
            result.append((name, seen[key]))
            added.add(key)
    for word in re.findall(r"\b[A-Za-z]+\b", text):
        low = word.lower()
        if low not in added and low in seen:
            result.append((word, seen[low]))
            added.add(low)

    return result


def entity_node_id(name: str) -> str:
    """ID determinístico para nó de entidade."""
    return f"ent_{hashlib.sha256(name.lower().encode()).hexdigest()[:12]}"
