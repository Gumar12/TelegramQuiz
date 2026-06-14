import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import studio_api
from backend.studio_jobs import JobCancelled, JobManager


def test_health_endpoint():
    client = TestClient(studio_api.create_app())

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_groups_endpoint_lists_storage_groups(tmp_path: Path):
    quizzes_dir = tmp_path / "quizzes"
    quizzes_dir.mkdir()
    (quizzes_dir / "sample.json").write_text(
        json.dumps(
            {
                "quiz_title": "Sample",
                "quiz_description": "Desc",
                "questions": [
                    {
                        "question": "Who?",
                        "options": ["A", "B"],
                        "correct": 1,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    client = TestClient(studio_api.create_app(quizzes_dir=quizzes_dir))

    response = client.get("/api/groups")

    assert response.status_code == 200
    assert response.json()["groups"][0]["id"] == "sample"


def test_validate_job_returns_report(tmp_path: Path):
    quizzes_dir = tmp_path / "quizzes"
    quizzes_dir.mkdir()
    (quizzes_dir / "sample.json").write_text(
        json.dumps(
            {
                "quiz_title": "Sample",
                "questions": [
                    {
                        "question": "Who?",
                        "options": ["A", "B"],
                        "correct": 1,
                        "explanation": "",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    client = TestClient(studio_api.create_app(quizzes_dir=quizzes_dir))

    response = client.post("/api/jobs/validate", json={"group_id": "sample", "strict": False})

    assert response.status_code == 200
    job_id = response.json()["job_id"]
    snapshot = client.get(f"/api/jobs/{job_id}").json()
    assert snapshot["status"] == "completed"
    assert snapshot["result"]["report"]["questions_total"] == 1


def test_parse_docx_uses_workspace_dir(tmp_path: Path, monkeypatch):
    captured: dict[str, Path | str] = {}

    def fake_build_output(docx_path, output_path, media_dir, title, description):
        captured["docx_path"] = Path(docx_path)
        captured["output_path"] = Path(output_path)
        captured["media_dir"] = Path(media_dir)
        captured["title"] = title
        captured["description"] = description
        return {"report": {"items_total": 0}, "questions": []}

    monkeypatch.setattr(studio_api, "build_output", fake_build_output)
    monkeypatch.setattr(studio_api, "format_group_summary", lambda data: [])
    client = TestClient(studio_api.create_app())

    response = client.post(
        "/api/jobs/parse-docx",
        data={
            "title": "Custom source",
            "description": "Custom description",
            "workspace_dir": str(tmp_path),
        },
        files={
            "file": (
                "sample.docx",
                b"not a real docx because build_output is patched",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    assert response.status_code == 200
    job_id = response.json()["job_id"]
    for _ in range(50):
        snapshot = client.get(f"/api/jobs/{job_id}").json()
        if snapshot["status"] != "running":
            break
        time.sleep(0.01)

    assert snapshot["status"] == "completed"
    assert captured["output_path"] == tmp_path / "questions_v2.json"
    assert captured["media_dir"] == tmp_path / "media"
    assert captured["title"] == "Custom source"
    assert captured["description"] == "Custom description"
    workspace = client.get("/api/workspace").json()
    assert workspace["source_path"] == str(tmp_path / "questions_v2.json")
    assert workspace["quizzes_dir"] == str(tmp_path / "quizzes")


def test_media_endpoint_resolves_current_media_dir(tmp_path: Path):
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    image = media_dir / "image_001.png"
    image.write_bytes(b"fake-image")
    client = TestClient(studio_api.create_app(media_dir=media_dir))

    response = client.get("/api/media/media/image_001.png")

    assert response.status_code == 200
    assert response.content == b"fake-image"


def test_upload_media_saves_image_to_current_media_dir(tmp_path: Path):
    media_dir = tmp_path / "media"
    client = TestClient(studio_api.create_app(media_dir=media_dir))

    response = client.post(
        "/api/media/upload",
        files={"file": ("context.png", b"image-bytes", "image/png")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["path"].startswith("media/")
    assert payload["path"].endswith("_context.png")
    saved_path = Path(payload["saved_path"])
    assert saved_path.parent == media_dir
    assert saved_path.read_bytes() == b"image-bytes"
    assert client.get(f"/api/media/{payload['path']}").content == b"image-bytes"


def test_upload_media_rejects_non_image_extension(tmp_path: Path):
    client = TestClient(studio_api.create_app(media_dir=tmp_path / "media"))

    response = client.post(
        "/api/media/upload",
        files={"file": ("context.txt", b"text", "text/plain")},
    )

    assert response.status_code == 400


def test_generate_all_job_can_run_selected_queue(tmp_path: Path, monkeypatch):
    source_path = tmp_path / "questions_v2.json"
    source_path.write_text(
        json.dumps(
            {
                "questions": [
                    {"date": "10 мая", "section": "", "question": "A?", "options": ["A", "B"], "correct": 1},
                    {"date": "11 мая", "section": "", "question": "B?", "options": ["A", "B"], "correct": 1},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "quizzes"

    def fake_normalizer_run(args, cancel_check=None):
        Path(args.output).write_text(
            json.dumps({"quiz_title": Path(args.output).stem, "questions": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        return 0

    monkeypatch.setattr(studio_api.gpt_normalizer, "run", fake_normalizer_run)
    manager = JobManager()
    job = manager.create_job("generate-all-groups")
    request = studio_api.GenerateAllRequest(
        source_path=str(source_path),
        output_dir=str(output_dir),
        groups=["11 мая"],
    )

    result = studio_api._generate_all_job(request)(job.id, manager)

    assert [item["group"] for item in result["queue"]] == ["11 мая"]
    assert result["queue"][0]["status"] == "ready"
    assert result["groups"][0]["group"] == "11 мая"


def test_generate_all_job_passes_cancel_check_to_normalizer(tmp_path: Path, monkeypatch):
    source_path = tmp_path / "questions_v2.json"
    source_path.write_text(
        json.dumps(
            {
                "questions": [
                    {"date": "10 мая", "section": "", "question": "A?", "options": ["A", "B"], "correct": 1},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "quizzes"
    manager = JobManager()
    job = manager.create_job("generate-all-groups")

    def fake_normalizer_run(args, cancel_check=None):
        assert cancel_check is not None
        manager.cancel(job.id)
        with pytest.raises(JobCancelled):
            cancel_check()
        return 0

    monkeypatch.setattr(studio_api.gpt_normalizer, "run", fake_normalizer_run)
    request = studio_api.GenerateAllRequest(
        source_path=str(source_path),
        output_dir=str(output_dir),
        groups=["10 мая"],
    )

    with pytest.raises(JobCancelled):
        studio_api._generate_all_job(request)(job.id, manager)


def test_upload_queue_job_runs_items_in_order(tmp_path: Path, monkeypatch):
    quizzes_dir = tmp_path / "quizzes"
    quizzes_dir.mkdir()
    for stem in ["first", "second"]:
        (quizzes_dir / f"{stem}.json").write_text(
            json.dumps(
                {
                    "quiz_title": stem,
                    "questions": [
                        {
                            "question": "Who?",
                            "options": ["A", "B"],
                            "correct": 1,
                            "explanation": "",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    calls: list[str] = []

    async def fake_upload_run(file_path, quiz_name, **kwargs):
        calls.append(quiz_name)
        progress_callback = kwargs.get("progress_callback")
        if progress_callback:
            progress_callback("uploading", 1, 1, f"Uploaded {quiz_name}")
        return 0

    monkeypatch.setattr(studio_api.uploader_main, "run", fake_upload_run)
    manager = JobManager()
    job = manager.create_job("upload-queue")
    request = studio_api.UploadQueueRequest(
        items=[
            studio_api.UploadQueueItem(group_id="first", name="First"),
            studio_api.UploadQueueItem(group_id="second", name="Second"),
        ],
        speed="fast",
    )

    result = studio_api._upload_queue_job(request, quizzes_dir)(job.id, manager)

    assert calls == ["First", "Second"]
    assert [item["status"] for item in result["queue"]] == ["ready", "ready"]
    assert [item["group"] for item in result["groups"]] == ["First", "Second"]
