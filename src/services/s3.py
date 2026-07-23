"""Работа с S3/MinIO: фоновая заливка исходников и кэшированное чтение.

Один S3FileSystem на процесс. Заливка — в пуле потоков, чтобы не блокировать
рендер Streamlit. Чтение кэшируется, чтобы не качать объект на каждый rerun.
"""

from concurrent.futures import Future, ThreadPoolExecutor
from functools import lru_cache
from pathlib import PurePosixPath

import s3fs
import streamlit as st

from config import config

# Небольшой пул: заливки идут в фоне, UI остаётся отзывчивым.
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="s3-upload")


@lru_cache(maxsize=1)
def get_s3() -> s3fs.S3FileSystem:
    return s3fs.S3FileSystem(
        key=config.s3_access_key,
        secret=config.s3_secret_key,
        endpoint_url=config.s3_endpoint_url,
        client_kwargs={"region_name": config.s3_region} if config.s3_region else None,
    )


def _put(name: str, data: bytes) -> str:
    """Выполняется в фоновом потоке — никаких st.* внутри.

    Имя санитизируем до basename: у загрузки папки в name может быть путь.
    Возвращает durable s3_key вида 'bucket/file.pdf'.
    """
    safe_name = PurePosixPath(name).name
    key = f"{config.s3_bucket}/{safe_name}"
    with get_s3().open(key, "wb") as dst:
        dst.write(data)
    return key


def upload_async(uploaded_files: list) -> list[Future]:
    """Байты читаем сразу (виджет живёт только до rerun), заливаем в фоне.

    Возвращает futures со s3-ключами.
    """
    payload = [(file.name, file.getvalue()) for file in uploaded_files]
    return [_executor.submit(_put, name, data) for name, data in payload]


@st.cache_data(show_spinner="Загружаю файл…", max_entries=32)
def read(s3_key: str) -> bytes:
    """Байты объекта. Кэш — чтобы не качать при каждом ререндере Streamlit."""
    return get_s3().cat_file(s3_key)
