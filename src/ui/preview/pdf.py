import hashlib
from io import BytesIO

import streamlit as st
from pypdf import PdfReader
from streamlit_pdf_viewer import pdf_viewer

from .metadata import doc_metadata


def _annotations(
    documents: list, s3_key: str, data: bytes, color: str = "red"
) -> list[dict]:
    """Рамки вокруг найденных чанков по bbox от docling."""
    pages = PdfReader(BytesIO(data)).pages
    result = []

    for doc in documents:
        meta = doc_metadata(doc)
        if meta.get("s3_key") != s3_key:
            continue

        for item in meta.get("doc_items", []):
            for prov in item.get("prov", []):
                bbox = prov.get("bbox", {})
                if bbox.get("coord_origin") != "BOTTOMLEFT":
                    continue

                page_no = prov["page_no"]
                page_height = float(pages[page_no - 1].mediabox.height)
                result.append(
                    {
                        "page": page_no,
                        "x": bbox["l"],
                        "y": page_height - bbox["t"],
                        "width": bbox["r"] - bbox["l"],
                        "height": bbox["t"] - bbox["b"],
                        "color": color,
                    }
                )
    return result


# Стартовый объём рендера. Раньше в DOM уходили ВСЕ страницы разом — на
# больших PDF модалка «замирала» на секунды. Теперь сперва только страницы
# с найденными фрагментами (или первые страницы), остальное — по кнопке.
_INITIAL_PAGES = 8


def show_pdf(data: bytes, s3_key: str, documents: list) -> None:
    annotations = _annotations(documents, s3_key, data)

    # Без подсветки тяжёлый компонент не нужен: нативный st.pdf открывается
    # заметно быстрее (стриминг вместо рендера всех страниц в DOM).
    #
    # Проверка hasattr(st, "pdf") тут когда-то стояла и не работала: атрибут
    # есть всегда, а нужный компонент ставится экстрой streamlit[pdf] — без
    # неё вызов падал StreamlitAPIException прямо в модалке. Экстра объявлена
    # в зависимостях, поэтому проверять нечего.
    if not annotations:
        st.pdf(data, height=1100)
        return

    total = len(PdfReader(BytesIO(data)).pages)

    marked = sorted({a["page"] for a in annotations})
    initial = marked or list(range(1, min(_INITIAL_PAGES, total) + 1))
    partial = total > len(initial)

    show_all = False
    if partial:
        note = (
            f"Показаны страницы с найденными фрагментами ({len(initial)} из {total})"
            if marked
            else f"Показаны первые {len(initial)} из {total} страниц"
        )
        show_all = st.toggle(f"📖 Весь документ — {note}", key=f"all_{s3_key}")

    limited = partial and not show_all
    pdf_viewer(
        input=data,
        key=f"pdf_{hashlib.md5(data).hexdigest()}_{show_all}",
        width="100%",
        height=1100,
        annotations=annotations,
        **({"pages_to_render": initial} if limited else {}),
        scroll_to_page=annotations[0]["page"],
        # Текстовый слой не нужен: подсветка — рамки по координатам, а
        # text-layer заставляет pdf.js рендерить каждую страницу дважды.
        render_text=False,
        show_page_separator=True,
    )
