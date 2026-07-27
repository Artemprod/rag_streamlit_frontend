"""Работа с S3/MinIO: фоновая заливка исходников и кэшированное чтение.

Один S3FileSystem на процесс. Заливка — в пуле потоков, чтобы не блокировать
рендер Streamlit. Чтение кэшируется, чтобы не качать объект на каждый rerun.
"""

import errno
from concurrent.futures import Future, ThreadPoolExecutor
from functools import lru_cache
from pathlib import PurePosixPath

import s3fs
import streamlit as st
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from config import config

# Небольшой пул: заливки идут в фоне, UI остаётся отзывчивым.
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="s3-upload")

# Временные отказы хранилища. s3fs переводит коды S3 в OSError с errno:
#   EBUSY  — OperationAborted (409, «conflicting conditional operation»),
#            SlowDown/503 — конкурентные операции над бакетом, троттлинг;
#   EAGAIN/ETIMEDOUT/ECONNRESET — сетевые срывы.
# Сам s3fs такие ошибки НЕ ретраит (retry только на SlowDown-строке и
# сетевых исключениях), поэтому одиночный 409 ронял всю заливку.
_TRANSIENT_ERRNOS = frozenset(
    {errno.EBUSY, errno.EAGAIN, errno.ETIMEDOUT, errno.ECONNRESET, errno.EPIPE}
)


def _is_transient(error: BaseException) -> bool:
    return isinstance(error, OSError) and error.errno in _TRANSIENT_ERRNOS


@lru_cache(maxsize=1)
def get_s3() -> s3fs.S3FileSystem:
    return s3fs.S3FileSystem(
        key=config.s3_access_key,
        secret=config.s3_secret_key,
        endpoint_url=config.s3_endpoint_url,
        client_kwargs={"region_name": config.s3_region} if config.s3_region else None,
    )


def _safe_key(name: str) -> str:
    """Относительный путь → безопасный ключ внутри бакета.

    Сохраняем структуру папок (важно при загрузке директории, иначе
    a/report.pdf и b/report.pdf схлопнутся), но убираем ведущие слэши и
    обход каталогов (`..`), чтобы не выйти за пределы бакета.
    """
    parts = [
        part
        for part in PurePosixPath(name.replace("\\", "/")).parts
        if part not in ("", "/", "..")
    ]
    return "/".join(parts) or "file"


@retry(
    retry=retry_if_exception(_is_transient),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
def _write(key: str, data: bytes) -> None:
    """Одна попытка записи объекта. Ретраится только на временных отказах."""
    with get_s3().open(key, "wb") as dst:
        dst.write(data)


def _put(name: str, data: bytes) -> str:
    """Выполняется в фоновом потоке — никаких st.* внутри.

    Возвращает durable s3_key вида 'bucket/dir/file.pdf'.
    """
    key = f"{config.s3_bucket}/{_safe_key(name)}"
    try:
        _write(key, data)
    except Exception as error:
        logger.error("Не удалось залить {} в S3: {}", key, error)
        raise
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
