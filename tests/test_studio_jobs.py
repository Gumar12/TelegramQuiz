import time

from backend import studio_jobs


def test_job_manager_creates_job_and_records_events():
    manager = studio_jobs.JobManager()

    job = manager.create_job("validate")
    manager.emit(job.id, stage="validating", progress=50, message="Halfway")

    snapshot = manager.snapshot(job.id)
    events = manager.events_since(job.id, 0)

    assert snapshot["id"] == job.id
    assert snapshot["type"] == "validate"
    assert snapshot["status"] == "running"
    assert snapshot["progress"] == 50
    assert snapshot["current_step"] == "Halfway"
    assert len(events) == 2
    assert events[-1]["message"] == "Halfway"


def test_job_manager_marks_failed_jobs():
    manager = studio_jobs.JobManager()
    job = manager.create_job("parse")

    manager.fail(job.id, RuntimeError("boom"))

    snapshot = manager.snapshot(job.id)
    assert snapshot["status"] == "failed"
    assert snapshot["error"] == "boom"
    assert snapshot["progress"] == 100


def test_job_manager_cancel_sets_flag_and_event():
    manager = studio_jobs.JobManager()
    job = manager.create_job("upload")

    manager.cancel(job.id)

    snapshot = manager.snapshot(job.id)
    assert snapshot["cancel_requested"] is True
    assert snapshot["logs"][-1]["type"] == "warn"


def test_job_manager_marks_cancelled_when_target_raises_cancelled():
    manager = studio_jobs.JobManager()

    def target(job_id, job_manager):
        job_manager.cancel(job_id)
        job_manager.raise_if_cancelled(job_id)

    job = manager.run_in_thread("upload", target)

    for _ in range(50):
        snapshot = manager.snapshot(job.id)
        if snapshot["status"] == "cancelled":
            break
        time.sleep(0.01)
    else:
        raise AssertionError("job did not reach cancelled status")

    assert snapshot["progress"] == 100
    assert snapshot["error"] == "Job cancelled"
