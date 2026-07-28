"""Диспетчер предпросмотра документов по типу файла.

Байты берём из S3 (кэшируются), рендерим по расширению. Для PDF/DOCX
подсвечиваем фрагменты, которые вернул ретривер (documents).
"""

from io import BytesIO
from pathlib import PurePosixPath

import pandas as pd
import streamlit as st

from services import s3

from .docx import show_docx
from .icons import icon_for
from .metadata import doc_metadata, doc_text
from .pdf import show_pdf
from .table import show_table

__all__ = ["doc_metadata", "doc_text", "icon_for", "preview_file"]

# Ровно те расширения, что принимает загрузка (см. SUPPORTED_EXTS сервиса
# обработки): другие в хранилище не попадают, а если попадут — сработает
# ветка со скачиванием.
TEXT_EXTS = {".txt", ".md"}


def preview_file(s3_key: str, documents: list | None = None) -> None:
    documents = documents or []
    name = PurePosixPath(s3_key).name
    ext = PurePosixPath(s3_key).suffix.lower()

    try:
        data = s3.read(s3_key)
    except Exception as error:
        st.error(f"Не удалось загрузить файл из хранилища: {error}")
        return

    if ext == ".pdf":
        show_pdf(data, s3_key, documents)
    elif ext == ".docx":
        show_docx(data, s3_key, documents)
    elif ext == ".csv":
        show_table(pd.read_csv(BytesIO(data)), key=f"grid_{s3_key}")
    elif ext in {".xlsx", ".xls"}:
        excel = pd.ExcelFile(BytesIO(data))
        sheet = st.selectbox("Лист", excel.sheet_names, key=f"sheet_{s3_key}")
        show_table(excel.parse(sheet), key=f"grid_{s3_key}_{sheet}")
    elif ext in TEXT_EXTS:
        st.code(data.decode("utf-8", errors="ignore"), height=650, wrap_lines=True)
    else:
        st.warning("Для этого типа файла нет предпросмотра.")
        st.download_button("Скачать", data=data, file_name=name)
