"""Страница «Чат» — основной сценарий: вопрос → ответ по документам.

Диалог занимает всю ширину; документ-источник открывается по клику в
модальном окне (st.dialog), а не в постоянной колонке — так не остаётся
пустой половины экрана. Ответы хранятся в истории сессии, поэтому reruns
(клик по источнику) не дёргают LLM повторно.
"""

import streamlit as st
from loguru import logger

from services import retrieval_client
from services.retrieval_client import SearchError, SearchNotReady
from ui.preview import preview_file
from ui.sources import render_sources

_EXAMPLES = [
    "О чём эти документы?",
    "Найди упоминания сроков и дат",
    "Сделай краткое резюме по загруженным файлам",
]


@st.dialog("Просмотр документа", width="large")
def _preview_dialog(s3_key: str, documents: list) -> None:
    st.caption(s3_key.rsplit("/", 1)[-1])
    preview_file(s3_key, documents)


def _open_preview(s3_key: str, documents: list) -> None:
    """Колбэк выбора источника: открывает документ в модалке."""
    _preview_dialog(s3_key, documents)


def _wait_for_answer(prompt: str):
    """Пока сервис ищет — показываем вопрос и «печатающего» ассистента.

    Вопрос иначе появился бы только после ререна, то есть через десяток секунд
    после нажатия Enter, и казалось бы, что ввод не сработал.
    """
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        st.html('<div class="typing"><span></span><span></span><span></span></div>')
        return retrieval_client.ask(prompt)


def _handle_prompt(prompt: str) -> None:
    """Добавляет вопрос в историю, получает ответ и сохраняет его."""
    st.session_state.messages.append({"role": "user", "content": prompt})
    try:
        answer, sources = _wait_for_answer(prompt)
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
    if not retrieval_client.is_configured():
        st.info(
            "Пока не заданы `RETRIEVAL_URL` / `RETRIEVAL_API_KEY` — ответы "
            "недоступны. Документы уже можно загружать во вкладке **Загрузка**.",
            icon="ℹ️",
        )
        return

    # Пилюли вместо ряда кнопок: компактнее и это нативный виджет выбора.
    # Сбрасывать выбор не нужно: после первого вопроса welcome-экран
    # больше не рендерится, и состояние виджета умирает вместе с ним.
    example = st.pills("С чего начать:", _EXAMPLES, key="example_pick")
    if example:
        _handle_prompt(example)
        st.rerun()


def _feedback(message: dict, ns: str) -> None:
    """Оценка ответа 👍/👎. Хранится в сообщении, пишется в лог сервиса —
    по логам видно, какие вопросы получают плохие ответы."""
    score = st.feedback("thumbs", key=f"fb_{ns}")
    if score is not None and score != message.get("feedback"):
        message["feedback"] = score
        verdict = "полезен" if score else "бесполезен"
        logger.info(f"Оценка ответа: {verdict} | текст: {message['content'][:200]}")


def _render_history() -> None:
    for i, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["role"] == "assistant":
                render_sources(
                    message.get("sources", []), ns=str(i), on_select=_open_preview
                )
                _feedback(message, ns=str(i))


def render() -> None:
    title_col, clear_col = st.columns([0.75, 0.25], vertical_alignment="center")
    title_col.title("💬 Спросить документы")
    if st.session_state.messages and clear_col.button(
        "🧹 Очистить", width="stretch", help="Очистить историю диалога"
    ):
        st.session_state.messages = []
        st.rerun()

    if st.session_state.messages:
        _render_history()
    else:
        _render_welcome()

    if prompt := st.chat_input("Спросите что-нибудь о документах…"):
        _handle_prompt(prompt)
        st.rerun()
