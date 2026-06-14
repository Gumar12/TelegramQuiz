"""Local FastAPI backend for QuizBot Studio."""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import time
from argparse import Namespace
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import config
from backend import gpt_normalizer
from backend import main as uploader_main
from backend import studio_storage
from backend import validate_quiz_json
from backend.docx_to_quiz_json_v2 import build_output, format_group_summary
from backend.generate_editable_quiz import (
    group_label,
    group_labels,
    normalizer_args,
    output_path_for_group,
    safe_stem,
    write_group_source,
)
from backend.normalizer_io import load_v2_dataset
from backend.studio_jobs import JobManager


SOURCE_FILENAME = Path("questions_v2.json")
MEDIA_DIRNAME = Path("media")
OUTPUT_DIRNAME = Path("quizzes")
WORKDIR_NAME = Path(".normalizer_tmp")
UPLOAD_DIRNAME = Path(".studio_data") / "uploads"

DEFAULT_SOURCE_PATH = config.DATA_DIR / SOURCE_FILENAME
DEFAULT_MEDIA_DIR = config.DATA_DIR / MEDIA_DIRNAME
DEFAULT_OUTPUT_DIR = config.DATA_DIR / OUTPUT_DIRNAME
DEFAULT_WORKDIR = config.DATA_DIR / WORKDIR_NAME
MEDIA_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".webp"}


def _resolve_path(value: str | Path | None, default: str | Path = ".") -> Path:
    raw = str(value if value not in {None, ""} else default).strip() or str(default)
    return Path(raw).expanduser()


def _workspace_paths(workspace_dir: str | Path | None) -> tuple[Path, Path, Path, Path]:
    workspace = _resolve_path(workspace_dir, config.DATA_DIR)
    return (
        workspace,
        workspace / SOURCE_FILENAME,
        workspace / MEDIA_DIRNAME,
        workspace / OUTPUT_DIRNAME,
    )


def _safe_media_filename(filename: str | None) -> str:
    source_name = Path(filename or "image").name
    suffix = Path(source_name).suffix.lower()
    if suffix not in MEDIA_SUFFIXES:
        raise HTTPException(status_code=400, detail="Only image files are supported")
    stem = re.sub(r"[^0-9A-Za-zА-Яа-я_-]+", "_", Path(source_name).stem, flags=re.U).strip("_") or "image"
    return f"{int(time.time() * 1000)}_{stem}{suffix}"


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _media_candidates(media_path: str, media_dir: Path, workspace_dir: Path) -> list[Path]:
    normalized = media_path.replace("\\", "/").lstrip("/")
    relative = Path(normalized)
    if relative.is_absolute():
        return [relative]

    candidates: list[Path] = []
    if normalized.startswith("media/"):
        candidates.append(media_dir / normalized.split("/", 1)[1])
    else:
        candidates.append(media_dir / relative)
    candidates.extend([media_dir / relative.name, workspace_dir / relative])
    return candidates


class GenerateAllRequest(BaseModel):
    source_path: str | None = None
    output_dir: str = str(DEFAULT_OUTPUT_DIR)
    groups: list[str] | None = None
    skip_existing: bool = True
    model: str = ""
    max_retries: int = 3
    seed: int = 42
    media_root: str = str(config.DATA_DIR)
    style_examples: int = 5
    image_detail: str = "high"


class ValidateRequest(BaseModel):
    group_id: str
    strict: bool = False


class UploadRequest(BaseModel):
    group_id: str
    name: str | None = None
    speed: str = "normal"
    context_send_mode: str = "once"
    shuffle_options: bool = True


class UploadQueueItem(BaseModel):
    group_id: str
    name: str | None = None


class UploadQueueRequest(BaseModel):
    items: list[UploadQueueItem]
    speed: str = "normal"
    context_send_mode: str = "once"
    shuffle_options: bool = True


