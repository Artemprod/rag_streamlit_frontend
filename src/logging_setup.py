"""Логирование фронта: один loguru на процесс, дефолтный формат.

Streamlit и библиотеки пишут через stdlib logging — перехватываем их, чтобы
весь лог шёл одним форматом.
"""

import inspect
import logging
import os
import sys

from loguru import logger

_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Болтливые чужие логгеры: оставляем только WARNING и выше. httpx здесь
# потому, что health-пробы и поллинг статуса идут раз в 1–2 секунды и
# забивали лог целиком.
_QUIET = (
    "httpx",
    "httpcore",
    "botocore",
    "s3fs",
    "fsspec",
    "watchdog",
    "tornado",
    "PIL",
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

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def setup_logging() -> None:
    """Идемпотентно: Streamlit переисполняет скрипт на каждый rerun."""
    logger.remove()
    logger.add(
        sys.stderr,
        level=_LEVEL,
        backtrace=True,
        # diagnose=False обязателен: иначе loguru печатает значения переменных
        # из кадров стека, а там ходят пароль админа и секрет cookie.
        diagnose=False,
    )
    logging.basicConfig(handlers=[_InterceptHandler()], level=logging.NOTSET, force=True)
    for name in _QUIET:
        logging.getLogger(name).setLevel(logging.WARNING)
