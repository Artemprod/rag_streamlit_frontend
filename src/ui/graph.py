"""Страница «Граф знаний»: что извлечено из документов и как связано.

Рисуем через st-link-analysis (Cytoscape.js): зум/перетаскивание/фулскрин из
коробки, весь JS в бандле компонента — без CDN. Клик по сущности возвращается
в Python, и под графом показываются документы, из которых она извлечена.
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
- **Клик по кружку** — внизу появится карточка: в каких документах сущность
  упоминается, файл открывается по клику.
- **«Раскрыть связи»** в карточке — уходит в базу за всеми связями этой
  сущности и показывает только её окрестность. Так граф обходят шаг за шагом:
  сосед → его сосед → дальше. Вернуться назад — кнопкой над графом.
- **Колесо мыши** — масштаб, **перетаскивание** — двигать сцену и узлы.
- **Поиск** слева идёт в базу и приносит найденные сущности вместе с
  соседями. Сразу на экране лежит обзор графа, а не весь он целиком —
  поэтому нужную сущность ищите поиском: её связи придут, даже если в
  обзор они не попали.
- **Типы связей** — фильтр по уже показанному графу: разгружает картинку,
  в базу не ходит.
- Кнопки в правом верхнем углу: перестроить раскладку, скачать, во весь экран.
"""


@st.cache_data(ttl=120, show_spinner="Собираю граф знаний…")
def _load(query: str, node_id: str | None) -> dict:
    """Обзор графа (оба пустые), результат поиска или окрестность узла.

    И поиск, и раскрытие узла ушли на сервер: фильтровать загруженную выборку
    на фронте значило искать только среди тех связей, что уже приехали, — до
    остальных было не добраться. Кэш на оба ключа, чтобы шаг назад по цепочке
    раскрытий был мгновенным и не бил по Neo4j.
    """
    return retrieval_client.knowledge_graph(query or None, node_id)


@st.dialog("Просмотр документа", width="large")
def _preview_dialog(s3_key: str) -> None:
    st.caption(s3_key.rsplit("/", 1)[-1])
    preview_file(s3_key, [])


def _clicked_node_id(value) -> str | None:
    """Достаёт id узла из события компонента ({action, data:{target_id}})."""
    if isinstance(value, dict) and value.get("action") == "node_click":
        return (value.get("data") or {}).get("target_id")
    return None


def _focus(node: dict) -> None:
    """Переводит граф в режим окрестности узла (обработчик кнопки «Раскрыть»).

    Через on_click, а не по возврату из st.button: иначе Streamlit сначала
    дорисовал бы страницу со старой выборкой и только потом перезапустил её.
    """
    st.session_state["kg_focus"] = {"id": node["id"], "name": node["name"]}


def _render_node_card(node: dict, degree: int) -> None:
    """Карточка выбранной сущности: связи, откуда извлечена, открытие файла."""
    st.subheader(node["name"])
    kind = "категория" if node.get("type") == "EntityType" else "сущность"
    st.caption(f"{kind} · связей на графе: {degree}")

    # Раскрытие — единственный способ увидеть связи, не попавшие в выборку.
    # На уже раскрытой сущности кнопку не показываем: она ничего не изменит.
    if (st.session_state.get("kg_focus") or {}).get("id") != node["id"]:
        st.button(
            "🔎 Раскрыть связи этой сущности",
            key=f"gexp_{node['id']}",
            on_click=_focus,
            args=(node,),
            type="primary",
        )

    docs = node.get("docs") or []
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


def _controls() -> tuple[str, bool]:
    """Шапка страницы и запрос. Возвращает (поисковая строка, подписи связей).

    Поиск спрашиваем ДО загрузки: он уходит в запрос к сервису, а не фильтрует
    пришедшее.
    """
    title_col, help_col, refresh_col = st.columns(
        [0.6, 0.2, 0.2], vertical_alignment="center"
    )
    title_col.markdown("## 🕸️ Граф знаний")
    with help_col.popover("❓ Как пользоваться", width="stretch"):
        st.markdown(_TUTORIAL)
    if refresh_col.button("🔄 Обновить", width="stretch", help="Перечитать граф"):
        _load.clear()

    search_col, labels_col = st.columns([0.75, 0.25], vertical_alignment="bottom")
    query = search_col.text_input(
        "Поиск по сущностям",
        placeholder="например: правление — найду её в базе и покажу с соседями",
        help="Ищет по всему графу, а не по видимой части: связи сущности "
        "придут, даже если в обзор они не попали.",
    ).strip()
    show_labels = labels_col.toggle(
        "Подписи связей",
        value=False,
        help="Названия отношений на линиях. На большом графе создают кашу — "
        "включайте, когда сузили граф поиском.",
    )

    # Новый поиск отменяет раскрытие: иначе пользователь ищет одно, а на
    # экране остаётся окрестность узла, найденного до этого.
    if st.session_state.get("kg_query") != query:
        st.session_state["kg_query"] = query
        st.session_state.pop("kg_focus", None)
    return query, show_labels


