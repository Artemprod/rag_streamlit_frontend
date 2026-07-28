"""Точка входа Streamlit-фронта RAG.

Порядок строгий: конфиг страницы → гейт аутентификации → инициализация
состояния → навигация по страницам. До успешного логина ни одна страница
не рендерится.
"""

import sys
from pathlib import Path

# src/ на sys.path: делает импорты (config, services, ui…) независимыми от того,
# из какой директории и чем запущено приложение. Единственная точка входа —
# этот файл: streamlit run src/app.py
sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st

from logging_setup import setup_logging

setup_logging()

st.set_page_config(
    page_title="RAG · Спросить документы",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

import auth
from state import init_state
from ui import chat, graph, sidebar, theme, upload

theme.inject_base_styles()

authenticator = auth.require_login()
init_state()

# Логотип рисуется в своём слоте над меню — вызываем до навигации.
sidebar.render_brand()

# url_path обязателен и уникален: все функции называются render(),
# иначе st.navigation вывел бы одинаковый путь и упал.
chat_page = st.Page(chat.render, title="Чат", icon="💬", url_path="chat", default=True)
pages = st.navigation(
    [
        chat_page,
        st.Page(upload.render, title="Загрузка", icon="📤", url_path="upload"),
        st.Page(graph.render, title="Граф знаний", icon="🕸️", url_path="graph"),
    ]
)

with st.sidebar:
    st.divider()
    sidebar.render_chat_history(chat_page)
    st.divider()
    sidebar.render_status()
    sidebar.render_help()
    st.divider()
    auth.render_logout(authenticator)

pages.run()
