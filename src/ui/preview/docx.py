from io import BytesIO
from xml.sax.saxutils import escape

import mammoth
import streamlit as st

from .metadata import doc_metadata, doc_text


def _highlight(html: str, documents: list, s3_key: str) -> str:
    """Подсвечивает в тексте документа фрагменты, найденные ретривером."""
    for doc in documents:
        if doc_metadata(doc).get("s3_key") != s3_key:
            continue

        text = doc_text(doc)
        if not text or text not in html:
            continue

        mark = (
            '<mark style="background-color:#fff176;color:black;'
            'padding:3px 7px;border-radius:4px;">'
            f"{escape(text)}</mark>"
        )
        html = html.replace(text, mark, 1)
    return html


def show_docx(data: bytes, s3_key: str, documents: list) -> None:
    result = mammoth.convert_to_html(BytesIO(data))
    html = _highlight(result.value, documents, s3_key)

    st.html(
        f'<div style="background:#fff;color:#1a1a1a;padding:48px 40px;'
        f'border-radius:8px;line-height:1.75;font-size:15.5px;">{html}</div>'
    )
