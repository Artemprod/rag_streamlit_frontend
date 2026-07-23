"""Отрисовка документов-источников под ответом.

Каждый источник — кликабельная карточка: клик выбирает файл для просмотра
в правой колонке (проставляет selected_file и связанные с ним источники).
"""

from pathlib import PurePosixPath

import streamlit as st

from ui.preview import doc_metadata, icon_for


def _source_key(doc: dict) -> str | None:
    return doc_metadata(doc).get("s3_key")


def render_sources(documents: list[dict], *, ns: str) -> None:
    """Показывает уникальные файлы-источники как кнопки.

    ns — префикс для ключей виджетов, чтобы кнопки в разных сообщениях чата
    не конфликтовали.
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
            st.session_state.selected_file = s3_key
            st.session_state.selected_sources = documents
            st.rerun()
