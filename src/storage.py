from concurrent.futures import Future, ThreadPoolExecutor
from functools import lru_cache

import s3fs
import streamlit as st

from config import config

_executor = ThreadPoolExecutor(max_workers=4)


@lru_cache(maxsize=1)
def get_s3() -> s3fs.S3FileSystem:
    return s3fs.S3FileSystem(
        key=config.s3_access_key,
        secret=config.s3_secret_key,
        endpoint_url=config.s3_endpoint_url,
        client_kwargs={"region_name": config.s3_region} if config.s3_region else None,
    )


def _put(name: str, data: bytes) -> str:
    """Выполняется в фоновом потоке — никаких st.* внутри."""
    key = f"{config.s3_bucket}/{name}"
    with get_s3().open(key, "wb") as dst:
        dst.write(data)
    return key


def upload_async(uploaded_files: list) -> list[Future]:
    """Байты читаем сразу (виджет живёт только до rerun), заливаем в фоне.
    Возвращает futures со s3-ключами."""
    payload = [(file.name, file.getvalue()) for file in uploaded_files]
    return [_executor.submit(_put, name, data) for name, data in payload]


@st.cache_data(show_spinner="Загружаю файл...", max_entries=20)
def read(s3_key: str) -> bytes:
    """Байты объекта. Кэш — чтобы не качать при каждом ререндере Streamlit."""
    return get_s3().cat_file(s3_key)