"""Страница «Граф знаний»: что извлечено из документов и как связано.

Рисуем через st-link-analysis (Cytoscape.js): зум/перетаскивание/фулскрин из
коробки, весь JS в бандле компонента — без CDN. Клик по сущности возвращается
в Python, и в панели справа показываются её документы и кнопка раскрытия.

Граф исследуют шагами: обзор → поиск → клик → раскрытие связей → снова клик.
Пройденный путь лежит в session_state (kg_trail), поэтому назад можно вернуться
на любой шаг, а не только в самое начало.
"""

from collections import Counter

import streamlit as st
from st_link_analysis import EdgeStyle, Event, NodeStyle, st_link_analysis

from services import retrieval_client
from services.retrieval_client import SearchError, SearchNotReady
from ui import theme
from ui.preview import icon_for, preview_file

# Группы узлов: конкретные сущности и их категории (is_a). Цвета согласованы
# с темой (индиго/фиолетовый бренда + янтарный для категорий).
_NODE_STYLES = [
    NodeStyle("Entity", "#6366f1", "name", "description"),
    NodeStyle("EntityType", "#f59e0b", "name", "folder"),
]

_CLICK = Event("node_click", "click tap", "node")

# fcose распутывает клубок заметно лучше дефолтного cose; репульсия выше
# дефолта — узлам с длинными русскими подписями нужно больше воздуха.
_LAYOUT = {
    "name": "fcose",
    "animate": "end",
    "fit": True,
    "padding": 30,
    "nodeRepulsion": 6000,
    "nodeDimensionsIncludeLabels": True,
}

_TUTORIAL = """
**Как пользоваться графом**

- **Кружки** — сущности из ваших документов (отделы, комитеты, процессы),
  **янтарные** — их категории.
- **Клик по кружку** — справа появится карточка: в каких документах сущность
  упоминается, файл открывается по клику.
- **«Раскрыть связи»** в карточке — уходит в базу за всеми связями этой
  сущности и оставляет на экране только её окрестность. Так граф обходят шаг
  за шагом: сосед → его сосед → дальше. Путь виден над графом, вернуться
  можно на любой шаг.
- **Колесо мыши** — масштаб, **перетаскивание** — двигать сцену и узлы.
- **Поиск** идёт в базу и приносит найденные сущности вместе с соседями.
  Сразу на экране лежит обзор графа, а не весь он целиком — поэтому нужную
  сущность ищите поиском: её связи придут, даже если в обзор они не попали.
- **Типы связей** — фильтр по уже показанному графу: разгружает картинку,
  в базу не ходит.
- Кнопки в правом верхнем углу графа: перестроить раскладку, скачать,
  во весь экран.
"""

# Сколько шагов пути показывать целиком, прежде чем свернуть середину в «…».
_TRAIL_VISIBLE = 4

# Связей в одной порции. Ограничение не про базу, а про браузер: граф рисует
# Cytoscape на клиенте, и уже тысячи рёбер заметно подтормаживают вкладку.
# Остальные связи доступны следующей порцией, а не более тяжёлой картинкой.
_PAGE_SIZE = 500

_PANEL_HINT = (
    "Кликните по кружку на графе — здесь появятся документы, из которых "
    "сущность извлечена, и кнопка раскрытия её связей."
)


# Потолок записей у кэшей: без него каждая порция, раскрытие и поиск оседают
# в памяти процесса до истечения ttl, а одна выдача — это сотни узлов и рёбер.
_CACHE_ENTRIES = 32


@st.cache_data(ttl=120, max_entries=_CACHE_ENTRIES, show_spinner="Собираю граф знаний…")
def _load(query: str, node_id: str | None, page: int, chunks: tuple[str, ...]) -> dict:
    """Обзор графа (оба пустые), результат поиска или окрестность узла.

    И поиск, и раскрытие узла ушли на сервер: фильтровать загруженную выборку
    на фронте значило искать только среди тех связей, что уже приехали, — до
    остальных было не добраться. Кэш на все ключи, чтобы шаг назад по цепочке
    раскрытий и возврат к прошлой порции были мгновенными и не били по Neo4j.
    """
    return retrieval_client.knowledge_graph(
        query or None,
        node_id,
        offset=page * _PAGE_SIZE,
        limit=_PAGE_SIZE,
        chunk_ids=list(chunks),
    )


@st.cache_data(ttl=300, max_entries=_CACHE_ENTRIES, show_spinner=False)
def _load_docs(node_ids: tuple[str, ...]) -> list[dict]:
    """Документы сущностей — по действию пользователя, а не вместе с графом.

    Кортеж, а не список: ключ кэша должен быть хешируемым. Спиннер выключен
    намеренно — запрос точечный и быстрый, а мигающая плашка на каждый клик
    по узлу раздражает сильнее, чем помогает.
    """
    return retrieval_client.graph_node_documents(list(node_ids))


