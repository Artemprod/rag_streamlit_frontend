from typing import Any


def doc_metadata(doc: Any) -> dict:
    """Единая точка доступа к метаданным источника.

    Источник от retrieval-сервиса — dict вида {id, text, url, metadata}.
    Возвращаем именно вложенный metadata (там s3_key, file_name, doc_items).
    """
    if isinstance(doc, dict):
        return doc.get("metadata") or {}
    return getattr(doc, "metadata", {}) or {}


def doc_text(doc: Any) -> str:
    """Текст найденного фрагмента (для подсветки в предпросмотре)."""
    if isinstance(doc, dict):
        return (doc.get("text") or "").strip()
    return (getattr(doc, "text", "") or "").strip()
