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

st.set_page_config(
    page_title="RAG · Спросить документы",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

import auth
from state import init_state
from ui import chat, sidebar, theme, upload

theme.inject_base_styles()

authenticator = auth.require_login()
init_state()

with st.sidebar:
    sidebar.render_brand()
    st.divider()

pages = st.navigation(
    [
        st.Page(chat.render, title="Чат", icon="💬", default=True),
        st.Page(upload.render, title="Загрузка", icon="📤"),
    ]
)

with st.sidebar:
    st.divider()
    sidebar.render_status()
    sidebar.render_help()
    st.divider()
    auth.render_logout(authenticator)

pages.run()
