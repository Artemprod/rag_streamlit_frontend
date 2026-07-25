"""Страница «Загрузка» — заливка документов и постановка на обработку.

Поток: выбор файлов → фоновая заливка в S3 (прогресс в реальном времени) →
постановка в обработку (сервис отдаёт job_id) → поллинг прогресса задачи до
терминального статуса.

Прогресс показываем честно на всех стадиях: сервис обработки отдаёт снимок
счётчиков (файлы загружены/упали, ноды переведены/записаны/попали в граф),
поэтому пользователь видит движение конвейера, а не только факт приёма.
"""

from datetime import datetime

import streamlit as st

from services import process_client
from services import s3 as s3_service
from services.process_client import ProcessError

# Отображение статусов. Ключи — статусы сервиса обработки плюс локальный
# upload_failed (до сервиса дело не дошло).
_STATUS_VIEW = {
    "queued": ("📨", "В очереди"),
    "running": ("⚙️", "Обрабатывается"),
    "completed": ("✅", "Готово"),
    "completed_with_errors": ("⚠️", "Готово, часть данных потеряна"),
    "failed": ("❌", "Ошибка обработки"),
    "upload_failed": ("❌", "Не удалось отправить"),
}

# Счётчики стадий из снимка статуса — берём подмножеством, чтобы запись задачи
# не тащила служебные поля ответа.
_COUNTERS = (
    "total_files",
    "files_loaded",
    "files_failed",
    "nodes_total",
    "nodes_translated",
    "nodes_persisted",
    "nodes_graphed",
    "nodes_failed",
)

# Сколько имён файлов показывать, прежде чем свернуть в «…и ещё N».
_MAX_NAMES_SHOWN = 20
_POLL_INTERVAL = "2s"


def _record_job(
    *,
    dataset: str,
    file_names: list[str],
    status: str,
    job_id: str | None = None,
    error: str | None = None,
) -> None:
    st.session_state.jobs.insert(
        0,
        {
            "job_id": job_id,
            "created_at": datetime.now().strftime("%H:%M:%S"),
            "dataset": dataset,
            "file_names": file_names,
            "files": len(file_names),
            "status": status,
            "progress": 0.0,
            "stats": None,
            "error": error,
        },
    )


