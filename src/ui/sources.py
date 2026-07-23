"""Отрисовка документов-источников под ответом.

Каждый источник — кликабельная карточка: клик передаётся в on_select
(на странице чата открывает документ в модальном окне).
"""

from collections.abc import Callable
from pathlib import PurePosixPath

import streamlit as st

from ui.preview import doc_metadata, icon_for


def _source_key(doc: dict) -> str | None:
    return doc_metadata(doc).get("s3_key")


def render_sources(
    documents: list[dict],
    *,
    ns: str,
    on_select: Callable[[str, list[dict]], None],
) -> None:
    """Показывает уникальные файлы-источники как кнопки.

    ns — префикс ключей виджетов, чтобы кнопки в разных сообщениях чата
    не конфликтовали. on_select(s3_key, documents) вызывается по клику.
    """
    if not documents:
        return

    # Уникальные файлы в порядке появления.
    seen: dict[str, dict] = {}
    for doc in documents:
        key = _source_key(doc)
        if key and key not in seen:
            seen[key] = doc

    if not seen:
        return

    st.caption(f"📎 Источники ({len(seen)})")
    for s3_key, doc in seen.items():
        name = doc_metadata(doc).get("file_name") or PurePosixPath(s3_key).name
        if st.button(
            name,
            icon=icon_for(s3_key),
            width="stretch",
            key=f"src_{ns}_{s3_key}",
        ):
            on_select(s3_key, documents)
