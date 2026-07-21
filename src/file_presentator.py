import hashlib
import json
from pathlib import Path
from typing import Any

import mammoth
import pandas as pd
import streamlit as st
from pypdf import PdfReader
from st_aggrid import AgGrid, GridOptionsBuilder
from streamlit_pdf_viewer import pdf_viewer


def _show_table(df: pd.DataFrame, key: str):
    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(resizable=True, filterable=True, sortable=True)
    gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=50)
    AgGrid(
        df, gridOptions=gb.build(), height=600, fit_columns_on_grid_load=True, key=key
    )


st.set_page_config(layout="wide")

if "selected_file" not in st.session_state:
    st.session_state.selected_file = None


def icon_for(path: Path) -> str:
    ext = path.suffix.lower()
    icons = {
        ".pdf": ":material/picture_as_pdf:",
        ".png": ":material/image:",
        ".jpg": ":material/image:",
        ".jpeg": ":material/image:",
        ".webp": ":material/image:",
        ".gif": ":material/image:",
        ".svg": ":material/image:",
        ".csv": ":material/table_chart:",
        ".xlsx": ":material/table_chart:",
        ".xls": ":material/table_chart:",
        ".txt": ":material/article:",
        ".md": ":material/article:",
        ".py": ":material/article:",
        ".json": ":material/article:",
        ".yaml": ":material/article:",
        ".yml": ":material/article:",
        ".mp4": ":material/movie:",
        ".mov": ":material/movie:",
        ".avi": ":material/movie:",
        ".mp3": ":material/audio_file:",
        ".wav": ":material/audio_file:",
        ".ogg": ":material/audio_file:",
    }
    return icons.get(ext, ":material/description:")


def doc_metadata(doc: Any):
    """Единая точка доступа к метаданным."""
    if isinstance(doc, dict):
        return doc.get("metadata") or doc
    return getattr(doc, "metadata", {})


def _render_html_safe(html_content: str, *, padding: int = 48) -> None:
    """Единая функция для рендера HTML с белым фоном."""
    styled_html = f"""
    <div style="
        background-color: #ffffff;
        color: #1a1a1a;
        padding: {padding}px 40px;
        border-radius: 8px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.08);
        max-width: 100%;
        margin: 0 auto;
        line-height: 1.75;
        font-size: 15.5px;
    ">
        {html_content}
    </div>
    """
    st.html(styled_html)


def _show_docx(path: Path, bd_documents: list | None = None):
    """Улучшенный рендер DOCX с подсветкой."""
    with path.open("rb") as f:
        result = mammoth.convert_to_html(f)

    # Предупреждения (оставляем в expander)
    if result.messages:
        with st.expander("⚠️ Предупреждения конвертации DOCX", expanded=False):
            for msg in result.messages:
                st.caption(str(msg))

    html_content = result.value

    # === ПОДСВЕТКА НАЙДЕННОГО ТЕКСТА ===
    if bd_documents:
        for doc in bd_documents:
            meta = doc_metadata(doc)
            file_path = (
                meta.get("file_path")
                if isinstance(meta, dict)
                else getattr(meta, "file_path", None)
            )

            if str(file_path) != str(path):
                continue

            text_to_find = (
                doc.get("page_content")
                if isinstance(doc, dict)
                else getattr(doc, "page_content", "")
            ).strip()

            if not text_to_find or text_to_find not in html_content:
                continue

            # Правильное экранирование
            escaped = (
                text_to_find.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )

            highlighted = (
                f'<mark style="'
                f"background-color: #fff176; "
                f"color: black; "
                f"padding: 3px 7px; "
                f"border-radius: 4px; "
                f"font-weight: 500; "
                f'box-shadow: 0 0 0 2px rgba(255, 235, 59, 0.4);">'
                f"{escaped}"
                f"</mark>"
            )

            html_content = html_content.replace(
                text_to_find, highlighted, 1
            )  # первое совпадение

    _render_html_safe(html_content)


def build_annotations(
    bd_documents: list, pdf_path: Path, color: str = "red"
) -> list[dict]:
    """Аннотации для PDF (без изменений — хорошо)."""
    pages = PdfReader(pdf_path).pages
    annotations = []

    for doc in bd_documents:
        meta = doc_metadata(doc)
        if Path(str(meta.get("file_path", ""))) != pdf_path:
            continue

        for item in meta.get("doc_items", []):
            for prov in item.get("prov", []):
                bbox = prov.get("bbox", {})
                if bbox.get("coord_origin") != "BOTTOMLEFT":
                    continue

                page_no = prov["page_no"]
                page_h = float(pages[page_no - 1].mediabox.height)

                annotations.append(
                    {
                        "page": page_no,
                        "x": bbox["l"],
                        "y": page_h - bbox["t"],
                        "width": bbox["r"] - bbox["l"],
                        "height": bbox["t"] - bbox["b"],
                        "color": color,
                    }
                )
    return annotations


def preview_file(path: Path, bd_documents: list | None = None):
    """Главный диспетчер предпросмотра."""
    ext = path.suffix.lower()
    st.subheader(path.name)

    match ext:
        case ".pdf":
            annotations = build_annotations(bd_documents or [], path)
            pdf_viewer(
                input=path.as_posix(),
                key=hashlib.md5(path.read_bytes()).hexdigest(),
                width="100%",
                height=1100,
                zoom_level=1.0,
                viewer_align="left",
                show_page_separator=True,
                render_text=True,
                annotations=annotations,
                scroll_to_page=annotations[0]["page"] if annotations else None,
            )

        case ".png" | ".jpg" | ".jpeg" | ".webp" | ".gif" | ".svg":
            st.image(path, use_column_width=True)  # лучше чем width="stretch"

        case ".docx":
            _show_docx(path, bd_documents)

        case ".csv":
            _show_table(pd.read_csv(path), key=f"aggrid_{path.as_posix()}")

        case ".xlsx" | ".xls":
            excel = pd.ExcelFile(path)
            sheet = st.selectbox(
                "Лист Excel", excel.sheet_names, key=f"sheet_{path.as_posix()}"
            )
            df = pd.read_excel(path, sheet_name=sheet)
            _show_table(df, key=f"aggrid_{path.as_posix()}_{sheet}")

        case ".json":
            st.json(json.loads(path.read_text(encoding="utf-8")))

        case ".txt" | ".md" | ".py" | ".yaml" | ".yml":
            text = path.read_text(encoding="utf-8", errors="ignore")
            st.code(
                text,
                language="python" if ext == ".py" else None,
                height=650,
                wrap_lines=True,
            )

        case ".mp4" | ".mov":
            st.video(path)

        case ".mp3" | ".wav" | ".ogg":
            st.audio(path)

        case ".html" | ".htm":
            st.iframe(str(path), height=700)

        case _:
            st.warning("Для этого типа файла нет предпросмотра.")
            st.download_button(
                "Скачать файл",
                data=path.read_bytes(),
                file_name=path.name,
                icon=":material/download:",
            )
