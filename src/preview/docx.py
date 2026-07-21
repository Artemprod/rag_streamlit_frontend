from io import BytesIO
from xml.sax.saxutils import escape

import mammoth
import streamlit as st


def _highlight(html: str, documents: list, s3_key: str) -> str:
    from . import doc_metadata

    for doc in documents:
        meta = doc_metadata(doc)
        if meta.get("s3_key") != s3_key:
            continue

        text = (doc.get("text") if isinstance(doc, dict) else getattr(doc, "text", "")).strip()
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