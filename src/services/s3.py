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

# Повторы со СЛУЧАЙНОЙ паузой. Джиттер обязателен: при обычной экспоненте все
# потоки падают почти одновременно и повторяют в одни и те же моменты
# (1с, 2с, 4с…), то есть заново сталкиваются на бакете.
#
# Терпение при этом бесполезно, и логи это доказали: конфликт из-за зависшей
# multipart-загрузки держится на ключе, пока её не отменят, — файл выгорал
# все десять попыток за полторы минуты и терялся. Поэтому окно короткое:
# оно ловит настоящие транзитные сбои (сеть, троттлинг), а «вечный» 409
# лечится не ожиданием, а очисткой ключа (см. _abort_stale_uploads).
_RETRY_ATTEMPTS = 5
_RETRY_MAX_WAIT = 15


def _is_transient(error: BaseException) -> bool:
    return isinstance(error, OSError) and error.errno in _TRANSIENT_ERRNOS


@lru_cache(maxsize=1)
def get_s3() -> s3fs.S3FileSystem:
    return s3fs.S3FileSystem(
        key=config.s3_access_key,
        secret=config.s3_secret_key,
        endpoint_url=config.s3_endpoint_url,
        config_kwargs={"s3": {"addressing_style": "path"}},
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


def _stored_size(key: str) -> int | None:
    """Размер объекта в хранилище или None, если его там нет.

    Кэш s3fs сбрасываем: нас интересует, что в бакете сейчас, а не что он
    отдавал при прошлом листинге.
    """
    fs = get_s3()
    fs.invalidate_cache(key)
    try:
        return fs.info(key).get("size")
    except FileNotFoundError:
        return None
    except OSError as error:  # сеть/доступ — считаем, что не знаем
        logger.debug("Не удалось проверить {} в S3: {}", key, error)
        return None


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


def _abort_stale_uploads(key: str) -> int:
    """Отменяет зависшие multipart-загрузки этого ключа. Возвращает их число.

    Это и есть причина «вечного» 409. Незавершённая multipart-загрузка живёт
    на ключе, пока её не отменят: хранилище считает, что над объектом уже идёт
    операция, и отбивает любую новую запись — не секунды, а до тех пор, пока
    висит огрызок. Ретраи такое не пересиживают по определению.

    Огрызки остаются, когда заливку обрывают на полпути: пересобрали контейнер
    UI, перезапустили сервис, упала сеть. Ровно это и происходило: контейнер
    пересоздавали во время активных заливок, и страдали те самые файлы,
    которые были в полёте.
    """
    bucket, _, name = key.partition("/")
    fs = get_s3()
    try:
        uploads = fs.list_multipart_uploads(bucket)
    except Exception as error:
        logger.debug("Не удалось получить список незавершённых загрузок: {}", error)
        return 0

    aborted = 0
    for upload in [item for item in uploads if item.get("Key") == name]:
        try:
            fs.abort_mpu(bucket, name, upload["UploadId"])
            aborted += 1
        except Exception as error:
            logger.warning("Не удалось отменить зависшую загрузку {}: {}", key, error)
    if aborted:
        logger.warning("{}: отменено зависших загрузок — {}", key, aborted)
    return aborted


def _put(key: str, data: bytes) -> str:
    """Выполняется в фоновом потоке — никаких st.* внутри.

    Порядок действий выстроен от дешёвого к дорогому:

    1. Файл уже лежит в хранилище нужного размера — не переливаем. Повторная
       загрузка того же набора документов дело обычное, а лишняя перезапись
       это ещё и лишний повод для конфликта.
    2. Обычная запись с повторами.
    3. Не вышло — проверяем, не долетел ли объект всё-таки (ответ мог
       потеряться уже после записи).
    4. Всё ещё нет — снимаем с ключа зависшие multipart-загрузки и пробуем
       последний раз. Это единственное, что реально снимает «вечный» 409.
    """
    if _stored_size(key) == len(data):
        logger.info("{} уже в хранилище, заливка не нужна", key)
        return key

    try:
        _write(key, data)
        return key
    except Exception as error:
        if _stored_size(key) == len(data):
            logger.warning("{}: запись отбита ({}), но файл в хранилище", key, error)
            return key
        if not _abort_stale_uploads(key):
            logger.error("Не удалось залить {} в S3: {}", key, error)
            raise

    try:
        _write(key, data)
    except Exception as error:
        logger.error("Не удалось залить {} в S3 после очистки: {}", key, error)
        raise
    logger.info("{}: залит после отмены зависших загрузок", key)
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