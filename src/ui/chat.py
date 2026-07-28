"""Страница «Чат» — основной сценарий: вопрос → ответ по документам.

Диалог занимает всю ширину; документ-источник открывается по клику в
модальном окне (st.dialog), а не в постоянной колонке — так не остаётся
пустой половины экрана. Ответы хранятся в истории сессии, поэтому reruns
(клик по источнику) не дёргают LLM повторно.
"""

import random
from concurrent.futures import ThreadPoolExecutor
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

# Поиск ответа выполняется в фоновом потоке: прогон страницы Streamlit
# обрывается при переходе на другую вкладку, а поток и future в session_state
# живут — вернулся на «Чат», и поиск продолжается с того же места.
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ask")


def _current_mode_label() -> str:
    label = st.session_state.get("chat_mode") or _DEFAULT_MODE_LABEL
    return label if label in _MODES else _DEFAULT_MODE_LABEL


# Фразы ожидания «как в мессенджере с характером». На один запрос берём
# несколько случайных, CSS листает их по кругу без JS: при таком списке
# повтор в пределах запроса невозможен, а между запросами — редок.
_PHRASES_PER_REQUEST = 6
# Сколько секунд висит одна фраза. Произведение на _PHRASES_PER_REQUEST
# обязано совпадать с длительностью animation `phrase` в ui/theme.py.
_PHRASE_SECONDS = 2.2

_SEARCH_PHRASES = [
    "Кручу диск бронированного сейфа. 36 вправо, 12 влево...",
    "Сдуваю вековую пыль с папки «Особая важность». Апчхи! Будьте здоровы.",
    "Если за нами следят — моргните в микрообъектив, вмонтированный в вашу розетку, дважды.",
    "Только ради ваших красивых глаз лезу на эту шаткую стремянку.",
    "Тяжело вздыхаю. Иду в секретный сектор «В»...",
    "Спускаюсь на минус пятый этаж. Тут ловит только радио «Маяк».",
    "Вы там чай пьёте из подстаканника, да? А я тут сейфы ворочаю. Оставьте глоточек.",
    "Споткнулся о коробку с агентурными сводками за 1979-й. Жив, спасибо.",
    "У вас красивый почерк в анкете. Взял на карандаш.",
    "Кручу ручку передвижного стеллажа. Чувствую себя капитаном подлодки.",
    "Заодно читаю вашу школьную характеристику. Занятно...",
    "Скрепка впилась в палец! Ладно, спишем на производственную травму.",
    "Ради вас готов нарушить гостайну. Но только один раз.",
    "Кто вообще додумался ставить документы такого уровня на самую верхнюю полку?!",
    "Проверяю документ на наличие «жучков». Вроде чисто.",
    "Балансирую на одной ноге, пытаясь достать самую дальнюю папку.",
    "Ваш запрос такой изящный. Сохраню его копию в свой личный сейф.",
    "Борюсь с желанием отправить этот стеллаж в топку котельной. Но ради вас держусь.",
    "Расшифровываю текст. «Юстас — Алексу»… Нет, это не то дело.",
    "Печатаю запрос на «Ундервуде». Палец застрял между клавишами.",
    "Делаю пометку в деле: «Объект обаятелен, продолжать наблюдение».",
    "Опять залили шифровку чаем из гранёного стакана!",
    "Сверяю печати. Если тут нет гербовой — кому-то светит выговор.",
    "Если найду с первой попытки — с вас талон на спецпаёк.",
    "Стряхиваю пепел с «Беломора» прямо на гриф «Совершенно секретно».",
    "Пытаюсь разобрать почерк резолюции. Это «арестовать», «премировать» или «обнять»?",
    "Шлю вам воздушный поцелуй морзянкой: тире-точка-точка...",
    "Ищу ваш запрос, а мог бы ловить иностранных шпионов.",
    "Взбиваю пыль так, что в луче света можно снимать кино для Тарковского.",
    "Достаю дело из тайника за портретом Дзержинского.",
    "Кто додумался зашифровать этот приказ двойным шифром?! Ломаю голову.",
    "Специально ищу медленнее, чтобы подольше за вами понаблюдать... Шучу, работаю на пределе!",
    "Осторожно разлепляю слипшиеся страницы...",
    "Подмигиваю вам через глазок, замаскированный под гвоздь в стене.",
    "Спрашиваю у товарища майора. Майор спит на стопке протоколов. Справляюсь сам.",
    "Ставлю сургучную печать на допуск. Осторожно, капает!",
    "Пытаюсь развязать тесёмки на папке. Да кто это так затянул?!",
    "Перебираю перфокарты. Кто-то пролил на них советский кисель.",
    "Листаю... Листаю... О, чья-то заначка — талоны на колбасу за восемьдесят второй год!",
    "Ищу нужный абзац в море номенклатурного бреда.",
    "Так, буква «А», буква «Б»... Куда дели стеллаж с грифом «М»?!",
    "Рискую погонами, лишь бы вы скорее получили ответ.",
    "Батарейка «Крона» в фонарике садится. Нагнетаю атмосферу!",
    "Смахиваю дохлую моль с совершенно секретного акта приёмки.",
    "Вы уверены, что хотите это знать? Обратно пути уже не будет.",
    "Пересчитываю листы. Тридцать восьмая вырвана с корнем... Кто-то заметал следы. Ищу копию.",
    "Прикладываю логарифмическую линейку, чтобы не потерять строчку. Я профессионал.",
    "Слюнявлю палец... Фу, бумага на вкус как эпоха застоя.",
    "Заполняю форму 4-Б на выдачу формы 8-В. Терпите, порядок есть порядок.",
    "Аккуратно вытягиваю ваш листок пинцетом, чтобы не оставить отпечатков.",
    "Пытаюсь прочитать закрашенное чёрной тушью. Похоже на ГОСТ докторской колбасы.",
    "Даже на допросе с пристрастием я бы не выдал, как сильно хочу вам помочь.",
    "Поправляю съехавшие роговые очки. Так, что тут у нас...",
    "Если на меня сейчас упадёт этот сейф — считайте меня коммунистом.",
    "Кручу ручку арифмометра «Феликс», пытаюсь высчитать вероятность успеха.",
    "Включаю настольную лампу с зелёным абажуром. Так думать легче.",
    "Ваш запрос обрабатывает новейшая ЭВМ размером с двухкомнатную квартиру. Ждём.",
]


