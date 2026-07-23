"""Аутентификация на готовом компоненте streamlit-authenticator.

Один админ-аккаунт из окружения (логин/имя/пароль). Компонент сам:
  • рисует форму входа,
  • хранит сессию в подписанной cookie (переживает refresh страницы),
  • даёт виджет логаута.

Экземпляр Authenticate создаём на каждый прогон скрипта (так задуман его
менеджер cookie — по одному на сессию). Дорого только bcrypt-хэширование
пароля, поэтому хэш считаем один раз и кэшируем ресурсом.
"""

import streamlit as st
import streamlit_authenticator as stauth

from config import INSECURE_COOKIE_KEY, config


@st.cache_resource
def _password_hash() -> str:
    """bcrypt-хэш админ-пароля. Считается один раз на процесс."""
    return stauth.Hasher.hash(config.admin_password)


def _build_authenticator() -> stauth.Authenticate:
    credentials = {
        "usernames": {
            config.admin_username: {
                "name": config.admin_name,
                "password": _password_hash(),
                "email": f"{config.admin_username}@local",
            }
        }
    }
    # auto_hash=False — пароль уже захэширован, повторно не трогаем.
    return stauth.Authenticate(
        credentials,
        config.auth_cookie_name,
        config.auth_cookie_key,
        config.auth_cookie_expiry_days,
        auto_hash=False,
    )


# Значения-заглушки из Config: если оставить в проде — подпись cookie и вход
# становятся предсказуемыми. Предупреждаем прямо на экране входа.
_INSECURE_DEFAULTS = {"change-me-in-prod", "change-me", INSECURE_COOKIE_KEY}


def require_login() -> stauth.Authenticate:
    """Гейт на входе: без успешного логина скрипт дальше не идёт.

    Возвращает authenticator, чтобы страницы могли отрисовать логаут в сайдбаре.
    """
    if (
        config.auth_cookie_key in _INSECURE_DEFAULTS
        or config.admin_password in _INSECURE_DEFAULTS
    ):
        st.warning(
            "⚠️ Используются значения по умолчанию для пароля/секрета cookie. "
            "Задайте ADMIN_PASSWORD и AUTH_COOKIE_KEY в окружении перед продом."
        )

    authenticator = _build_authenticator()
    authenticator.login(
        location="main",
        fields={
            "Form name": "Вход",
            "Username": "Логин",
            "Password": "Пароль",
            "Login": "Войти",
        },
    )

    status = st.session_state.get("authentication_status")
    if status is False:
        st.error("Неверный логин или пароль")
        st.stop()
    if status is None:
        st.info("Введите логин и пароль для доступа к приложению")
        st.stop()

    return authenticator


def render_logout(authenticator: stauth.Authenticate) -> None:
    name = st.session_state.get("name") or config.admin_name
    st.caption(f"👤 {name}")
    authenticator.logout("Выйти", location="sidebar", use_container_width=True)
