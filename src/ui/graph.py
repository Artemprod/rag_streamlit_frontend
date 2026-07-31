"""Страница «Граф знаний»: что извлечено из документов и как связано.

Рисуем через st-link-analysis (Cytoscape.js): зум/перетаскивание/фулскрин из
коробки, весь JS в бандле компонента — без CDN. Клик по сущности возвращается
в Python, и в панели справа показываются её документы и кнопка раскрытия.

Граф исследуют шагами: обзор → поиск → клик → раскрытие связей → снова клик.
Пройденный путь лежит в session_state (kg_trail), поэтому назад можно вернуться
на любой шаг, а не только в самое начало.
"""

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

_PANEL_HINT = (
    "Кликните по кружку на графе — здесь появятся документы, из которых "
    "сущность извлечена, и кнопка раскрытия её связей."
)


@st.cache_data(ttl=120, show_spinner="Собираю граф знаний…")
def _load(query: str, node_id: str | None) -> dict:
    """Обзор графа (оба пустые), результат поиска или окрестность узла.

    И поиск, и раскрытие узла ушли на сервер: фильтровать загруженную выборку
    на фронте значило искать только среди тех связей, что уже приехали, — до
    остальных было не добраться. Кэш на оба ключа, чтобы шаг назад по цепочке
    раскрытий был мгновенным и не бил по Neo4j.
    """
    return retrieval_client.knowledge_graph(query or None, node_id)


@st.cache_data(ttl=300, show_spinner=False)
def _load_docs(node_id: str) -> list[dict]:
    """Документы одной сущности — по клику, а не вместе с графом.

    Спиннер выключен намеренно: запрос точечный и быстрый, а мигающая плашка
    на каждый клик по узлу раздражает сильнее, чем помогает.
    """
    return retrieval_client.graph_node_documents(node_id)


@st.dialog("Просмотр документа", width="large")
def _preview_dialog(s3_key: str) -> None:
    st.caption(s3_key.rsplit("/", 1)[-1])
    preview_file(s3_key, [])


def _clicked_node_id(value) -> str | None:
    """Достаёт id узла из события компонента ({action, data:{target_id}})."""
    if isinstance(value, dict) and value.get("action") == "node_click":
        return (value.get("data") or {}).get("target_id")
    return None


def _trail() -> list[dict]:
    """Пройденный путь раскрытий: [{id, name}, ...]. Последний — текущий."""
    return st.session_state.setdefault("kg_trail", [])


def _focus(node: dict) -> None:
    """Шаг вглубь: раскрыть связи узла (обработчик кнопки в карточке).

    Через on_click, а не по возврату из st.button: иначе Streamlit сначала
    дорисовал бы страницу со старой выборкой и только потом перезапустил её.
    """
    _trail().append({"id": node["id"], "name": node["name"]})


def _go_back(depth: int) -> None:
    """Вернуться на шаг depth пути (0 — к обзору или результатам поиска)."""
    del _trail()[depth:]


def _render_trail(query: str) -> None:
    """Хлебные крошки пути раскрытий — кнопками, чтобы вернуться на любой шаг.

    Одной кнопки «назад» мало: после двух-трёх раскрытий пользователь перестаёт
    понимать, где он и как сюда попал, а возврат к началу теряет весь путь.
    """
    trail = _trail()
    if not trail:
        return  # на обзоре и в поиске крошки не нужны: путь ещё не начат

    root = f"Поиск «{query}»" if query else "Обзор графа"
    steps = [(0, root), *((i + 1, s["name"]) for i, s in enumerate(trail))]
    # Глубокий путь ужал бы кнопки в нечитаемые колонки. Начало пути важнее
    # середины: вернуться к обзору нужно чаще, чем на четыре шага назад.
    if len(steps) > _TRAIL_VISIBLE:
        steps = [steps[0], (None, "…"), *steps[-2:]]

    cols = st.columns(len(steps) + 1, vertical_alignment="center")
    for col, (depth, label) in zip(cols, steps, strict=False):
        with col:
            if depth is None:
                st.caption("…")
            elif depth == steps[-1][0]:
                st.markdown(f"**{label}**")
            else:
                st.button(
                    f"‹ {label}",
                    key=f"kgtrail_{depth}",
                    on_click=_go_back,
                    args=(depth,),
                    type="tertiary",
                )


