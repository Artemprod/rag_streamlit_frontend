"""Единая настройка структурного логирования фронта.

Тот же формат, что у сервисов обработки и поиска: одна JSON-строка на запись,
чтобы логи всех трёх сервисов читались одним сборщиком. Streamlit и библиотеки
пишут через stdlib logging, поэтому перехватываем и их.
"""

import inspect
import logging
import os
import sys

from loguru import logger

_LEVEL = os.getenv("LOG_LEVEL", "INFO")
_SERIALIZE = os.getenv("LOG_JSON", "true").strip().lower() not in ("0", "false", "no")


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
        # и в логе не видно, кто её произвёл — uvicorn.access, sqlalchemy.engine
        # или что-то ещё. Для разбора инцидентов это ключевое поле.
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
        backtrace=True,
        # diagnose=False обязателен: иначе loguru печатает значения переменных
        # из кадров стека, а там ходят пароль админа и секрет cookie.
        diagnose=False,
    )
    logging.basicConfig(handlers=[_InterceptHandler()], level=logging.NOTSET, force=True)
