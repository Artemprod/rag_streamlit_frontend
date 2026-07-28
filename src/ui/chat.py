"""Страница «Чат» — основной сценарий: вопрос → ответ по документам.

Диалог занимает всю ширину; документ-источник открывается по клику в
модальном окне (st.dialog), а не в постоянной колонке — так не остаётся
пустой половины экрана. Ответы хранятся в истории сессии, поэтому reruns
(клик по источнику) не дёргают LLM повторно.
"""

import random
from html import escape

import streamlit as st
from loguru import logger

from services import chats, retrieval_client
from services.retrieval_client import SearchError, SearchNotReady
from ui import theme
from ui.preview import preview_file
from ui.sources import render_sources

_EXAMPLES = [
    "О чём эти документы?",
    "Найди упоминания сроков и дат",
    "Сделай краткое резюме по загруженным файлам",
]

# Режимы ответа: label переключателя → (mode API, подсказка в поле ввода,
# цвет бейджа, описание для пользователя). Спор по регламенту и сверка
# противоречий — сценарии комплаенса/безопасности, обычный режим — вопросы.
_MODES = {
    "💬 Вопрос": (
        "default",
        "Спросите что-нибудь о документах…",
        "violet",
        "обычный ответ по документам с источниками",
    ),
    "🛡️ По регламенту": (
        "compliance",
        "Опишите спорную ситуацию — отвечу вердиктом с цитатами пунктов…",
        "blue",
        "для спора «можно/нельзя»: вердикт + дословные цитаты пунктов",
    ),
    "⚖️ Противоречия": (
        "contradictions",
        "Назовите тему или процесс — сверю, не расходятся ли документы…",
        "orange",
        "назовите тему — сверю документы между собой на расхождения",
    ),
}
_DEFAULT_MODE_LABEL = next(iter(_MODES))


def _current_mode_label() -> str:
    label = st.session_state.get("chat_mode") or _DEFAULT_MODE_LABEL
    return label if label in _MODES else _DEFAULT_MODE_LABEL


# Фразы ожидания «как в мессенджере с характером». Каждый запрос показывает
# свои четыре — повторы редки, а CSS листает их по кругу без JS.
_SEARCH_PHRASES = [
    "Листаю регламенты…",
    "Сдуваю пыль с папки №7…",
    "Спрашиваю у архивариуса…",
    "Сверяю пункты и подпункты…",
    "Иду вдоль стеллажа Б…",
    "Перечитываю мелкий шрифт…",
    "Кто-то опять не вернул документ на место…",
    "Проверяю примечания под звёздочкой…",
    "Согласовываю с воображаемым юристом…",
    "Перебираю подшивку за прошлый год…",
    "Заглядываю в приложение к приказу…",
    "Расставляю закладки…",
    "Пролистываю оглавление…",
    "Разбираю почерк на полях…",
    "Уточняю формулировки…",
    "Ищу нужный абзац…",
]


@st.dialog("Просмотр документа", width="large")
def _preview_dialog(s3_key: str, documents: list) -> None:
    st.caption(s3_key.rsplit("/", 1)[-1])
    preview_file(s3_key, documents)


def _open_preview(s3_key: str, documents: list) -> None:
    """Колбэк выбора источника: открывает документ в модалке."""
    _preview_dialog(s3_key, documents)


def _wait_for_answer(prompt: str, mode: str):
    """Пока сервис ищет — вопрос уже на экране, ассистент «печатает».

    Под точками крутятся фразы (стилизованный CSS-цикл): видно, что процесс
    идёт, и ожидание переносится веселее.
    """
    phrases = "".join(
        f"<span>{escape(text)}</span>" for text in random.sample(_SEARCH_PHRASES, 4)
    )
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        st.html(
            '<div class="typing"><span></span><span></span><span></span></div>'
            f'<div class="phrases">{phrases}</div>'
        )
        return retrieval_client.ask(prompt, mode=mode)


def _handle_prompt(prompt: str) -> None:
    """Добавляет вопрос в историю, получает ответ, автосохраняет диалог."""
    label = _current_mode_label()
    mode = _MODES[label][0]
    st.session_state.messages.append({"role": "user", "content": prompt})
    try:
        answer, sources = _wait_for_answer(prompt, mode)
        st.session_state.messages.append(
            {"role": "assistant", "content": answer, "sources": sources, "mode": label}
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
    st.session_state.chat_id = chats.save(
        st.session_state.chat_id, st.session_state.messages
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
    # Ключи виджетов включают id диалога: иначе оценка «fb_0» из одного
    # диалога проросла бы в первое сообщение другого после переключения.
    chat_ns = st.session_state.chat_id or "new"
    for i, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            # Ответы спец-режимов помечены бейджем: видно, чем этот ответ
            # отличается от соседних и в каком режиме переспрашивать.
            label = message.get("mode")
            if label in _MODES and label != _DEFAULT_MODE_LABEL:
                st.markdown(f":{_MODES[label][2]}-badge[{label}]")
            st.markdown(message["content"])
            if message["role"] == "assistant":
                render_sources(
                    message.get("sources", []),
                    ns=f"{chat_ns}_{i}",
                    on_select=_open_preview,
                )
                _feedback(message, ns=f"{chat_ns}_{i}")


def render() -> None:
    theme.wide("1400px")  # диалогу тесно в колонке для чтения форм
    # История и «Новый чат» живут в сайдбаре (привычно по ChatGPT);
    # заголовок — тише (##), чтобы контент начинался выше.
    st.markdown("## 💬 Спросить документы")

    if st.session_state.messages:
        _render_history()
    else:
        _render_welcome()

    # Переключатель режима действует на следующий вопрос; описание выбранного
    # режима — цветной строкой, тем же цветом помечаются его ответы в истории.
    st.pills(
        "Режим ответа",
        list(_MODES),
        default=_DEFAULT_MODE_LABEL,
        key="chat_mode",
        label_visibility="collapsed",
        help="Режимы меняют форму ответа: обычный, вердикт по регламенту, "
        "сверка документов на противоречия",
    )
    label = _current_mode_label()
    _, placeholder, color, description = _MODES[label]
    st.markdown(f":{color}-background[{label} — {description}]")
    if prompt := st.chat_input(placeholder):
        _handle_prompt(prompt)
        st.rerun()
