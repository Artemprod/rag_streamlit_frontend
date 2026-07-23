"""Инициализация ключей st.session_state в одном месте.

Держим все дефолты здесь, чтобы страницы не дублировали setdefault и чтобы
структура состояния была видна с одного взгляда.
"""

import streamlit as st

# Значения по умолчанию для всего пользовательского состояния сессии.
_DEFAULTS: dict = {
    # Чат: история сообщений [{role, content, sources}]
    "messages": [],
    # Ключ выбранного для просмотра файла (s3_key) и его источники
    "selected_file": None,
    "selected_sources": [],
    # Загрузка: фьючерсы фоновой заливки в S3 и метаданные пакета
    "upload_futures": None,
    "upload_meta": None,
    # Инкремент для сброса виджетов file_uploader после отправки
    "uploader_key": 0,
    # История поставленных на обработку пакетов [{...}]
    "jobs": [],
}


def init_state() -> None:
    """Идемпотентно проставляет дефолты. Вызывать один раз на старте app.py."""
    for key, value in _DEFAULTS.items():
        # list/dict копируем, чтобы сессии не делили один и тот же объект.
        st.session_state.setdefault(
            key, value.copy() if isinstance(value, list | dict) else value
        )