def _require_job(manager: JobManager, job_id: str) -> dict[str, Any]:
    try:
        return manager.snapshot(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown job: {job_id}") from exc


def _source_group_summaries(source_path: Path, output_dir: Path) -> list[dict[str, Any]]:
    if not source_path.exists():
        return []

    source_data = load_v2_dataset(source_path)
    counts: dict[str, int] = {}
    for item in source_data.get("questions", []):
        if not isinstance(item, dict):
            continue
        label = group_label(item)
        if not label:
            continue
        counts[label] = counts.get(label, 0) + 1

    groups: list[dict[str, Any]] = []
    for label, count in counts.items():
        output_path = output_path_for_group(output_dir, label)
        groups.append(
            {
                "id": output_path.stem,
                "name": label,
                "questions_count": count,
                "generated": output_path.exists(),
                "path": str(output_path),
            }
        )
    return groups


def _parse_docx_job(
    *,
    docx_path: Path,
    output_path: Path,
    media_dir: Path,
    title: str,
    description: str,
):
    def run(job_id: str, manager: JobManager) -> dict[str, Any]:
        manager.emit(job_id, stage="parsing", progress=5, message=f"Reading DOCX: {docx_path.name}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        media_dir.mkdir(parents=True, exist_ok=True)
        data = build_output(docx_path, output_path, media_dir, title=title, description=description)
        groups = format_group_summary(data)
        manager.emit(
            job_id,
            stage="parsing",
            progress=100,
            message=f"Parsed {data['report']['items_total']} questions",
            log_type="success",
            result={"source_path": str(output_path), "groups": groups, "report": data["report"]},
        )
        return {"source_path": str(output_path), "groups": groups, "report": data["report"]}

    return run


def _generate_all_job(args: GenerateAllRequest):
    def run(job_id: str, manager: JobManager) -> dict[str, Any]:
        source_path = Path(args.source_path or DEFAULT_SOURCE_PATH)
        source_data = load_v2_dataset(source_path)
        available_labels = group_labels(source_data)
        if args.groups:
            known_labels = set(available_labels)
            unknown_labels = [label for label in args.groups if label not in known_labels]
            if unknown_labels:
                raise ValueError(f"Unknown groups requested: {', '.join(unknown_labels)}")
            labels = []
            for label in args.groups:
                if label not in labels:
                    labels.append(label)
        else:
            labels = available_labels
        if not labels:
            raise ValueError("No groups found in source JSON")

        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        group_workdir = DEFAULT_WORKDIR / "groups"
        results: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        queue: list[dict[str, Any]] = [
            {
                "group": label,
                "status": "queued",
                "questions": 0,
                "output": str(output_path_for_group(output_dir, label)),
            }
            for label in labels
        ]

        def queue_result() -> dict[str, Any]:
            return {
                "queue": queue,
                "groups": results,
                "failures": failures,
                "skipped": skipped,
                "output_dir": str(output_dir),
            }

        manager.emit(
            job_id,
            stage="normalizing",
            progress=0,
            message=f"Queued {len(labels)} group(s) for JSON generation",
            result=queue_result(),
        )

        for index, label in enumerate(labels, start=1):
            if manager.is_cancel_requested(job_id):
                for item in queue[index - 1:]:
                    if item["status"] == "queued":
                        item["status"] = "cancelled"
                manager.emit(
                    job_id,
                    stage="normalizing",
                    progress=100,
                    message="Generation queue cancelled",
                    log_type="warn",
                    result=queue_result(),
                )
                manager.raise_if_cancelled(job_id)
            progress = int((index - 1) / len(labels) * 100)
            queue[index - 1]["status"] = "creating"
            manager.emit(
                job_id,
                stage="normalizing",
                progress=progress,
                group=label,
                message=f"Normalizing group {index}/{len(labels)}: {label}",
                eta=max(0, (len(labels) - index + 1) * 30),
                result=queue_result(),
            )
            output_path = output_path_for_group(output_dir, label)
            group_source = group_workdir / f"{safe_stem(output_path)}_source.json"
            selected_count = write_group_source(source_data, label, group_source)
            queue[index - 1]["questions"] = selected_count
            if selected_count == 0:
                failure = {"group": label, "error": "no questions found"}
                failures.append(failure)
                queue[index - 1]["status"] = "error"
                queue[index - 1]["error"] = failure["error"]
                manager.emit(
                    job_id,
                    stage="normalizing",
                    progress=progress,
                    group=label,
                    message=f"Skipped empty group: {label}",
                    log_type="warn",
                    result=queue_result(),
                )
                continue

            if args.skip_existing and output_path.exists():
                skipped.append({"group": label, "output": str(output_path), "questions": selected_count})
                queue[index - 1]["status"] = "ready"
                manager.emit(
                    job_id,
                    stage="normalizing",
                    progress=int(index / len(labels) * 100),
                    group=label,
                    message=f"Already exists, left unchanged: {output_path.name}",
                    log_type="success",
                    result=queue_result(),
                )
                continue

            normalizer_namespace = Namespace(
                source=str(source_path),
                docx=None,
                all_groups=False,
                output_dir=str(output_dir),
                group=label,
                output=str(output_path),
                review=None,
                report=None,
                workdir=str(DEFAULT_WORKDIR),
                model=args.model,
                max_retries=args.max_retries,
                seed=args.seed,
                media_root=args.media_root,
                style_source=None,
                style_examples=args.style_examples,
                image_detail=args.image_detail,
                dry_run=False,
            )
            group_args = normalizer_args(normalizer_namespace, group_source, source_path)
            manager.raise_if_cancelled(job_id)
            exit_code = gpt_normalizer.run(
                group_args,
                cancel_check=lambda: manager.raise_if_cancelled(job_id),
            )
            if manager.is_cancel_requested(job_id):
                queue[index - 1]["status"] = "cancelled"
                for item in queue[index:]:
                    if item["status"] == "queued":
                        item["status"] = "cancelled"
                manager.emit(
                    job_id,
                    stage="normalizing",
                    progress=100,
                    group=label,
                    message="Generation queue cancelled",
                    log_type="warn",
                    result=queue_result(),
                )
                manager.raise_if_cancelled(job_id)
            if exit_code == 0:
                results.append({"group": label, "output": str(output_path), "questions": selected_count})
                queue[index - 1]["status"] = "ready"
                manager.emit(
                    job_id,
                    stage="normalizing",
                    progress=int(index / len(labels) * 100),
                    group=label,
                    message=f"Generated JSON {index}/{len(labels)}: {output_path.name}",
                    log_type="success",
                    result=queue_result(),
                )
            else:
                failures.append({"group": label, "exit_code": exit_code})
                queue[index - 1]["status"] = "error"
                queue[index - 1]["error"] = f"exit code {exit_code}"
                manager.emit(
                    job_id,
                    stage="normalizing",
                    progress=int(index / len(labels) * 100),
                    group=label,
                    message=f"Generation failed for {label}: exit code {exit_code}",
                    log_type="error",
                    result=queue_result(),
                )

        result = queue_result()
        if failures:
            manager.emit(job_id, stage="normalizing", progress=100, message="Finished with failures", log_type="warn", result=result)
        return result

    return run


def _validate_job(group_id: str, strict: bool, quizzes_dir: Path):
    def run(job_id: str, manager: JobManager) -> dict[str, Any]:
        path = quizzes_dir / f"{Path(group_id).name}.json"
        manager.emit(job_id, stage="validating", progress=25, group=group_id, message=f"Validating {path.name}")
        questions, raw_items = validate_quiz_json.load_questions_with_raw(path)
        validate_quiz_json.validate_all(questions)
        report = validate_quiz_json.build_quality_report(questions, raw_items)
        exit_code = 2 if strict and report["warnings"] else 0
        result = {"report": report, "exit_code": exit_code, "strict": strict}
        log_type = "warn" if report["warnings"] else "success"
        manager.emit(
            job_id,
            stage="validating",
            progress=100,
            group=group_id,
            message=f"Validation completed with {len(report['warnings'])} warnings",
            log_type=log_type,
            result=result,
        )
        return result

    return run


def _upload_job(request: UploadRequest, quizzes_dir: Path):
    def run(job_id: str, manager: JobManager) -> dict[str, Any]:
        path = quizzes_dir / f"{Path(request.group_id).name}.json"
        name = request.name or request.group_id.replace("_", " ")
        manager.emit(job_id, stage="uploading", progress=5, group=name, message=f"Uploading {path.name} to @QuizBot")

        def progress_callback(stage: str, done: int, total: int, message: str) -> None:
            manager.raise_if_cancelled(job_id)
            if stage == "loaded":
                progress = 8
            elif stage == "creating":
                progress = 12
            elif stage == "uploading":
                progress = 15 + int((done / total) * 75) if total else 90
            elif stage == "finishing":
                progress = 95
            elif stage == "completed":
                progress = 100
            else:
                progress = 10
            seconds_per_question = 5 if request.speed == "fast" else 20
            eta = max(0, (total - done) * seconds_per_question)
            manager.emit(
                job_id,
                stage="uploading",
                progress=progress,
                group=name,
                message=message,
                eta=eta,
            )

        exit_code = asyncio.run(
            uploader_main.run(
                str(path),
                name,
                context_send_mode=request.context_send_mode,
                shuffle_options=request.shuffle_options,
                speed=request.speed,
                progress_callback=progress_callback,
                cancel_check=lambda: manager.raise_if_cancelled(job_id),
            )
        )
        result = {"exit_code": exit_code}
        if exit_code != 0:
            raise RuntimeError(f"Upload failed with exit code {exit_code}")
        manager.emit(job_id, stage="uploading", progress=100, group=name, message="Upload completed", log_type="success", result=result)
        return result

    return run


def _upload_queue_job(request: UploadQueueRequest, quizzes_dir: Path):
    def run(job_id: str, manager: JobManager) -> dict[str, Any]:
        if not request.items:
            raise ValueError("Upload queue is empty")

        queue: list[dict[str, Any]] = [
            {
                "group_id": item.group_id,
                "group": item.name or item.group_id.replace("_", " "),
                "status": "queued",
                "progress": 0,
            }
            for item in request.items
        ]
        completed: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []

        def queue_result() -> dict[str, Any]:
            return {"queue": queue, "groups": completed, "failures": failures}

        manager.emit(
            job_id,
            stage="uploading",
            progress=0,
            message=f"Queued {len(queue)} quiz upload(s)",
            result=queue_result(),
        )

        for index, item in enumerate(request.items, start=1):
            if manager.is_cancel_requested(job_id):
                for queue_item in queue[index - 1:]:
                    if queue_item["status"] == "queued":
                        queue_item["status"] = "cancelled"
                manager.emit(
                    job_id,
                    stage="uploading",
                    progress=100,
                    message="Telegram upload queue cancelled",
                    log_type="warn",
                    result=queue_result(),
                )
                manager.raise_if_cancelled(job_id)

            queue_item = queue[index - 1]
            queue_item["status"] = "uploading"
            path = quizzes_dir / f"{Path(item.group_id).name}.json"
            name = item.name or item.group_id.replace("_", " ")
            base_progress = int((index - 1) / len(queue) * 100)
            manager.emit(
                job_id,
                stage="uploading",
                progress=base_progress,
                group=name,
                message=f"Uploading quiz {index}/{len(queue)}: {name}",
                result=queue_result(),
            )

            def progress_callback(stage: str, done: int, total: int, message: str) -> None:
                manager.raise_if_cancelled(job_id)
                if stage == "loaded":
                    local_progress = 8
                elif stage == "creating":
                    local_progress = 12
                elif stage == "uploading":
                    local_progress = 15 + int((done / total) * 75) if total else 90
                elif stage == "finishing":
                    local_progress = 95
                elif stage == "completed":
                    local_progress = 100
                else:
                    local_progress = 10
                queue_item["progress"] = local_progress
                total_progress = int(((index - 1) + (local_progress / 100)) / len(queue) * 100)
                seconds_per_question = 5 if request.speed == "fast" else 20
                eta = max(0, ((len(queue) - index) * max(total, 1) + (total - done)) * seconds_per_question)
                manager.emit(
                    job_id,
                    stage="uploading",
                    progress=total_progress,
                    group=name,
                    message=f"{index}/{len(queue)}: {message}",
                    eta=eta,
                    result=queue_result(),
                )

            try:
                exit_code = asyncio.run(
                    uploader_main.run(
                        str(path),
                        name,
                        context_send_mode=request.context_send_mode,
                        shuffle_options=request.shuffle_options,
                        speed=request.speed,
                        progress_callback=progress_callback,
                        cancel_check=lambda: manager.raise_if_cancelled(job_id),
                    )
                )
            except Exception as exc:
                if manager.is_cancel_requested(job_id):
                    queue_item["status"] = "cancelled"
                    for queue_tail in queue[index:]:
                        if queue_tail["status"] == "queued":
                            queue_tail["status"] = "cancelled"
                    manager.emit(
                        job_id,
                        stage="uploading",
                        progress=100,
                        group=name,
                        message="Telegram upload queue cancelled",
                        log_type="warn",
                        result=queue_result(),
                    )
                    manager.raise_if_cancelled(job_id)
                queue_item["status"] = "error"
                queue_item["error"] = str(exc)
                failures.append({"group": name, "group_id": item.group_id, "error": str(exc)})
                manager.emit(
                    job_id,
                    stage="uploading",
                    progress=int(index / len(queue) * 100),
                    group=name,
                    message=f"Upload failed for {name}: {exc}",
                    log_type="error",
                    result=queue_result(),
                )
                continue

            if exit_code != 0:
                queue_item["status"] = "error"
                queue_item["error"] = f"exit code {exit_code}"
                failures.append({"group": name, "group_id": item.group_id, "exit_code": exit_code})
                manager.emit(
                    job_id,
                    stage="uploading",
                    progress=int(index / len(queue) * 100),
                    group=name,
                    message=f"Upload failed for {name}: exit code {exit_code}",
                    log_type="error",
                    result=queue_result(),
                )
                continue

            queue_item["status"] = "ready"
            queue_item["progress"] = 100
            completed.append({"group": name, "group_id": item.group_id})
            manager.emit(
                job_id,
                stage="uploading",
                progress=int(index / len(queue) * 100),
                group=name,
                message=f"Uploaded quiz {index}/{len(queue)}: {name}",
                log_type="success",
                result=queue_result(),
            )

        result = queue_result()
        if failures:
            manager.emit(job_id, stage="uploading", progress=100, message="Upload queue finished with failures", log_type="warn", result=result)
        return result

    return run


def create_app(
    *,
    quizzes_dir: str | Path = DEFAULT_OUTPUT_DIR,
    source_path: str | Path = DEFAULT_SOURCE_PATH,
    media_dir: str | Path = DEFAULT_MEDIA_DIR,
    manager: JobManager | None = None,
) -> FastAPI:
    app = FastAPI(title="QuizBot Studio API")
    app.state.workspace_dir = config.DATA_DIR
    app.state.source_path = Path(source_path)
    app.state.media_dir = Path(media_dir)
    app.state.quizzes_dir = Path(quizzes_dir)
    app.state.manager = manager or JobManager()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "time": int(time.time())}

    @app.get("/api/groups")
    def groups() -> dict[str, Any]:
        return {"groups": studio_storage.list_groups(app.state.quizzes_dir)}

    @app.get("/api/source-groups")
    def source_groups() -> dict[str, Any]:
        return {"groups": _source_group_summaries(app.state.source_path, app.state.quizzes_dir)}

    @app.get("/api/workspace")
    def workspace() -> dict[str, Any]:
        return {
            "workspace_dir": str(app.state.workspace_dir),
            "source_path": str(app.state.source_path),
            "media_dir": str(app.state.media_dir),
            "quizzes_dir": str(app.state.quizzes_dir),
        }

    @app.get("/api/media/{media_path:path}")
    def media(media_path: str) -> FileResponse:
        media_dir = Path(app.state.media_dir).resolve()
        workspace_dir = Path(app.state.workspace_dir).resolve()
        allowed_roots = [media_dir, workspace_dir]
        for candidate in _media_candidates(media_path, media_dir, workspace_dir):
            resolved = candidate.resolve()
            if not any(_is_relative_to(resolved, root) for root in allowed_roots):
                continue
            if resolved.exists() and resolved.is_file():
                return FileResponse(resolved)
        raise HTTPException(status_code=404, detail=f"Media file not found: {media_path}")

    @app.post("/api/media/upload")
    async def upload_media(file: UploadFile = File(...)) -> dict[str, Any]:
        media_dir = Path(app.state.media_dir)
        media_dir.mkdir(parents=True, exist_ok=True)
        filename = _safe_media_filename(file.filename)
        target = media_dir / filename
        with target.open("wb") as fh:
            shutil.copyfileobj(file.file, fh)
        return {
            "path": f"media/{filename}",
            "filename": filename,
            "saved_path": str(target),
        }

    @app.get("/api/groups/{group_id}")
    def group(group_id: str) -> dict[str, Any]:
        try:
            return studio_storage.load_group(group_id, app.state.quizzes_dir)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/api/groups/{group_id}")
    def save_group(group_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return studio_storage.save_group(group_id, payload, app.state.quizzes_dir)

    @app.post("/api/jobs/parse-docx")
    async def parse_docx(
        file: UploadFile = File(...),
        title: str = Form("История Казахстана"),
        description: str = Form("Generated source"),
        workspace_dir: str = Form("."),
    ) -> dict[str, Any]:
        workspace_dir_path, source_path, media_dir, quizzes_dir = _workspace_paths(workspace_dir)
        app.state.workspace_dir = workspace_dir_path
        app.state.source_path = source_path
        app.state.media_dir = media_dir
        app.state.quizzes_dir = quizzes_dir

        upload_dir = workspace_dir_path / UPLOAD_DIRNAME
        upload_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(file.filename or "upload.docx").suffix or ".docx"
        target = upload_dir / f"{int(time.time())}{suffix}"
        with target.open("wb") as fh:
            shutil.copyfileobj(file.file, fh)
        job = app.state.manager.run_in_thread(
            "parse-docx",
            _parse_docx_job(
                docx_path=target,
                output_path=source_path,
                media_dir=media_dir,
                title=title,
                description=description,
            ),
        )
        return {"job_id": job.id}

    @app.post("/api/jobs/generate-all-groups")
    def generate_all_groups(request: GenerateAllRequest) -> dict[str, Any]:
        if request.source_path:
            app.state.source_path = Path(request.source_path)
        app.state.quizzes_dir = Path(request.output_dir)
        media_root = _resolve_path(request.media_root, app.state.workspace_dir)
        app.state.workspace_dir = media_root
        app.state.media_dir = media_root / MEDIA_DIRNAME
        job = app.state.manager.run_in_thread("generate-all-groups", _generate_all_job(request))
        return {"job_id": job.id}

    @app.post("/api/jobs/validate")
    def validate(request: ValidateRequest) -> dict[str, Any]:
        job = app.state.manager.create_job("validate")
        try:
            result = _validate_job(request.group_id, request.strict, app.state.quizzes_dir)(job.id, app.state.manager)
            app.state.manager.complete(job.id, result)
        except BaseException as exc:  # noqa: BLE001 - API job boundary
            app.state.manager.fail(job.id, exc)
        return {"job_id": job.id}

    @app.post("/api/jobs/upload")
    def upload(request: UploadRequest) -> dict[str, Any]:
        job = app.state.manager.run_in_thread("upload", _upload_job(request, app.state.quizzes_dir))
        return {"job_id": job.id}

    @app.post("/api/jobs/upload-queue")
    def upload_queue(request: UploadQueueRequest) -> dict[str, Any]:
        job = app.state.manager.run_in_thread("upload-queue", _upload_queue_job(request, app.state.quizzes_dir))
        return {"job_id": job.id}

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str) -> dict[str, Any]:
        try:
            app.state.manager.cancel(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown job: {job_id}") from exc
        return {"ok": True}

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str) -> dict[str, Any]:
        return _require_job(app.state.manager, job_id)

    @app.get("/api/jobs/{job_id}/events")
    async def job_events(job_id: str) -> StreamingResponse:
        _require_job(app.state.manager, job_id)

        async def event_stream():
            index = 0
            while True:
                events = app.state.manager.events_since(job_id, index)
                for event in events:
                    index = event["index"] + 1
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                snapshot = app.state.manager.snapshot(job_id)
                if snapshot["status"] in {"completed", "failed", "cancelled"} and not events:
                    break
                await asyncio.sleep(0.5)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    if DEFAULT_MEDIA_DIR.exists():
        app.mount("/media", StaticFiles(directory=DEFAULT_MEDIA_DIR), name="media")

    studio_dist = config.PROJECT_ROOT / "frontend" / "dist"
    if studio_dist.exists():
        app.mount("/", StaticFiles(directory=studio_dist, html=True), name="studio")

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("backend.studio_api:app", host="127.0.0.1", port=8000, reload=False)