@st.dialog("Просмотр документа", width="large")
def _preview_dialog(s3_key: str) -> None:
    st.caption(s3_key.rsplit("/", 1)[-1])
    preview_file(s3_key, [])


def _clicked_node_id(value) -> str | None:
    """Достаёт id узла из события компонента ({action, data:{target_id}})."""
    if isinstance(value, dict) and value.get("action") == "node_click":
        return (value.get("data") or {}).get("target_id")
    return None


def focus_documents(chunk_ids: list[str], label: str) -> None:
    """Открыть граф на связях этих фрагментов документов (зовут из чата).

    Переносим id фрагментов, на которые сослался ответ, а не текст вопроса:
    сущности из них уже извлечены при обработке документов, так что переход
    стоит одного запроса в Neo4j и не требует ни поиска, ни модели.
    """
    st.session_state["kg_chunks"] = tuple(chunk_ids)
    st.session_state["kg_chunks_label"] = label
    st.session_state["kg_trail"] = []
    st.session_state["kg_page"] = 0
    # Иначе в поле поиска остался бы прошлый запрос: выборку он уже не задаёт
    # (связи документов приоритетнее), а на экране выглядит как активный фильтр.
    st.session_state["kg_search"] = ""


def _chunks() -> tuple[str, ...]:
    return st.session_state.get("kg_chunks", ())


def _drop_documents() -> None:
    st.session_state.pop("kg_chunks", None)
    st.session_state.pop("kg_chunks_label", None)
    st.session_state["kg_trail"] = []
    st.session_state["kg_page"] = 0


def _render_documents_bar() -> None:
    """Откуда пришла выборка и как вернуться ко всему графу."""
    label = st.session_state.get("kg_chunks_label", "документов из ответа")
    note_col, drop_col = st.columns([0.78, 0.22], vertical_alignment="center")
    note_col.info(f"Связи из ответа в чате · {label}", icon="💬")
    drop_col.button(
        "✕ Ко всему графу",
        key="kg_drop_docs",
        on_click=_drop_documents,
        width="stretch",
    )


def _trail() -> list[dict]:
    """Пройденный путь раскрытий: [{id, name}, ...]. Последний — текущий."""
    return st.session_state.setdefault("kg_trail", [])


def _focus(node: dict) -> None:
    """Шаг вглубь: раскрыть связи узла (обработчик кнопки в карточке).

    Через on_click, а не по возврату из st.button: иначе Streamlit сначала
    дорисовал бы страницу со старой выборкой и только потом перезапустил её.
    """
    _trail().append({"id": node["id"], "name": node["name"]})
    st.session_state["kg_page"] = 0  # у новой выборки своя нумерация порций


def _go_back(depth: int) -> None:
    """Вернуться на шаг depth пути (0 — к обзору или результатам поиска)."""
    del _trail()[depth:]
    st.session_state["kg_page"] = 0


def _render_trail(query: str) -> None:
    """Возврат из раскрытия: явная кнопка назад плюс путь текстом.

    Кнопка обычная, а не тертиарная ссылка: выход из раскрытия — главное
    действие на этом экране, и его надо видеть, а не искать. Путь показываем
    рядом текстом: после двух-трёх шагов пользователь перестаёт понимать, где
    он и как сюда попал.
    """
    trail = _trail()
    if not trail:
        return  # на обзоре и в поиске возвращаться некуда: путь ещё не начат

    if _chunks():
        root_label, root = "Связи из ответа", "связям из ответа"
    elif query:
        root_label, root = f"Поиск «{query}»", f"поиску «{query}»"
    else:
        root_label, root = "Обзор графа", "обзору графа"
    previous = f"«{trail[-2]['name']}»" if len(trail) > 1 else root
    back_col, home_col, path_col = st.columns(
        [0.24, 0.18, 0.58], vertical_alignment="center"
    )
    back_col.button(
        f"← Назад к {previous}",
        key="kg_back",
        on_click=_go_back,
        args=(len(trail) - 1,),
        width="stretch",
    )
    if len(trail) > 1:
        home_col.button(
            "⌂ К началу",
            key="kg_home",
            on_click=_go_back,
            args=(0,),
            width="stretch",
            help=f"Вернуться к {root}",
        )

    names = [step["name"] for step in trail]
    # Глубокий путь свернём: начало важнее середины — вернуться к обзору нужно
    # чаще, чем посмотреть, через что именно шли четыре шага назад.
    if len(names) > _TRAIL_VISIBLE:
        names = [names[0], "…", *names[-2:]]
    path_col.caption("Путь: " + " › ".join([root_label, *names]))


