"""Страница «Загрузка» — заливка документов и постановка на обработку.

Поток: выбор файлов → фоновая заливка в S3 (прогресс в реальном времени) →
отдача ключей сервису обработки → запись в историю задач.

Оговорка про прогресс: сервис обработки принимает работу асинхронно и не
отдаёт статус выполнения, поэтому в реальном времени мы честно показываем
только стадию заливки в S3; дальнейшая обработка отмечается как «принята».
"""

from datetime import datetime

import streamlit as st

from services import process_client
from services import s3 as s3_service
from services.process_client import ProcessError

_STAGES = {
    "uploading": ("⏳", "Загрузка в S3"),
    "queued": ("📨", "Отправлено в обработку"),
    "failed": ("❌", "Ошибка"),
}

# Сколько имён файлов показывать в карточке задачи, прежде чем свернуть в «…и ещё N».
_MAX_NAMES_SHOWN = 20


def _record_job(
    *, dataset: str, file_names: list[str], status: str, error: str | None = None
) -> None:
    st.session_state.jobs.insert(
        0,
        {
            "created_at": datetime.now().strftime("%H:%M:%S"),
            "dataset": dataset,
            "file_names": file_names,
            "files": len(file_names),
            "status": status,
            "error": error,
        },
    )


def _render_uploader() -> None:
    st.subheader("Выбор документов")
    files = st.file_uploader(
        "Файлы",
        accept_multiple_files=True,
        width="stretch",
        key=f"file_uploader_{st.session_state.uploader_key}",
    )
    folder = st.file_uploader(
        "Папка",
        accept_multiple_files="directory",
        width="stretch",
        key=f"folder_uploader_{st.session_state.uploader_key}",
    )

    uploaded = (files or []) + (folder or [])
    if not uploaded:
        return

    st.info(f"Выбрано файлов: **{len(uploaded)}**")

    col_ds, col_ctx = st.columns(2)
    dataset = col_ds.text_input(
        "Датасет", value="yello", help="Логическая группа документов"
    )
    domain_context = (
        col_ctx.text_area(
            "Контекст домена (необязательно)",
            help="Подсказка для перевода/извлечения сущностей",
        )
        or None
    )

    busy = st.session_state.upload_futures is not None
    if st.button(
        "🚀 Сохранить и обработать",
        width="stretch",
        type="primary",
        disabled=busy,
    ):
        st.session_state.upload_futures = s3_service.upload_async(uploaded)
        st.session_state.upload_meta = {
            "dataset": dataset,
            "domain_context": domain_context,
            "file_names": [f.name for f in uploaded],
        }
        st.session_state.uploader_key += 1
        st.rerun()


@st.fragment(run_every="1s")
def _render_progress() -> None:
    """Поллит фоновую заливку; когда всё в S3 — отдаёт ключи сервису обработки.

    Перерисовывается только этот фрагмент, остальная страница не трогается.
    """
    futures = st.session_state.upload_futures
    if not futures:
        return

    done = sum(future.done() for future in futures)
    total = len(futures)
    st.progress(done / total, text=f"Загрузка в S3: {done}/{total}")

    if done < total:
        return

    # Все объекты в S3 — снимаем задачу заливки и ставим на обработку.
    meta = st.session_state.upload_meta or {}
    st.session_state.upload_futures = None
    st.session_state.upload_meta = None

    try:
        s3_keys = [future.result() for future in futures]
        result = process_client.process(
            s3_keys, meta.get("dataset", "yello"), meta.get("domain_context")
        )
        _record_job(
            dataset=meta.get("dataset", "yello"),
            file_names=meta.get("file_names", s3_keys),
            status="queued",
        )
        st.success(f"Принято в обработку: {result.get('files', len(s3_keys))} файл(ов)")
    except ProcessError as error:
        _record_job(
            dataset=meta.get("dataset", "yello"),
            file_names=meta.get("file_names", []),
            status="failed",
            error=str(error),
        )
        st.error(f"Не удалось поставить на обработку: {error}")
    except Exception as error:
        _record_job(
            dataset=meta.get("dataset", "yello"),
            file_names=meta.get("file_names", []),
            status="failed",
            error=str(error),
        )
        st.error(f"Ошибка заливки: {error}")


def _render_history() -> None:
    st.subheader("История обработки")
    jobs = st.session_state.jobs
    if not jobs:
        st.caption("Пока ничего не загружалось.")
        return

    for job in jobs:
        icon, label = _STAGES.get(job["status"], ("•", job["status"]))
        with st.expander(
            f"{icon} {job['created_at']} — {job['files']} файл(ов) · {label}",
            expanded=False,
        ):
            st.write(f"**Датасет:** {job['dataset']}")
            st.write("**Файлы:** " + ", ".join(job["file_names"][:_MAX_NAMES_SHOWN]))
            if len(job["file_names"]) > _MAX_NAMES_SHOWN:
                st.caption(f"…и ещё {len(job['file_names']) - _MAX_NAMES_SHOWN}")
            if job.get("error"):
                st.error(job["error"])
            elif job["status"] == "queued":
                st.caption(
                    "Документы приняты сервисом обработки и обрабатываются в фоне "
                    "(векторизация + граф). Статус выполнения сервис не отдаёт."
                )


def render() -> None:
    st.title("📤 Загрузка документов")
    _render_uploader()
    _render_progress()
    st.divider()
    _render_history()
