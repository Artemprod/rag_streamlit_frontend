import secrets

import streamlit as st

from config import config


def require_login() -> None:
    """Гейт на входе: без пароля скрипт дальше не идёт."""
    if st.session_state.get("authenticated"):
        return

    st.title("Вход")
    password = st.text_input("Пароль администратора", type="password") or ""

    if st.button("Войти", width="stretch"):
        if secrets.compare_digest(password.encode(), config.admin_password.encode()):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Неверный пароль")

    st.stop()


def render_logout() -> None:
    if st.button("Выйти", width="stretch"):
        st.session_state.authenticated = False
        st.rerun()