def _render_node_card(node: dict, degree: int) -> None:
    """Панель выбранной сущности: связи, источники, шаг вглубь."""
    st.markdown(f"### {node['name']}")
    st.caption(f"{_kind(node)} · связей на графе: {degree}")

    # Раскрытие — единственный способ увидеть связи, не попавшие в выборку.
    # На уже раскрытой сущности кнопку не показываем: она ничего не изменит.
    trail = _trail()
    if not trail or trail[-1]["id"] != node["id"]:
        st.button(
            "🔎 Раскрыть связи",
            key=f"gexp_{node['id']}",
            on_click=_focus,
            args=(node,),
            type="primary",
            width="stretch",
            help="Показать все связи этой сущности из базы, включая те, "
            "что не попали в текущую выдачу",
        )

    try:
        docs = _load_docs((node["id"],))
    except (SearchError, SearchNotReady):
        st.caption("Не удалось загрузить документы-источники.")
        return

    if not docs:
        st.caption("Для этой сущности не нашлось документов-источников.")
        return
    st.caption("Упоминается в документах:")
    for doc in docs:
        if not doc.get("s3_key"):
            st.markdown(f"- {doc['file_name']}")
        elif st.button(
            doc["file_name"],
            icon=icon_for(doc["s3_key"]),
            key=f"gdoc_{node['id']}_{doc['s3_key']}",
            width="stretch",
        ):
            _preview_dialog(doc["s3_key"])


def _controls() -> tuple[str, bool, object]:
    """Шапка и запрос. Возвращает (поиск, подписи связей, колонку под фильтр).

    Поиск спрашиваем ДО загрузки: он уходит в запрос к сервису, а не фильтрует
    пришедшее. Колонку под фильтр типов связей отдаём наружу пустой — её
    заполнят после загрузки, когда станет известно, какие типы вообще есть.
    Так все органы управления стоят одной строкой, а не растягивают страницу
    и не отжимают граф вниз.
    """
    title_col, help_col, refresh_col = st.columns(
        [0.6, 0.2, 0.2], vertical_alignment="center"
    )
    title_col.markdown("## 🕸️ Граф знаний")
    with help_col.popover("❓ Как пользоваться", width="stretch"):
        st.markdown(_TUTORIAL)
    if refresh_col.button("🔄 Обновить", width="stretch", help="Перечитать граф"):
        _load.clear()
        _load_docs.clear()

    search_col, filter_col, labels_col = st.columns(
        [0.5, 0.3, 0.2], vertical_alignment="bottom"
    )
    query = search_col.text_input(
        "Поиск по сущностям",
        key="kg_search",  # чтобы переход из чата мог очистить поле
        placeholder="например: правление",
        help="Ищет по всему графу, а не по видимой части: связи сущности "
        "придут, даже если в обзор они не попали.",
    ).strip()
    show_labels = labels_col.toggle(
        "Подписи связей",
        value=False,
        help="Названия отношений на линиях. На большом графе создают кашу — "
        "включайте, когда сузили граф поиском или раскрытием.",
    )

    # Новый поиск отменяет раскрытия: иначе пользователь ищет одно, а на
    # экране остаётся окрестность узла, найденного до этого.
    if st.session_state.get("kg_query") != query:
        st.session_state["kg_query"] = query
        st.session_state["kg_trail"] = []
        st.session_state["kg_page"] = 0
        if query:  # поиск по всей базе шире, чем связи пары документов
            _drop_documents()
    return query, show_labels, filter_col


def _elements(nodes: list[dict], edges: list[dict]) -> tuple[dict, dict, Counter]:
    """Данные для Cytoscape + разбор клика обратно в сущность.

    У компонента есть своя панель слева, и спрятать её нечем: она печатает все
    поля узла, кроме label. Раньше там висел UUID из базы — для пользователя
    это шум, из которого ничего не следует. Поэтому наружу отдаём короткий
    порядковый номер, а настоящий id держим в словаре на стороне Python; в
    панель вместо него кладём то, что человеку понятно: тип и число связей.

    Поля name/label оставлены латиницей намеренно: по ним компонент подбирает
    стиль узла, а его разбор data(...) кириллицу не понимает.
    """
    degrees: Counter = Counter()
    for edge in edges:
        degrees[edge["source"]] += 1
        degrees[edge["target"]] += 1

    key_of = {node["id"]: str(i + 1) for i, node in enumerate(nodes)}
    elements = {
        "nodes": [
            {
                "data": {
                    "id": key_of[node["id"]],
                    "label": node["type"],
                    "name": node["name"],
                    "Тип": _kind(node),
                    "Связей на графе": degrees[node["id"]],
                }
            }
            for node in nodes
        ],
        "edges": [
            {
                "data": {
                    "id": edge["id"],
                    "source": key_of[edge["source"]],
                    "target": key_of[edge["target"]],
                    "label": edge["label"],
                }
            }
            for edge in edges
        ],
    }
    return elements, {key_of[n["id"]]: n for n in nodes}, degrees


