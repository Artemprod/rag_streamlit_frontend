import streamlit as st

import auth
import process_client
import storage
from preview import doc_metadata, icon_for, preview_file
from search import SearchNotReady, ask

st.set_page_config(page_title="Спросить документ", page_icon="🧊", layout="wide")

auth.require_login()

st.session_state.setdefault("uploader_key", 0)
st.session_state.setdefault("selected_file", None)
st.session_state.setdefault("previous_query", "")
st.session_state.setdefault("upload_futures", None)
st.session_state.setdefault("upload_meta", None)


def render_uploader() -> None:
    """Выбор файлов и постановка задачи на фоновую заливку в S3."""
    with st.expander("Загрузка документов"):
        st.caption("Добавь файлы или папку для обработки.")

        st.subheader("Файлы")
        files = st.file_uploader(
            "Загрузить файлы",
            accept_multiple_files=True,
            width="stretch",
            label_visibility="collapsed",
            key=f"file_uploader_{st.session_state.uploader_key}",
        )

        st.subheader("Папка")
        folder = st.file_uploader(
            "Загрузить папку",
            accept_multiple_files="directory",
            width="stretch",
            label_visibility="collapsed",
            key=f"folder_uploader_{st.session_state.uploader_key}",
        )

    uploaded = (files or []) + (folder or [])
    if not uploaded:
        return

    st.write(f"Выбрано: **{len(uploaded)}** файлов")
    dataset = st.text_input("Датасет", value="yello")
    domain_context = st.text_area("Контекст домена (необязательно)") or None

    if st.button("🚀 Сохранить и обработать", width="stretch"):
        st.session_state.upload_futures = storage.upload_async(uploaded)
        st.session_state.upload_meta = (dataset, domain_context)
        st.session_state.uploader_key += 1
        st.rerun()


@st.fragment(run_every="1s")
def render_upload_progress() -> None:
    """Поллит фоновую заливку; когда всё в S3 — отдаёт ключи сервису обработки.
    Перерисовывается только этот блок, остальная страница не трогается."""
    futures = st.session_state.upload_futures
    if not futures:
        return

    done = sum(future.done() for future in futures)
    st.progress(done / len(futures), text=f"В S3: {done}/{len(futures)}")

    if done < len(futures):
        return

    st.session_state.upload_futures = None
    dataset, domain_context = st.session_state.upload_meta
    st.session_state.upload_meta = None

    try:
        s3_keys = [future.result() for future in futures]
        result = process_client.process(s3_keys, dataset, domain_context)
        st.success(f"Принято в работу: {result['files']} файл(ов)")
    except Exception as error:
        st.error(f"Ошибка: {error}")


def render_found_files(documents: list) -> None:
    """Кнопки найденных файлов; выбранный уходит в предпросмотр."""
    st.header("Найденные файлы")
    found_keys = dict.fromkeys(
        key for doc in documents if (key := doc_metadata(doc).get("s3_key"))
    )
    for key in found_keys:
        if st.button(
            key.rsplit("/", 1)[-1], icon=icon_for(key), width="stretch", key=key
        ):
            st.session_state.selected_file = key


st.header("Спросить документ")

with st.sidebar:
    render_uploader()
    render_upload_progress()
    st.divider()
    auth.render_logout()

query = st.text_input("Спросить базу")
if query and query != st.session_state.previous_query:
    st.session_state.selected_file = None
    st.session_state.previous_query = query

if query:
    try:
        with st.spinner("Ищу..."):
            answer, documents = ask(query)
    except SearchNotReady as error:
        st.info(str(error))
        st.stop()

    st.subheader("Ответ")
    st.text(answer)
    st.divider()

    with st.sidebar:
        render_found_files(documents)

    st.header("Просмотр")
    if st.session_state.selected_file:
        preview_file(st.session_state.selected_file, documents)
    else:
        st.info("Выбери файл слева.")