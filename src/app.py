"""Точка входа Streamlit-фронта RAG.

Порядок строгий: конфиг страницы → гейт аутентификации → инициализация
состояния → навигация по страницам. До успешного логина ни одна страница
не рендерится.
"""

import streamlit as st

st.set_page_config(
    page_title="RAG · Спросить документы",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

import auth
from state import init_state
from ui import chat, theme, upload

theme.inject_base_styles()

authenticator = auth.require_login()
init_state()

with st.sidebar:
    st.markdown("### 📚 RAG Документы")
    st.caption("Загрузка, поиск и просмотр документов")
    st.divider()

pages = st.navigation(
    [
        st.Page(chat.render, title="Чат", icon="💬", default=True),
        st.Page(upload.render, title="Загрузка", icon="📤"),
    ]
)

with st.sidebar:
    st.divider()
    auth.render_logout(authenticator)

pages.run()
