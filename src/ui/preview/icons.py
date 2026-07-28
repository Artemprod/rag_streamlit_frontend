from pathlib import PurePosixPath

# Только форматы, которые принимает загрузка; остальное получит иконку
# по умолчанию.
_ICONS = {
    ".pdf": ":material/picture_as_pdf:",
    ".csv": ":material/table_chart:",
    ".xlsx": ":material/table_chart:",
    ".xls": ":material/table_chart:",
    ".txt": ":material/article:",
    ".md": ":material/article:",
    ".docx": ":material/description:",
    ".pptx": ":material/slideshow:",
}


def icon_for(s3_key: str) -> str:
    return _ICONS.get(PurePosixPath(s3_key).suffix.lower(), ":material/description:")