def _render_node_card(node: dict, degree: int) -> None:
    """Панель выбранной сущности: связи, источники, шаг вглубь."""
    st.markdown(f"### {node['name']}")
    kind = "категория" if node.get("type") == "EntityType" else "сущность"
    st.caption(f"{kind} · связей на графе: {degree}")

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
        docs = _load_docs(node["id"])
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
    return query, show_labels, filter_col


def _render_empty(focus: dict | None, query: str) -> None:
    if focus:
        st.info(
            f"У сущности «{focus['name']}» нет связей с другими сущностями.", icon="🔍"
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
    """Отбор по типам связей — по уже приехавшей выборке, без похода в базу.

    Это способ разгрузить картинку, а не сузить запрос. Узлы, оставшиеся без
    связей, убираем: висящие в пустоте кружки картину только засоряют.
    """
    relations = sorted({e["label"] for e in edges})
    if len(relations) <= 1:  # выбирать не из чего — фильтр только мешал бы
        return nodes, edges, []

    picked = container.multiselect(
        "Типы связей",
        relations,
        placeholder=f"все типы ({len(relations)})",
        help="Пусто — показываются все. Отбор идёт по видимому графу, "
        "новые связи из базы не подтягивает.",
    )
    if not picked:
        return nodes, edges, []

    kept = [e for e in edges if e["label"] in set(picked)]
    linked = {e["source"] for e in kept} | {e["target"] for e in kept}
    return [n for n in nodes if n["id"] in linked], kept, picked


def _stats(data: dict, nodes: list, edges: list, query: str, focus: dict | None) -> str:
    """Подпись под графом: сколько показано и всё ли это.

    Без оговорки про обрезку выдача неотличима от полной: пользователь видит
    связное полотно и считает, что перед ним всё, что нашлось.
    """
    shown = f"Показано сущностей: {len(nodes)}, связей: {len(edges)}"
    if len(edges) != len(data["edges"]):
        return shown + f" — отфильтровано по типам из {len(data['edges'])}"
    if data.get("truncated"):
        tail = "у сущности" if focus else "по запросу нашлось" if query else "в графе"
        return shown + f" — {tail} {data['total_edges']}, показаны не все"
    if focus:
        return shown + " — это все её связи"
    return shown if query else shown + " — это весь граф"


def render() -> None:
    theme.wide()  # графу нужен весь экран, а не колонка для чтения

    query, show_labels, filter_col = _controls()
    trail = _trail()
    focus = trail[-1] if trail else None

    try:
        data = _load(query, focus["id"] if focus else None)
    except SearchNotReady as error:
        st.info(str(error), icon="ℹ️")
        return
    except SearchError as error:
        st.warning(str(error), icon="⚠️")
        return

    nodes, edges = data["nodes"], data["edges"]
    if not nodes:
        _render_trail(query)
        _render_empty(focus, query)
        return

    nodes, edges, picked = _relation_filter(filter_col, nodes, edges)
    _render_trail(query)
    if not nodes:
        st.info("По выбранным типам связей ничего не осталось.", icon="🔍")
        return
    st.caption(_stats(data, nodes, edges, query, focus))

    graph_col, panel_col = st.columns([0.72, 0.28], gap="medium")
    with graph_col:
        elements = {
            "nodes": [
                # docs в data не кладём: встроенная инфопанель компонента
                # показала бы их сырым JSON. Панель справа рисуем сами.
                {"data": {"id": n["id"], "label": n["type"], "name": n["name"]}}
                for n in nodes
            ],
            "edges": [{"data": e} for e in edges],
        }
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
            key=f"kg_{hash((query, focus and focus['id'], show_labels, tuple(picked))) & 0xFFFF}",
            events=[_CLICK],
        )

    # Панель всегда на экране рядом с графом: карточка под графом требовала
    # прокрутки, и клик по узлу выглядел так, будто ничего не произошло.
    with panel_col, st.container(border=True, height=640):
        # После раскрытия показываем ту самую сущность, которую раскрыли:
        # она и есть центр выборки, и пустая панель сразу после клика
        # выглядела бы как потеря контекста.
        node_id = _clicked_node_id(clicked) or (focus and focus["id"])
        node = next((n for n in nodes if n["id"] == node_id), None) if node_id else None
        if node is None:
            st.caption(_PANEL_HINT)
        else:
            degree = sum(node["id"] in (e["source"], e["target"]) for e in edges)
            _render_node_card(node, degree)
