"""Страница «Чат» — основной сценарий: вопрос → ответ по документам.

Слева диалог с историей и источниками, справа предпросмотр выбранного
документа с подсветкой найденного фрагмента. Ответы хранятся в истории
сессии, поэтому reruns (клик по источнику) не дёргают LLM повторно.
"""

import streamlit as st

from services import retrieval_client
from services.retrieval_client import SearchError, SearchNotReady
from ui.preview import preview_file
from ui.sources import render_sources

_EXAMPLES = [
    "О чём эти документы?",
    "Найди упоминания сроков и дат",
    "Сделай краткое резюме по загруженным файлам",
]


def _handle_prompt(prompt: str) -> None:
    """Добавляет вопрос в историю, получает ответ и сохраняет его."""
    st.session_state.messages.append({"role": "user", "content": prompt})
    try:
        with st.spinner("Ищу ответ по документам…"):
            answer, sources = retrieval_client.ask(prompt)
        st.session_state.messages.append(
            {"role": "assistant", "content": answer, "sources": sources}
        )
    except SearchNotReady as error:
        st.session_state.messages.append(
            {"role": "assistant", "content": f"ℹ️ {error}", "sources": []}
        )
    except SearchError as error:
        st.session_state.messages.append(
            {"role": "assistant", "content": f"⚠️ {error}", "sources": []}
        )
    except Exception as error:  # неожиданное не должно ронять всю страницу
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": f"⚠️ Непредвиденная ошибка: {error}",
                "sources": [],
            }
        )


def _render_welcome() -> None:
    """Дружелюбный пустой экран: приветствие + примеры вопросов-«чипов»."""
    st.markdown(
        "#### 👋 Привет! Спросите что угодно о ваших документах\n"
        "Я найду ответ по загруженным файлам и покажу источники — "
        "кликните любой, чтобы открыть его с подсветкой."
    )
    st.caption("С чего начать:")
    for idx, example in enumerate(_EXAMPLES):
        if st.button(f"💡 {example}", key=f"ex_{idx}", width="stretch"):
            _handle_prompt(example)
            st.rerun()


def _render_history() -> None:
    for i, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["role"] == "assistant":
                render_sources(message.get("sources", []), ns=str(i))


def _render_preview() -> None:
    selected = st.session_state.selected_file
    if not selected:
        st.info("Выберите документ-источник слева, чтобы открыть его здесь.")
        return

    header = st.container()
    with header:
        cols = st.columns([0.85, 0.15])
        cols[0].subheader(selected.rsplit("/", 1)[-1])
        if cols[1].button("✕", key="close_preview", help="Закрыть просмотр"):
            st.session_state.selected_file = None
            st.session_state.selected_sources = []
            st.rerun()

    preview_file(selected, st.session_state.selected_sources)


def render() -> None:
    title_col, clear_col = st.columns([0.8, 0.2], vertical_alignment="center")
    title_col.title("💬 Спросить документы")
    if st.session_state.messages and clear_col.button(
        "🧹 Очистить", width="stretch", help="Очистить историю диалога"
    ):
        st.session_state.messages = []
        st.session_state.selected_file = None
        st.session_state.selected_sources = []
        st.rerun()

    if not retrieval_client.is_configured():
        st.warning(
            "Сервис поиска не подключён (не заданы RETRIEVAL_URL / RETRIEVAL_API_KEY). "
            "Загрузка документов работает, ответы на вопросы — пока нет."
        )

    conversation, preview = st.columns([0.5, 0.5], gap="large")
    with conversation:
        if st.session_state.messages:
            _render_history()
        else:
            _render_welcome()

    with preview:
        _render_preview()

    # chat_input обязан быть в основной области (не в колонке) — Streamlit
    # закрепит его внизу страницы.
    if prompt := st.chat_input("Спросите что-нибудь о документах…"):
        _handle_prompt(prompt)
        st.rerun()
