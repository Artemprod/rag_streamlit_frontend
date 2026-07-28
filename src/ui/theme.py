"""Небольшой косметический слой поверх нативной темы Streamlit.

Основной вид задаёт .streamlit/config.toml (цвета, радиусы, границы). Здесь —
только точечная полировка, которую тема не покрывает: отступы, аккуратные
карточки-источники, чуть более «воздушный» чат.

Два правила, которые тут нарушать нельзя:

1. Никаких своих цветов фона и текста. Тема бывает светлой и тёмной, и любой
   зашитый цвет однажды окажется белым текстом на белом фоне. Подложки задаём
   полупрозрачным серым — он ложится и на светлый, и на тёмный фон.
2. Селекторы — по data-testid и через потомка (пробел), а не прямого ребёнка
   (>). Streamlit регулярно добавляет промежуточные обёртки, и правило с `>`
   молча перестаёт применяться.
"""

import streamlit as st

_CSS = """
<style>
  /* Комфортная ширина чтения и центрирование: на широких мониторах контент
     не растягивается в разреженную полосу. Широкие превью (PDF/таблицы)
     живут в модалке, поэтому телу страницы широкая ширина не нужна. */
  [data-testid="stMainBlockContainer"],
  [data-testid="stBottomBlockContainer"] {
    max-width: 1040px;
    margin: 0 auto;
  }
  [data-testid="stMainBlockContainer"] {
    padding-top: 2rem;
    overflow-x: hidden;               /* страница не едет вбок */
  }

  /* Медиа никогда не выходят за ширину контейнера. */
  [data-testid="stMainBlockContainer"] img,
  [data-testid="stMainBlockContainer"] iframe { max-width: 100% !important; }

  /* Сообщения чата — мягкая карточка. Полупрозрачный серый вместо цвета темы:
     работает и на светлом, и на тёмном фоне, цвет текста не трогаем. */
  [data-testid="stChatMessage"] {
    background: rgba(128, 128, 128, 0.10);
    border-radius: 0.9rem;
    padding: 0.5rem 1rem;
    margin-bottom: 0.6rem;
  }

  /* Источники под ответом — «строки-файлы»: имя слева, мягкий hover. */
  [data-testid="stChatMessage"] [data-testid="stButton"] button {
    justify-content: flex-start;
    text-align: left;
    font-weight: 500;
  }
  [data-testid="stChatMessage"] [data-testid="stButton"] button:hover {
    background: rgba(128, 128, 128, 0.14);
  }

  h1, h2, h3 { letter-spacing: -0.01em; }

  /* Индикатор ожидания ответа: три «печатающие» точки вместо спиннера.
     currentColor — цвет текста темы, поэтому индикатор виден и на светлой,
     и на тёмной. Разметку рисует ui/chat.py. */
  .typing { display: flex; gap: 0.35rem; padding: 0.4rem 0; }
  .typing span {
    width: 0.5rem;
    height: 0.5rem;
    border-radius: 50%;
    background: currentColor;
    animation: typing-dot 1.2s ease-in-out infinite;
  }
  .typing span:nth-child(2) { animation-delay: 0.15s; }
  .typing span:nth-child(3) { animation-delay: 0.30s; }

  @keyframes typing-dot {
    0%, 80%, 100% { transform: translateY(0);        opacity: 0.25; }
    40%           { transform: translateY(-0.28rem); opacity: 0.9;  }
  }

  /* Сменные фразы под точками: 4 span'а по очереди, цикл 11.2с. */
  .phrases { position: relative; height: 1.5em; margin-top: .35rem; opacity: .75; }
  .phrases span {
    position: absolute; left: 0; white-space: nowrap;
    opacity: 0; animation: phrase 11.2s linear infinite;
  }
  .phrases span:nth-child(2) { animation-delay: 2.8s; }
  .phrases span:nth-child(3) { animation-delay: 5.6s; }
  .phrases span:nth-child(4) { animation-delay: 8.4s; }
  @keyframes phrase {
    0% { opacity: 0; } 3% { opacity: 1; } 22% { opacity: 1; }
    25% { opacity: 0; } 100% { opacity: 0; }
  }

  /* Уважаем системную настройку «меньше движения». */
  @media (prefers-reduced-motion: reduce) {
    .typing span { animation: none; opacity: 0.5; }
    .phrases span { animation: none; }
    .phrases span:first-child { opacity: 1; }
  }

  /* ── Адаптивность: планшеты и телефоны ──────────────────────────────
     На узких экранах любые колонки (заголовок+кнопка, набор+контекст)
     складываются в один столбец на всю ширину — ничего не наезжает и не
     сжимается в нечитаемую полоску. */
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


def wide(max_width: str = "100%") -> None:
    """Растягивает контент текущей страницы шире базовых 1040px.

    CSS живёт только в прогоне вызвавшей страницы, поэтому «широкими»
    становятся именно те страницы, которые это попросили (чат, граф),
    а формы загрузки остаются в комфортной для чтения колонке.
    """
    st.html(
        "<style>[data-testid='stMainBlockContainer'],"
        "[data-testid='stBottomBlockContainer']"
        f"{{max-width:{max_width} !important}}</style>"
    )
