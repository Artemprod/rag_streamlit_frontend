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
- **Колесо мыши** — масштаб, **перетаскивание** — двигать сцену и узлы.
- **Поиск** слева сужает граф до найденных сущностей и их соседей —
  так проще распутать плотный участок.
- Кнопки в правом верхнем углу: перестроить раскладку, скачать, во весь экран.
"""


def _filter(data: dict, query: str) -> tuple[list, list]:
    """Найденные по подстроке сущности + их соседи и связи между ними."""
    nodes, edges = data["nodes"], data["edges"]
    if not query:
        return nodes, edges
    needle = query.lower()
    hits = {n["id"] for n in nodes if needle in n["name"].lower()}
    keep = set(hits)
    for edge in edges:
        if edge["source"] in hits or edge["target"] in hits:
            keep.update((edge["source"], edge["target"]))
    return (
        [n for n in nodes if n["id"] in keep],
        [e for e in edges if e["source"] in keep and e["target"] in keep],
    )


@st.cache_data(ttl=120, show_spinner="Собираю граф знаний…")
def _load() -> dict:
    return retrieval_client.knowledge_graph()


@st.dialog("Просмотр документа", width="large")
def _preview_dialog(s3_key: str) -> None:
    st.caption(s3_key.rsplit("/", 1)[-1])
    preview_file(s3_key, [])


def _clicked_node_id(value) -> str | None:
    """Достаёт id узла из события компонента ({action, data:{target_id}})."""
    if isinstance(value, dict) and value.get("action") == "node_click":
        return (value.get("data") or {}).get("target_id")
    return None


def _render_node_card(node: dict) -> None:
    """Карточка выбранной сущности: откуда она извлечена, с открытием файла."""
    st.subheader(node["name"])
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


def render() -> None:
    theme.wide()  # графу нужен весь экран, а не колонка для чтения

    title_col, help_col, refresh_col = st.columns(
        [0.6, 0.2, 0.2], vertical_alignment="center"
    )
    title_col.markdown("## 🕸️ Граф знаний")
    with help_col.popover("❓ Как пользоваться", width="stretch"):
        st.markdown(_TUTORIAL)
    if refresh_col.button("🔄 Обновить", width="stretch", help="Перечитать граф"):
        _load.clear()

    try:
        data = _load()
    except SearchNotReady as error:
        st.info(str(error), icon="ℹ️")
        return
    except SearchError as error:
        st.warning(str(error), icon="⚠️")
        return

    if not data.get("nodes"):
        st.info(
            "Граф пока пуст: загрузите документы во вкладке «Загрузка» и "
            "дождитесь окончания обработки.",
            icon="🕸️",
        )
        return

    search_col, labels_col = st.columns([0.75, 0.25], vertical_alignment="bottom")
    query = search_col.text_input(
        "Поиск по сущностям",
        placeholder="например: правление — покажу её и соседей",
    )
    show_labels = labels_col.toggle(
        "Подписи связей",
        value=False,
        help="Названия отношений на линиях. На большом графе создают кашу — "
        "включайте, когда сузили граф поиском.",
    )

    nodes, edges = _filter(data, query)
    if not nodes:
        st.info(f"Сущностей по запросу «{query}» не нашлось.", icon="🔍")
        return
    shown = f"Показано сущностей: {len(nodes)}, связей: {len(edges)}"
    # Без этой оговорки обрезанный граф неотличим от полного: пользователь
    # видит связное полотно и считает, что перед ним весь граф.
    if not query and data.get("truncated"):
        shown += f" из {data['total_edges']} — граф показан не целиком"
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
        key=f"kg_{hash((query, show_labels)) & 0xFFFF}",
        events=[_CLICK],
    )

    node_id = _clicked_node_id(clicked)
    if node_id:
        node = next((n for n in data["nodes"] if n["id"] == node_id), None)
        if node:
            _render_node_card(node)