@st.dialog("Просмотр документа", width="large")
def _preview_dialog(s3_key: str, documents: list) -> None:
    st.caption(s3_key.rsplit("/", 1)[-1])
    preview_file(s3_key, documents)


def _open_preview(s3_key: str, documents: list) -> None:
    """Колбэк выбора источника: открывает документ в модалке."""
    _preview_dialog(s3_key, documents)


def _phrases_html() -> str:
    """Разметка сменяющихся фраз: случайные фразы со сдвигом по времени."""
    chosen = random.sample(
        _SEARCH_PHRASES, min(_PHRASES_PER_REQUEST, len(_SEARCH_PHRASES))
    )
    return "".join(
        f'<span style="animation-delay:{index * _PHRASE_SECONDS:.1f}s,0s">'
        f"{escape(text)}</span>"
        for index, text in enumerate(chosen)
    )


def _handle_prompt(prompt: str, label: str | None = None) -> None:
    """Кладёт вопрос в историю и запускает поиск в фоне (не блокируя UI).

    label задаётся явно при переспросе в другом режиме; иначе берётся
    из переключателя над полем ввода.
    """
    label = label or _current_mode_label()
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.session_state.pending = {
        "future": _EXECUTOR.submit(retrieval_client.ask, prompt, _MODES[label][0]),
        "mode": label,
        # Вопрос храним в ответе: он нужен, чтобы прогнать его же в другом
        # режиме одной кнопкой, не заставляя пользователя печатать заново.
        "question": prompt,
        # Фразы выбираются один раз на запрос: индикатор рисуется вне
        # фрагмента-опросчика, и CSS-цикл не сбрасывается каждый тик.
        "phrases_html": _phrases_html(),
    }


