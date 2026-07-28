"""
Работа с S3/MinIO: фоновая заливка исходников и кэшированное чтение.

Один S3FileSystem на процесс. Заливка — в пуле потоков, чтобы не блокировать
рендер Streamlit. Чтение кэшируется, чтобы не качать объект на каждый rerun.
"""

import errno
import threading
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
    wait_random_exponential,
)

from config import config

_UPLOAD_CONCURRENCY = 4
_executor = ThreadPoolExecutor(
    max_workers=_UPLOAD_CONCURRENCY, thread_name_prefix="s3-upload"
)

_TRANSIENT_ERRNOS = frozenset(
    {errno.EBUSY, errno.EAGAIN, errno.ETIMEDOUT, errno.ECONNRESET, errno.EPIPE}
)

_RETRY_ATTEMPTS = 10
_RETRY_MAX_WAIT = 60


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
    parts = [
        part
        for part in PurePosixPath(name.replace("\\", "/")).parts
        if part not in ("", "/", "..")
    ]
    return "/".join(parts) or "file"


def _log_retry(state) -> None:
    logger.warning(
        "S3 отбил запись {} (попытка {} из {}): {}. Повторяю…",
        state.args[0] if state.args else "?",
        state.attempt_number,
        _RETRY_ATTEMPTS,
        state.outcome.exception(),
    )


@retry(
    retry=retry_if_exception(_is_transient),
    stop=stop_after_attempt(_RETRY_ATTEMPTS),
    wait=wait_random_exponential(multiplier=1, max=_RETRY_MAX_WAIT),
    before_sleep=_log_retry,
    reraise=True,
)
def _write(key: str, data: bytes) -> None:
    """Одна попытка записи объекта с предварительным абортом «висящих» multipart-загрузок.

    Причина 409 — незавершённый multipart от прошлого сбоя на том же ключе.
    Удаляем все такие загрузки перед PUT, чтобы исключить конфликт навсегда.
    """
    s3 = get_s3()
    bucket = config.s3_bucket
    object_key = key[len(bucket) + 1:]   # убираем "bucket/" из ключа

    try:
        # В текущей версии s3fs list_multipart_uploads может не принимать prefix,
        # поэтому получаем все и фильтруем сами.
        for upload in s3.list_multipart_uploads(bucket=bucket):
            if upload["Key"] == object_key:
                logger.warning(
                    "Найден незавершённый multipart для {}, абортирую (upload_id={})",
                    key, upload["UploadId"]
                )
                s3.abort_multipart_upload(
                    bucket=bucket,
                    key=object_key,
                    upload_id=upload["UploadId"],
                )
    except Exception as exc:
        logger.warning(
            "Не удалось проверить/абортировать multipart для {}: {}", key, exc
        )

    s3.pipe_file(key, data)


def _put(key: str, data: bytes) -> str:
    """Выполняется в фоновом потоке — никаких st.* внутри."""
    try:
        _write(key, data)
    except Exception as error:
        logger.error("Не удалось залить {} в S3: {}", key, error)
        raise
    return key


_in_flight: dict[str, Future] = {}
_in_flight_lock = threading.Lock()


def _submit(key: str, data: bytes) -> Future:
    with _in_flight_lock:
        future = _in_flight.get(key)
        if future is not None and not future.done():
            return future
        future = _executor.submit(_put, key, data)
        _in_flight[key] = future
        future.add_done_callback(lambda f, key=key: _forget(key, f))
        return future


def _forget(key: str, future: Future) -> None:
    with _in_flight_lock:
        if _in_flight.get(key) is future:
            del _in_flight[key]


def upload_async(uploaded_files: list) -> list[tuple[str, Future]]:
    pairs = []
    seen: set[str] = set()
    for file in uploaded_files:
        key = f"{config.s3_bucket}/{_safe_key(file.name)}"
        if key in seen:
            continue
        seen.add(key)
        pairs.append((file.name, _submit(key, file.getvalue())))
    return pairs


@st.cache_data(show_spinner="Загружаю файл…", max_entries=32)
def read(s3_key: str) -> bytes:
    """Байты объекта. Кэш — чтобы не качать при каждом ререндере Streamlit."""
    return get_s3().cat_file(s3_key)