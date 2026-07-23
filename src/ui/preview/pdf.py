import hashlib
from io import BytesIO

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


def show_pdf(data: bytes, s3_key: str, documents: list) -> None:
    annotations = _annotations(documents, s3_key, data)
    pdf_viewer(
        input=data,
        key=f"pdf_{hashlib.md5(data).hexdigest()}",
        width="100%",
        height=1100,
        annotations=annotations,
        scroll_to_page=annotations[0]["page"] if annotations else None,
        render_text=True,
        show_page_separator=True,
    )
