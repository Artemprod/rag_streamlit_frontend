from pathlib import PurePosixPath

_ICONS = {
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
    ".json": ":material/article:",
    ".mp4": ":material/movie:",
    ".mov": ":material/movie:",
    ".mp3": ":material/audio_file:",
    ".wav": ":material/audio_file:",
}


def icon_for(s3_key: str) -> str:
    return _ICONS.get(PurePosixPath(s3_key).suffix.lower(), ":material/description:")