def _render_uploader() -> None:
    # Основной сценарий — просто перетащить файлы. Папка вынесена вторично.
    files = st.file_uploader(
        "Перетащите файлы сюда или выберите",
        accept_multiple_files=True,
        width="stretch",
        key=f"file_uploader_{st.session_state.uploader_key}",
    )
    with st.expander("📁 …или загрузить папку целиком"):
        folder = st.file_uploader(
            "Папка",
            accept_multiple_files="directory",
            width="stretch",
            label_visibility="collapsed",
            key=f"folder_uploader_{st.session_state.uploader_key}",
        )

    uploaded = (files or []) + (folder or [])
    if uploaded:
        st.success(f"Выбрано файлов: **{len(uploaded)}**")

    # Настройки и кнопка видны всегда — понятно, что будет дальше. Кнопка
    # неактивна, пока не выбраны файлы или пока идёт заливка.
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
        disabled=busy or not uploaded,
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
def _render_upload_progress() -> None:
    """Поллит фоновую заливку в S3; когда всё залито — ставит задачу в обработку.

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
    dataset = meta.get("dataset", "yello")
    st.session_state.upload_futures = None
    st.session_state.upload_meta = None

    try:
        s3_keys = [future.result() for future in futures]
        result = process_client.process(s3_keys, dataset, meta.get("domain_context"))
        _record_job(
            dataset=dataset,
            file_names=meta.get("file_names", s3_keys),
            status="queued",
            job_id=result.get("job_id"),
        )
        # Полный ререн, а не только фрагмента: задача должна появиться в разделе
        # «В работе», который живёт вне этого фрагмента.
        st.rerun(scope="app")
    except ProcessError as error:
        _record_job(
            dataset=dataset,
            file_names=meta.get("file_names", []),
            status="upload_failed",
            error=str(error),
        )
        st.toast(f"Не удалось поставить на обработку: {error}", icon="❌")
    except Exception as error:
        _record_job(
            dataset=dataset,
            file_names=meta.get("file_names", []),
            status="upload_failed",
            error=str(error),
        )
        st.toast(f"Ошибка заливки: {error}", icon="❌")


def _apply_snapshot(job: dict, snapshot: dict) -> None:
    """Переносит снимок статуса сервиса в запись задачи (мутирует на месте)."""
    job["status"] = snapshot.get("status", job["status"])
    job["progress"] = snapshot.get("progress", job.get("progress") or 0.0)
    job["error"] = snapshot.get("error") or job.get("error")
    job["stats"] = {name: snapshot.get(name, 0) for name in _COUNTERS}


def _stats_line(stats: dict) -> str:
    """Одна строка про стадии конвейера: файлы, затем ноды по этапам."""
    parts = [f"файлы {stats['files_loaded']}/{stats['total_files']}"]
    if stats["nodes_total"]:
        parts += [
            f"перевод {stats['nodes_translated']}/{stats['nodes_total']}",
            f"запись {stats['nodes_persisted']}/{stats['nodes_total']}",
            f"граф {stats['nodes_graphed']}/{stats['nodes_total']}",
        ]
    lost = stats["files_failed"] + stats["nodes_failed"]
    if lost:
        parts.append(f"потеряно {lost}")
    return " · ".join(parts)


def _active_jobs() -> list[dict]:
    """Задачи, за которыми ещё имеет смысл следить."""
    return [
        job
        for job in st.session_state.jobs
        if job.get("job_id") and not process_client.is_terminal(job["status"])
    ]


@st.fragment(run_every=_POLL_INTERVAL)
def _render_active_jobs() -> None:
    """Поллит незавершённые задачи и рисует их прогресс.

    Неудачный опрос не считается ошибкой задачи: сохраняем последнее известное
    состояние и пробуем снова на следующем тике. Когда задача дошла до
    терминального статуса — просим полный ререн, чтобы она переехала в историю
    и фрагмент перестал тикать.
    """
    active = _active_jobs()
    if not active:
        return

    st.subheader("В работе")
    for job in active:
        snapshot = process_client.status(job["job_id"])
        if snapshot is not None:
            _apply_snapshot(job, snapshot)

        icon, label = _STATUS_VIEW.get(job["status"], ("•", job["status"]))
        st.progress(
            job.get("progress") or 0.0,
            text=f"{icon} {job['created_at']} · {label} · {job['files']} файл(ов)",
        )
        if job.get("stats"):
            st.caption(_stats_line(job["stats"]))

    if any(process_client.is_terminal(job["status"]) for job in active):
        st.rerun(scope="app")


def _render_dead_letters(job_id: str, key: str) -> None:
    """Детали потерь тянем по кнопке: незачем дёргать сервис на каждый рендер."""
    if not st.button("Показать потерянные батчи", key=f"dl_{key}"):
        return
    try:
        rows = process_client.dead_letters(job_id)
    except ProcessError as error:
        st.warning(str(error))
        return
    if not rows:
        st.caption("Сервис не сохранил детали потерь.")
        return
    for row in rows:
        st.markdown(f"**Стадия {row.get('stage', '?')}** — {row.get('error', '')}")
        items = row.get("items") or []
        if items:
            st.caption(", ".join(items[:_MAX_NAMES_SHOWN]))


def _render_history() -> None:
    st.subheader("История обработки")
    jobs = [
        job
        for job in st.session_state.jobs
        if not job.get("job_id") or process_client.is_terminal(job["status"])
    ]
    if not jobs:
        st.caption("Пока ничего не завершено.")
        return

    for idx, job in enumerate(jobs):
        icon, label = _STATUS_VIEW.get(job["status"], ("•", job["status"]))
        with st.expander(
            f"{icon} {job['created_at']} — {job['files']} файл(ов) · {label}",
            expanded=False,
        ):
            st.write(f"**Датасет:** {job['dataset']}")
            st.write("**Файлы:** " + ", ".join(job["file_names"][:_MAX_NAMES_SHOWN]))
            if len(job["file_names"]) > _MAX_NAMES_SHOWN:
                st.caption(f"…и ещё {len(job['file_names']) - _MAX_NAMES_SHOWN}")
            if job.get("stats"):
                st.caption(_stats_line(job["stats"]))
            if job.get("error"):
                st.error(job["error"])
            if job["status"] == "completed_with_errors" and job.get("job_id"):
                _render_dead_letters(job["job_id"], f"{idx}_{job['job_id']}")


def render() -> None:
    st.title("📤 Загрузка документов")
    st.caption(
        "Добавьте файлы или папку — они уйдут на обработку и станут доступны "
        "для вопросов в чате. Поддерживаются PDF, DOCX/DOC, PPTX, XLSX/XLS, "
        "CSV, MD, TXT."
    )
    _render_uploader()

    # Фрагменты с run_every вызываем только когда есть что поллить, иначе они
    # тикали бы вечно и дёргали сервис на пустом месте.
    if st.session_state.upload_futures:
        _render_upload_progress()

    st.divider()
    if _active_jobs():
        _render_active_jobs()
    _render_history()
