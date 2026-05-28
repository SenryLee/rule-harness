from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

import backend.app as app_module
from backend.orchestrator import BatchProgress


client = TestClient(app_module.app)


def _batch_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def test_delete_batch_clears_memory_and_upload_dir():
    batch_id = _batch_id("delete")
    batch_dir = app_module._batch_dir(batch_id)
    batch_dir.mkdir(parents=True, exist_ok=True)
    (batch_dir / "sample.txt").write_text("sample", encoding="utf-8")

    app_module._batches[batch_id] = {
        "batch_id": batch_id,
        "status": "success",
        "started_at": "2026-05-28T00:00:00+00:00",
        "finished_at": "2026-05-28T00:00:01+00:00",
        "total_files": 1,
        "summary": {},
    }
    app_module._batch_rules[batch_id] = [{"rule_id": "R1"}]
    app_module._batch_decisions[batch_id] = [{"rule_id": "R1", "action": "new"}]
    app_module._batch_progress[batch_id] = BatchProgress(total_files=1)
    app_module._batch_exports[batch_id] = {"main_csv": batch_dir / "exports" / "main.csv"}

    response = client.delete(f"/api/batches/{batch_id}")

    assert response.status_code == 200
    assert response.json() == {"batch_id": batch_id, "deleted": True}
    assert batch_id not in app_module._batches
    assert batch_id not in app_module._batch_rules
    assert batch_id not in app_module._batch_decisions
    assert batch_id not in app_module._batch_progress
    assert batch_id not in app_module._batch_exports
    assert not batch_dir.exists()


def test_delete_running_batch_is_rejected():
    batch_id = _batch_id("running")
    app_module._batches[batch_id] = {
        "batch_id": batch_id,
        "status": "running",
        "started_at": "2026-05-28T00:00:00+00:00",
        "finished_at": None,
        "total_files": 1,
        "summary": {},
    }

    try:
        response = client.delete(f"/api/batches/{batch_id}")

        assert response.status_code == 409
        assert batch_id in app_module._batches
    finally:
        app_module._batches.pop(batch_id, None)
