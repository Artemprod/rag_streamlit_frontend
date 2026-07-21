import json
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any

import pandas as pd
import streamlit as st
import storage

from .docx import show_docx
from .icons import icon_for
from .pdf import show_pdf
from .table import show_table
from .metadata import doc_metadata

__all__ = ["preview_file", "icon_for", "doc_metadata"]

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
TEXT_EXTS = {".txt", ".md", ".py", ".yaml", ".yml"}



def preview_file(s3_key: str, documents: list | None = None) -> None:
    documents = documents or []
    name = PurePosixPath(s3_key).name
    ext = PurePosixPath(s3_key).suffix.lower()
    st.subheader(name)

    data = storage.read(s3_key)

    if ext == ".pdf":
        show_pdf(data, s3_key, documents)
    elif ext == ".docx":
        show_docx(data, s3_key, documents)
    elif ext in IMAGE_EXTS:
        st.image(data, use_container_width=True)
    elif ext == ".csv":
        show_table(pd.read_csv(BytesIO(data)), key=f"grid_{s3_key}")
    elif ext in {".xlsx", ".xls"}:
        excel = pd.ExcelFile(BytesIO(data))
        sheet = st.selectbox("Лист", excel.sheet_names, key=f"sheet_{s3_key}")
        show_table(excel.parse(sheet), key=f"grid_{s3_key}_{sheet}")
    elif ext == ".json":
        st.json(json.loads(data))
    elif ext in TEXT_EXTS:
        st.code(data.decode("utf-8", errors="ignore"), height=650, wrap_lines=True)
    elif ext in {".mp4", ".mov"}:
        st.video(data)
    elif ext in {".mp3", ".wav", ".ogg"}:
        st.audio(data)
    else:
        st.warning("Для этого типа файла нет предпросмотра.")
        st.download_button("Скачать", data=data, file_name=name)