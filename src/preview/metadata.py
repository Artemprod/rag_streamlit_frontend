from typing import Any


def doc_metadata(doc: Any) -> dict:
    """Единая точка доступа к метаданным чанка."""
    if isinstance(doc, dict):
        return doc.get("metadata") or doc
    return getattr(doc, "metadata", {}) or {}