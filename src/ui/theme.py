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
  /* Комфортная ширина чтения и центрирование: на широких мониторах контент
     не растягивается в разреженную полосу. Широкие превью (PDF/таблицы)
     живут в модалке, поэтому телу страницы широкая ширина не нужна. */
  [data-testid="stMainBlockContainer"] {
    padding-top: 2rem;
    max-width: 1040px;
    margin: 0 auto;
    overflow-x: hidden;               /* страница не едет вбок */
  }

  /* Медиа никогда не выходят за ширину контейнера. */
  [data-testid="stMainBlockContainer"] img,
  [data-testid="stMainBlockContainer"] iframe { max-width: 100% !important; }

  /* Сообщения чата — мягкая карточка вместо «голого» блока, чуть больше воздуха. */
  [data-testid="stChatMessage"] {
    background: var(--secondary-background-color, #f5f6fb);
    border-radius: 0.9rem;
    padding: 0.5rem 1rem;
    margin-bottom: 0.6rem;
  }

  /* Источники под ответом — «строки-файлы»: текст слева, мягкий hover. */
  [data-testid="stChatMessage"] [data-testid="stButton"] > button {
    justify-content: flex-start;
    text-align: left;
    font-weight: 500;
  }
  [data-testid="stChatMessage"] [data-testid="stButton"] > button:hover {
    background: rgba(99, 102, 241, 0.10);
    border-color: #6366f1;
  }

  [data-testid="stButton"] > button p { font-weight: 500; }
  h1, h2, h3 { letter-spacing: -0.01em; }

  /* ── Адаптивность: планшеты и телефоны ──────────────────────────────
     На узких экранах любые колонки (чат/просмотр, dataset/контекст,
     заголовок+кнопка) складываются в один столбец на всю ширину — ничего
     не наезжает и не сжимается в нечитаемую полоску. */
  @media (max-width: 992px) {
    [data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; }
    [data-testid="stHorizontalBlock"] > [data-testid="stColumn"],
    [data-testid="stHorizontalBlock"] > div {
      flex: 0 0 100% !important;
      max-width: 100% !important;
      min-width: 0 !important;
    }
    [data-testid="stMainBlockContainer"] {
      padding-left: 0.9rem !important;
      padding-right: 0.9rem !important;
    }
  }
</style>
"""


def inject_base_styles() -> None:
    """Вставляет косметический CSS. Вызывать один раз за прогон, после page_config."""
    st.html(_CSS)
