"""Инициализация ключей st.session_state в одном месте.

Держим все дефолты здесь, чтобы страницы не дублировали setdefault и чтобы
структура состояния была видна с одного взгляда.
"""

import streamlit as st

# Значения по умолчанию для всего пользовательского состояния сессии.
_DEFAULTS: dict = {
    # Чат: история сообщений [{role, content, sources, mode}]
    "messages": [],
    # id сохранённого диалога (None — новый, ещё не сохранялся)
    "chat_id": None,
    # Идущий поиск ответа: {future, mode, phrases_html} или None. Живёт в
    # сессии, поэтому переключение вкладок его не убивает.
    "pending": None,
    # Загрузка: фьючерсы фоновой заливки в S3 и метаданные пакета
    "upload_futures": None,
    "upload_meta": None,
    # Залившиеся файлы, ждущие отправки пачкой: [(имя, future)]
    "upload_ready": [],
    # Инкремент для сброса виджетов file_uploader после отправки
    "uploader_key": 0,
    # Поставленные пакеты. Запись:
    #   job_id     — id задачи сервиса обработки (None, если постановка не удалась)
    #   status     — статус сервиса: queued / running / completed /
    #                completed_with_errors / failed, либо локальный upload_failed
    #   progress   — доля выполнения 0..1 из снимка статуса
    #   stats      — последний снимок счётчиков стадий (файлы/ноды)
    #   error      — текст ошибки, если есть
    "jobs": [],
}


def init_state() -> None:
    """Идемпотентно проставляет дефолты. Вызывать один раз на старте app.py."""
    for key, value in _DEFAULTS.items():
        # list/dict копируем, чтобы сессии не делили один и тот же объект.
        st.session_state.setdefault(
            key, value.copy() if isinstance(value, list | dict) else value
        )