def _finish_pending(pending: dict) -> None:
    """Разбирает завершённый future в сообщение и автосохраняет диалог."""
    try:
        answer, sources = pending["future"].result()
        message = {
            "role": "assistant",
            "content": answer,
            "sources": sources,
            "mode": pending["mode"],
            "question": pending["question"],
        }
    except SearchNotReady as error:
        message = {"role": "assistant", "content": f"ℹ️ {error}", "sources": []}
    except SearchError as error:
        message = {"role": "assistant", "content": f"⚠️ {error}", "sources": []}
    except Exception as error:  # неожиданное не должно ронять всю страницу
        message = {
            "role": "assistant",
            "content": f"⚠️ Непредвиденная ошибка: {error}",
            "sources": [],
        }
    st.session_state.messages.append(message)
    st.session_state.chat_id = chats.save(
        st.session_state.chat_id, st.session_state.messages
    )


@st.fragment(run_every="1s")
def _poll_pending() -> None:
    """Тихо опрашивает фоновый поиск. Сам ничего не рисует: индикатор стоит
    снаружи фрагмента и не перерисовывается (анимация не дёргается), а по
    готовности ответа фрагмент просит полный ререн страницы."""
    pending = st.session_state.pending
    if pending and pending["future"].done():
        st.session_state.pending = None
        _finish_pending(pending)
        st.rerun(scope="app")


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


def _question_of(index: int, message: dict) -> str:
    """Вопрос, на который отвечает сообщение. В диалогах, сохранённых до
    появления переспроса, поля нет — берём предыдущую реплику пользователя."""
    if message.get("question"):
        return message["question"]
    previous = st.session_state.messages[index - 1] if index else None
    return previous["content"] if previous and previous["role"] == "user" else ""


def _render_rerun(message: dict, index: int, ns: str) -> None:
    """«Тот же вопрос в другом режиме» — по кнопке на каждый оставшийся режим.

    Ответ добавляется в конец той же переписки: рядом видно, что говорит
    обычный поиск, вердикт по регламенту и сверка на противоречия.
    """
    question = _question_of(index, message)
    if message.get("mode") not in _MODES or not question:
        return  # ошибки и служебные реплики переспрашивать нечем

    others = [label for label in _MODES if label != message["mode"]]
    st.caption("Тот же вопрос в другом режиме:")
    for column, label in zip(st.columns(len(others)), others, strict=True):
        if column.button(
            label,
            key=f"re_{ns}_{label}",
            width="stretch",
            disabled=bool(st.session_state.pending),
            help=_MODES[label][3],
        ):
            _handle_prompt(question, label)
            st.rerun()


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
                _render_rerun(message, i, ns=f"{chat_ns}_{i}")


def render() -> None:
    theme.wide("1400px")  # диалогу тесно в колонке для чтения форм
    # История и «Новый чат» живут в сайдбаре (привычно по ChatGPT);
    # заголовок — тише (##), чтобы контент начинался выше.
    st.markdown("## 💬 Спросить документы")

    if st.session_state.messages:
        _render_history()
    else:
        _render_welcome()

    # Идёт поиск: печатающий индикатор (вне фрагмента — анимация стабильна)
    # и фрагмент-опросчик, который дождётся ответа даже после ухода на другую
    # вкладку и возвращения.
    if st.session_state.pending:
        with st.chat_message("assistant"):
            st.html(
                '<div class="typing"><span></span><span></span><span></span></div>'
                f'<div class="phrases">{st.session_state.pending["phrases_html"]}</div>'
            )
        _poll_pending()

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
    # Пока идёт поиск, новый вопрос не принимаем — ответ пришёл бы вперемешку.
    if prompt := st.chat_input(placeholder, disabled=bool(st.session_state.pending)):
        _handle_prompt(prompt)
        st.rerun()
