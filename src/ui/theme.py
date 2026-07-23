"""Небольшой косметический слой поверх нативной темы Streamlit.

Основной вид задаёт .streamlit/config.toml (цвета, радиусы, границы). Здесь —
только точечная полировка, которую тема не покрывает: отступы, аккуратные
карточки-источники, чуть более «воздушный» чат. Селекторы устойчивые
(data-testid); если Streamlit их переименует — стиль просто перестанет
применяться, ничего не сломав.
"""

import streamlit as st

_CSS = """
<style>
  /* Чуть уже колонка контента и меньше пустоты сверху — плотнее и опрятнее. */
  .stMainBlockContainer { padding-top: 2.2rem; max-width: 1400px; }

  /* Сообщения чата — мягкая карточка вместо «голого» блока. */
  [data-testid="stChatMessage"] {
    background: var(--secondary-background-color, #f5f6fb);
    border-radius: 0.9rem;
    padding: 0.4rem 0.9rem;
    margin-bottom: 0.35rem;
  }

  /* Кнопки-источники: убираем «кнопочность», делаем их похожими на строки-ссылки. */
  [data-testid="stButton"] > button p { font-weight: 500; }

  /* Заголовки чуть плотнее к тексту. */
  h1, h2, h3 { letter-spacing: -0.01em; }
</style>
"""


def inject_base_styles() -> None:
    """Вставляет косметический CSS. Вызывать один раз за прогон, после page_config."""
    st.html(_CSS)
