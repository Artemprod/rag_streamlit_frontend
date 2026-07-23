"""Сайдбар: бренд, статус сервисов и ненавязчивая подсказка «как это работает».

Статус показываем спокойными цветными точками — сразу видно, готов ли поиск,
но без модальных окон и красных баннеров, которые давят на пользователя.
"""

import streamlit as st

from config import config
from services import retrieval_client


def render_brand() -> None:
    st.markdown("### 📚 RAG Документы")
    st.caption("Загрузка, поиск и просмотр документов")


def render_status() -> None:
    """Компактный статус сервисов: 🟢 готов / ⚪ не подключён."""
    process_ok = bool(config.process_api_key)
    search_ok = retrieval_client.is_configured()

    st.caption(
        f"{'🟢' if search_ok else '⚪'} Поиск ответов "
        f"{'подключён' if search_ok else 'не подключён'}"
    )
    st.caption(
        f"{'🟢' if process_ok else '⚪'} Обработка "
        f"{'подключена' if process_ok else 'не подключена'}"
    )


def render_help() -> None:
    with st.expander("Как это работает"):
        st.markdown(
            "1. **Загрузка** — добавьте документы, они уйдут на обработку "
            "(векторизация + граф).\n"
            "2. **Чат** — задайте вопрос: ответ соберётся по вашим документам.\n"
            "3. **Источники** — кликните файл под ответом, чтобы открыть его "
            "с подсветкой найденного фрагмента."
        )
