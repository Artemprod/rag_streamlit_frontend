"""Работа с S3/MinIO: фоновая заливка исходников и кэшированное чтение.

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


def _put(key: str, data: bytes) -> str:
    """Выполняется в фоновом потоке — никаких st.* внутри."""
    try:
        _write(key, data)
    except Exception as error:
        logger.error("Не удалось залить {} в S3: {}", key, error)
        raise
    return key


# Заливки, идущие прямо сейчас, по ключу. Два конкурентных PUT одного ключа
# (файл выбран и в «файлах», и в «папке»; повторная отправка при живой старой
# заливке после обновления страницы) — это 409 OperationAborted от хранилища
# на весь срок первой заливки, ретраи не спасают. Вместо второго PUT отдаём
# уже идущий future.
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
    """Байты читаем сразу (виджет живёт только до rerun), заливаем в фоне.

    Возвращает пары (имя файла, future c s3-ключом) — по одной на уникальный
    ключ: дубликаты выбора схлопываются в одну заливку.
    """
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