def _render_focus_bar(focus: dict) -> None:
    """Где мы находимся при раскрытии узла и как вернуться к прежней выдаче."""
    back_col, note_col = st.columns([0.25, 0.75], vertical_alignment="center")
    if back_col.button("← Вернуться", width="stretch"):
        st.session_state.pop("kg_focus", None)
        st.rerun()
    note_col.caption(
        f"Показана окрестность сущности «{focus['name']}» — все её связи из базы."
    )


def _render_empty(focus: dict | None, query: str) -> None:
    if focus:
        st.info(
            f"У сущности «{focus['name']}» нет связей с другими сущностями.", icon="🔍"
        )
    elif query:
        st.info(f"Сущностей по запросу «{query}» не нашлось.", icon="🔍")
    else:
        st.info(
            "Граф пока пуст: загрузите документы во вкладке «Загрузка» и "
            "дождитесь окончания обработки.",
            icon="🕸️",
        )


def _relation_filter(nodes: list[dict], edges: list[dict]) -> tuple[list, list, list]:
    """Отбор по типам связей — по уже приехавшей выборке, без похода в базу.

    Это способ разгрузить картинку, а не сузить запрос. Узлы, оставшиеся без
    связей, убираем: висящие в пустоте кружки картину только засоряют.
    """
    relations = sorted({e["label"] for e in edges})
    if len(relations) <= 1:  # выбирать не из чего — фильтр только мешал бы
        return nodes, edges, []

    picked = st.multiselect(
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


def render() -> None:
    theme.wide()  # графу нужен весь экран, а не колонка для чтения

    query, show_labels = _controls()
    focus = st.session_state.get("kg_focus")
    if focus:
        _render_focus_bar(focus)

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
        _render_empty(focus, query)
        return

    nodes, edges, picked = _relation_filter(nodes, edges)
    if not nodes:
        st.info("По выбранным типам связей ничего не осталось.", icon="🔍")
        return

    shown = f"Показано сущностей: {len(nodes)}, связей: {len(edges)}"
    # Без этой оговорки обрезанная выдача неотличима от полной: пользователь
    # видит связное полотно и считает, что перед ним всё, что нашлось.
    if picked:
        shown += f" — отфильтровано по типам из {len(data['edges'])}"
    elif data.get("truncated"):
        tail = "у сущности" if focus else "по запросу нашлось" if query else "в графе"
        shown += f" — {tail} {data['total_edges']}, показаны не все"
    elif not query and not focus:
        shown += " — это весь граф"
    st.caption(shown)

    elements = {
        "nodes": [
            # docs в data не кладём: встроенная инфопанель компонента показала
            # бы их сырым JSON. Карточку с кнопками рисуем сами по клику.
            {"data": {"id": n["id"], "label": n["type"], "name": n["name"]}}
            for n in nodes
        ],
        "edges": [{"data": e} for e in edges],
    }
    clicked = st_link_analysis(
        elements,
        layout=_LAYOUT,
        node_styles=_NODE_STYLES,
        edge_styles=[EdgeStyle("*", caption="label" if show_labels else None, directed=True)],
        height=640,
        # Ключ зависит от фильтров: смена выборки перемонтирует компонент
        # и заново раскладывает граф, а не оставляет старую сцену.
        key=f"kg_{hash((query, focus and focus['id'], show_labels, tuple(picked))) & 0xFFFF}",
        events=[_CLICK],
    )

    node_id = _clicked_node_id(clicked)
    if node_id:
        node = next((n for n in nodes if n["id"] == node_id), None)
        if node:
            degree = sum(node_id in (e["source"], e["target"]) for e in edges)
            _render_node_card(node, degree)
