"""Сайдбар: бренд (через st.logo, над меню), статус сервисов и подсказка.

Бренд рисуем нативным st.logo — он размещается над навигацией, поэтому
порядок «логотип → меню → статус» получается правильным без хаков.
Статус показываем спокойными цветными точками, без давящих баннеров.
"""

import base64

import streamlit as st

import auth
from config import config
from services import chats, process_client, retrieval_client

# SVG-вордмарк как data-URI: без бинарного ассета, цвета читаемы и на светлой,
# и на тёмной теме (иконка — градиент, «Документы» — нейтральный серый).
_LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="190" height="40" viewBox="0 0 190 40">
  <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#6366f1"/><stop offset="1" stop-color="#8b5cf6"/>
  </linearGradient></defs>
  <rect x="2" y="5" width="30" height="30" rx="8" fill="url(#g)"/>
  <g fill="#fff">
    <rect x="9" y="12" width="16" height="3.2" rx="1.6"/>
    <rect x="9" y="17.4" width="16" height="3.2" rx="1.6"/>
    <rect x="9" y="22.8" width="11" height="3.2" rx="1.6"/>
  </g>
  <text x="42" y="25" font-family="sans-serif" font-size="17" font-weight="700" fill="#6366f1">RAG</text>
  <text x="86" y="25" font-family="sans-serif" font-size="15" font-weight="500" fill="#8b8fa3">Документы</text>
</svg>"""

_LOGO_URI = "data:image/svg+xml;base64," + base64.b64encode(_LOGO_SVG.encode()).decode()


def render_brand() -> None:
    st.logo(_LOGO_URI, size="large")


# Статус опрашиваем не чаще раза в 15с: Streamlit переисполняет скрипт на
# каждое действие, а дёргать /health на каждый rerun незачем.
@st.cache_data(ttl=15, show_spinner=False)
def _probe() -> tuple[bool, bool]:
    """Живость сервисов обработки и поиска (по их /health)."""
    return process_client.health(), retrieval_client.health()


def _status_line(label: str, *, configured: bool, alive: bool) -> str:
    if not configured:
        return f"⚪ {label} — не подключён"
    return f"🟢 {label} — доступен" if alive else f"🔴 {label} — не отвечает"


def render_status() -> None:
    """Статус сервисов по реальному пробнику, а не по наличию ключа в конфиге."""
    process_alive, search_alive = _probe()

    st.caption(
        _status_line("Обработка", configured=bool(config.process_url), alive=process_alive)
    )
    st.caption(
        _status_line(
            "Поиск ответов",
            configured=retrieval_client.is_configured(),
            alive=search_alive,
        )
    )
    if auth.using_insecure_defaults():
        st.caption("⚠️ dev-режим: заданы значения секретов по умолчанию")


def render_help() -> None:
    with st.expander("Как это работает"):
        st.markdown(
            "1. **Загрузка** — добавьте документы, они уйдут на обработку "
            "(векторизация + граф).\n"
            "2. **Чат** — задайте вопрос: ответ соберётся по вашим документам.\n"
            "3. **Источники** — кликните файл под ответом, чтобы открыть его "
            "с подсветкой найденного фрагмента."
        )


def render_chat_history(chat_page) -> None:
    """Диалоги в сайдбаре: «Новый чат» + список прошлых. Клик по диалогу
    подгружает переписку и переводит на страницу чата с любой вкладки."""
    if st.button("✚ Новый чат", width="stretch"):
        st.session_state.messages = []
        st.session_state.chat_id = None
        st.session_state.pending = None  # ответ старого поиска — не в новый чат
        st.switch_page(chat_page)

    saved = chats.summaries()
    if not saved:
        return
    with st.expander("🗂️ История диалогов"):
        for chat in saved:
            if st.button(
                chat["title"],
                key=f"hist_{chat['id']}",
                help=f"Обновлён {chat['updated_at']}",
                width="stretch",
            ):
                st.session_state.messages = chats.get(chat["id"])
                st.session_state.chat_id = chat["id"]
                st.session_state.pending = None
                st.switch_page(chat_page)
