from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

import backend.state as state_module
from backend.app import app
from backend.orchestrator import BatchProgress
from backend.routes.batch_routes import _batch_dir


client = TestClient(app)


def _batch_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def test_delete_batch_clears_memory_and_upload_dir():
    batch_id = _batch_id("delete")
    batch_dir = _batch_dir(batch_id)
    batch_dir.mkdir(parents=True, exist_ok=True)
    (batch_dir / "sample.txt").write_text("sample", encoding="utf-8")

    state_module.batches[batch_id] = {
        "batch_id": batch_id,
        "status": "success",
        "started_at": "2026-05-28T00:00:00+00:00",
        "finished_at": "2026-05-28T00:00:01+00:00",
        "total_files": 1,
        "summary": {},
    }
    state_module.batch_rules[batch_id] = [{"rule_id": "R1"}]
    state_module.batch_decisions[batch_id] = [{"rule_id": "R1", "action": "new"}]
    state_module.batch_progress[batch_id] = BatchProgress(total_files=1)
    state_module.batch_exports[batch_id] = {"main_csv": batch_dir / "exports" / "main.csv"}

    response = client.delete(f"/api/batches/{batch_id}")

    assert response.status_code == 200
    assert response.json() == {"batch_id": batch_id, "deleted": True}
    assert batch_id not in state_module.batches
    assert batch_id not in state_module.batch_rules
    assert batch_id not in state_module.batch_decisions
    assert batch_id not in state_module.batch_progress
    assert batch_id not in state_module.batch_exports
    assert not batch_dir.exists()


def test_delete_running_batch_is_rejected():
    batch_id = _batch_id("running")
    state_module.batches[batch_id] = {
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
        assert batch_id in state_module.batches
    finally:
        state_module.batches.pop(batch_id, None)
