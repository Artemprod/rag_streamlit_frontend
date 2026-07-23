"""Сайдбар: бренд (через st.logo, над меню), статус сервисов и подсказка.

Бренд рисуем нативным st.logo — он размещается над навигацией, поэтому
порядок «логотип → меню → статус» получается правильным без хаков.
Статус показываем спокойными цветными точками, без давящих баннеров.
"""

import base64

import streamlit as st

import auth
from config import config
from services import retrieval_client

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
