"""Единая настройка логирования фронта.

Тот же формат, что у сервисов обработки и поиска. По умолчанию — компактная
человекочитаемая строка (логи смотрят в `docker compose logs`), LOG_JSON=true
переключает на JSON для сборщика. Streamlit и библиотеки пишут через stdlib
logging, поэтому перехватываем и их.
"""

import inspect
import logging
import os
import sys

from loguru import logger

_LEVEL = os.getenv("LOG_LEVEL", "INFO")


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() not in ("0", "false", "no", "")


_SERIALIZE = _flag("LOG_JSON", "false")
_VERBOSE = _flag("LOG_VERBOSE", "false")

_TEXT_FORMAT = (
    "<green>{time:HH:mm:ss}</green> "
    "<level>{level: <7}</level> "
    "<cyan>{extra[source]}</cyan>  <level>{message}</level>"
)

# Поллинг статуса и health-пробы идут раз в 1–2 секунды: без фильтра лог
# состоит из них целиком, и настоящие события в нём не найти.
_MUTED_PATHS = ("/health", "/api/health", "/pipeline/status/")

_QUIET_LOGGERS = (
    "httpx",
    "httpcore",
    "urllib3",
    "botocore",
    "boto3",
    "aiobotocore",
    "s3fs",
    "fsspec",
    "asyncio",
    "watchdog",
    "PIL",
    "tornado",
)

_WARNING_NO = logging.WARNING


def _short_source(name: str) -> str:
    """'services.process_client' оставляем, длинные пути режем до двух частей."""
    parts = [part for part in name.split(".") if part != "src"]
    return ".".join(parts[-2:]) if len(parts) > 1 else name


def _sink_filter(record) -> bool:
    """Заполняет extra[source] и отсекает шум. Мутирует record — так задумано."""
    name = record["extra"].get("logger_name") or record["name"] or "app"
    record["extra"]["source"] = _short_source(name)

    if _VERBOSE or record["level"].no >= _WARNING_NO:
        return True

    if any(path in record["message"] for path in _MUTED_PATHS):
        return False

    return not any(
        name == quiet or name.startswith(quiet + ".") for quiet in _QUIET_LOGGERS
    )


class _InterceptHandler(logging.Handler):
    """Перекладывает записи stdlib logging в loguru, сохраняя место вызова."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Разматываем кадры стека, пока не выйдем из модуля logging, иначе в
        # логе источником окажется этот файл, а не настоящий вызывающий код.
        frame, depth = inspect.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1

        # bind(logger_name): без него в записи остаётся только модуль вызова,
        # и в логе не видно, кто её произвёл — httpx, streamlit или что-то ещё.
        logger.bind(logger_name=record.name).opt(
            depth=depth, exception=record.exc_info
        ).log(level, record.getMessage())


def setup_logging() -> None:
    """Идемпотентно: Streamlit переисполняет скрипт на каждый rerun."""
    logger.remove()
    logger.add(
        sys.stderr,
        level=_LEVEL,
        serialize=_SERIALIZE,
        format=_TEXT_FORMAT,  # при serialize=True loguru формат игнорирует
        filter=_sink_filter,
        backtrace=True,
        # diagnose=False обязателен: иначе loguru печатает значения переменных
        # из кадров стека, а там ходят пароль админа и секрет cookie.
        diagnose=False,
    )
    logging.basicConfig(handlers=[_InterceptHandler()], level=logging.NOTSET, force=True)
