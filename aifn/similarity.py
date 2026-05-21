from __future__ import annotations

from difflib import SequenceMatcher

from .registry import FunctionRecord, Registry


def find_similar(registry: Registry, query: str, threshold: float = 0.72) -> list[tuple[float, FunctionRecord]]:
    matches: list[tuple[float, FunctionRecord]] = []
    for record in registry.records.values():
        candidates = [record.canonical_name, *record.aliases, record.description, *record.tags]
        score = max(SequenceMatcher(None, query.lower(), c.lower()).ratio() for c in candidates if c)
        if score >= threshold:
            matches.append((score, record))
    return sorted(matches, key=lambda item: item[0], reverse=True)