def _kind(node: dict) -> str:
    return "категория" if node.get("type") == "EntityType" else "сущность"


def _page() -> int:
    return st.session_state.get("kg_page", 0)


def _turn_page(step: int) -> None:
    st.session_state["kg_page"] = max(0, _page() + step)


def _render_pager(data: dict) -> None:
    """Листание порциями: следующая порция вместо всё более тяжёлой картинки.

    Показать все связи разом нельзя — граф рисует браузер, и тысячи рёбер
    вешают вкладку. Дорисовывать связи в ту же сцену — то же самое, только
    постепенно. Поэтому порция заменяется на следующую: на экране всегда
    ровно столько же элементов, а дойти можно до любой части графа.
    """
    size, total = data.get("limit") or 1, data.get("total_edges", 0)
    pages = max(1, -(-total // size))
    if pages == 1:
        return

    page = _page()
    prev_col, info_col, next_col = st.columns(
        [0.18, 0.34, 0.18], vertical_alignment="center"
    )
    prev_col.button(
        "← Предыдущие",
        key="kg_prev",
        on_click=_turn_page,
        args=(-1,),
        disabled=page == 0,
        width="stretch",
    )
    info_col.caption(f"Порция {page + 1} из {pages} · по {size} связей")
    next_col.button(
        "Ещё связи →",
        key="kg_next",
        on_click=_turn_page,
        args=(1,),
        disabled=page + 1 >= pages,
        width="stretch",
        help="Следующая порция связей. Картинка не тяжелеет: связи заменяются, "
        "а не добавляются к уже нарисованным.",
    )


def _render_empty(focus: dict | None, query: str) -> None:
    if focus:
        st.info(
            f"У сущности «{focus['name']}» нет связей с другими сущностями.", icon="🔍"
        )
    elif _chunks():
        st.info(
            "Из этих документов не извлеклось связанных сущностей — показывать "
            "на графе нечего. Вернитесь ко всему графу или поищите по названию.",
            icon="🔍",
        )
    elif query:
        st.info(
            f"Сущностей по запросу «{query}» не нашлось. Попробуйте часть слова: "
            "поиск ищет по вхождению.",
            icon="🔍",
        )
    else:
        st.info(
            "Граф пока пуст: загрузите документы во вкладке «Загрузка» и "
            "дождитесь окончания обработки.",
            icon="🕸️",
        )


def _relation_filter(container, nodes: list[dict], edges: list[dict]) -> tuple:
    """Отбор по типам связей — по уже приехавшей порции, без похода в базу.

    Список типов открытый: их извлекает модель, и на 500 связей приходится
    больше трёхсот формулировок, почти все — по одному разу. Поэтому список
    отсортирован по частоте и показывает счётчик: сверху оказывается то, на
    чём граф действительно держится (is_a, «входит_в»), а хвост из уникальных
    формулировок ищется набором текста.
    """
    counts = Counter(e["label"] for e in edges)
    if len(counts) <= 1:  # выбирать не из чего — фильтр только мешал бы
        return nodes, edges, []

    picked = container.multiselect(
        "Типы связей",
        [label for label, _ in counts.most_common()],
        format_func=lambda label: f"{label} · {counts[label]}",
        placeholder=f"все типы ({len(counts)})",
        help="Отбор идёт по показанной порции связей. Список отсортирован по "
        "частоте: сверху — типы, на которых держится граф. Начните печатать, "
        "чтобы найти нужный.",
    )
    if not picked:
        return nodes, edges, []

    kept = [e for e in edges if e["label"] in set(picked)]
    linked = {e["source"] for e in kept} | {e["target"] for e in kept}
    return [n for n in nodes if n["id"] in linked], kept, picked


def _render_relation_documents(nodes: list[dict], picked: list[str]) -> None:
    """Документы, из которых извлечены связи выбранных типов.

    Сценарий обратный обычному: не «что в этом документе», а «где вообще
    описан этот вид отношений» — так регламент находят по смыслу связи, а не
    по названию файла. Свёрнуто по умолчанию: запрос уходит только если
    пользователь раскрыл блок, и результат кэшируется.
    """
    label = picked[0] if len(picked) == 1 else f"выбранным типам ({len(picked)})"
    with st.expander(f"📄 Документы по «{label}»"):
        try:
            docs = _load_docs(tuple(sorted(n["id"] for n in nodes)))
        except (SearchError, SearchNotReady):
            st.caption("Не удалось загрузить документы.")
            return
        if not docs:
            st.caption("Документы-источники не нашлись.")
            return
        st.caption(f"Такие связи встречаются в {len(docs)} документах:")
        for doc in docs:
            if not doc.get("s3_key"):
                st.markdown(f"- {doc['file_name']}")
            elif st.button(
                doc["file_name"],
                icon=icon_for(doc["s3_key"]),
                key=f"grel_{doc['s3_key']}",
            ):
                _preview_dialog(doc["s3_key"])


def _stats(data: dict, nodes: list, edges: list, query: str, focus: dict | None) -> str:
    """Подпись под графом: сколько показано и всё ли это.

    Без оговорки про обрезку выдача неотличима от полной: пользователь видит
    связное полотно и считает, что перед ним всё, что нашлось.
    """
    shown = f"Показано сущностей: {len(nodes)}, связей: {len(edges)}"
    if len(edges) != len(data["edges"]):
        return shown + f" — отфильтровано по типам из {len(data['edges'])}"
    total = data.get("total_edges", len(edges))
    if total > len(edges):
        if focus:
            tail = "у сущности"
        elif _chunks():
            tail = "в этих документах"
        elif query:
            tail = "по запросу нашлось"
        else:
            tail = "в графе"
        return shown + f" — {tail} {total}, остальные ниже по кнопке «Ещё связи»"
    if focus:
        return shown + " — это все её связи"
    if _chunks():
        return shown + " — это все связи из этих документов"
    return shown if query else shown + " — это весь граф"


def render() -> None:
    theme.wide()  # графу нужен весь экран, а не колонка для чтения

    query, show_labels, filter_col = _controls()
    chunks = _chunks()
    if chunks:
        _render_documents_bar()
    trail = _trail()
    focus = trail[-1] if trail else None

    try:
        data = _load(query, focus["id"] if focus else None, _page(), chunks)
    except SearchNotReady as error:
        st.info(str(error), icon="ℹ️")
        return
    except SearchError as error:
        st.warning(str(error), icon="⚠️")
        return

    nodes, edges = data["nodes"], data["edges"]
    if not nodes:
        # Пустая порция дальше первой — это не «ничего не нашлось», а выход за
        # край: граф успел измениться, пока пользователь листал. Без возврата
        # к началу он застрял бы на пустом экране: пагинатор здесь не рисуется.
        if _page():
            st.session_state["kg_page"] = 0
            st.rerun()
        _render_trail(query)
        _render_empty(focus, query)
        return

    nodes, edges, picked = _relation_filter(filter_col, nodes, edges)
    _render_trail(query)
    if not nodes:
        st.info("По выбранным типам связей ничего не осталось.", icon="🔍")
        return
    st.caption(_stats(data, nodes, edges, query, focus))
    if picked:
        _render_relation_documents(nodes, picked)

    graph_col, panel_col = st.columns([0.68, 0.32], gap="medium")
    with graph_col:
        elements, by_key, degrees = _elements(nodes, edges)
        clicked = st_link_analysis(
            elements,
            layout=_LAYOUT,
            node_styles=_NODE_STYLES,
            edge_styles=[
                EdgeStyle("*", caption="label" if show_labels else None, directed=True)
            ],
            height=640,
            # Ключ зависит от выборки: её смена перемонтирует компонент и
            # заново раскладывает граф, а не оставляет старую сцену.
            key=f"kg_{hash((query, focus and focus['id'], _page(), show_labels, tuple(picked))) & 0xFFFF}",
            events=[_CLICK],
        )
        _render_pager(data)

    # Панель всегда на экране рядом с графом: карточка под графом требовала
    # прокрутки, и клик по узлу выглядел так, будто ничего не произошло.
    with panel_col, st.container(border=True, height=700):
        # После раскрытия показываем ту самую сущность, которую раскрыли:
        # она и есть центр выборки, и пустая панель сразу после клика
        # выглядела бы как потеря контекста.
        clicked_key = _clicked_node_id(clicked)
        node = by_key.get(clicked_key) if clicked_key else None
        if node is None and focus:
            node = next((n for n in nodes if n["id"] == focus["id"]), None)
        if node is None:
            st.caption(_PANEL_HINT)
        else:
            _render_node_card(node, degrees[node["id"]])
