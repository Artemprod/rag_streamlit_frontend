"""Страница «Граф знаний»: что извлечено из документов и как связано.

Рисуем через st-link-analysis (Cytoscape.js): зум/перетаскивание/фулскрин из
коробки, весь JS в бандле компонента — без CDN. Клик по сущности возвращается
в Python, и под графом показываются документы, из которых она извлечена.
"""

import streamlit as st
from st_link_analysis import EdgeStyle, Event, NodeStyle, st_link_analysis

from services import retrieval_client
from services.retrieval_client import SearchError, SearchNotReady
from ui.preview import icon_for, preview_file

# Группы узлов: конкретные сущности и их категории (is_a). Цвета согласованы
# с темой (индиго/фиолетовый бренда + нейтральный для категорий).
_NODE_STYLES = [
    NodeStyle("Entity", "#6366f1", "name", "description"),
    NodeStyle("EntityType", "#f59e0b", "name", "folder"),
]
_EDGE_STYLES = [EdgeStyle("*", labeled=True, directed=True)]

_CLICK = Event("node_click", "click tap", "node")


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
    title_col, refresh_col = st.columns([0.78, 0.22], vertical_alignment="center")
    title_col.title("🕸️ Граф знаний")
    if refresh_col.button("🔄 Обновить", width="stretch", help="Перечитать граф"):
        _load.clear()

    st.caption(
        "Сущности, которые система извлекла из ваших документов, и связи между "
        "ними. Кликните по сущности — внизу появятся документы, где она "
        "упоминается."
    )

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

    elements = {
        "nodes": [
            # docs в data не кладём: встроенная инфопанель компонента показала
            # бы их сырым JSON. Карточку с кнопками рисуем сами по клику.
            {"data": {"id": n["id"], "label": n["type"], "name": n["name"]}}
            for n in data["nodes"]
        ],
        "edges": [{"data": e} for e in data["edges"]],
    }
    clicked = st_link_analysis(
        elements,
        layout="cose",
        node_styles=_NODE_STYLES,
        edge_styles=_EDGE_STYLES,
        height=560,
        key="knowledge_graph",
        events=[_CLICK],
    )

    node_id = _clicked_node_id(clicked)
    if node_id:
        node = next((n for n in data["nodes"] if n["id"] == node_id), None)
        if node:
            _render_node_card(node)
