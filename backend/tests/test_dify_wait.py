from __future__ import annotations

from fastapi.testclient import TestClient

from backend import state
from backend.app import app


def _register_batch(batch_id: str, status: str, rules: list[dict] | None = None) -> None:
    state.batches[batch_id] = {
        "batch_id": batch_id,
        "status": status,
        "started_at": "2026-06-10T00:00:00+00:00",
        "finished_at": "2026-06-10T00:01:00+00:00" if status != "running" else None,
        "total_files": 1,
        "file_metas": [],
        "summary": {"total_rules": len(rules or [])},
        "source": "dify",
    }
    if rules is not None:
        state.batch_rules[batch_id] = rules


def test_wait_returns_immediately_when_done():
    _register_batch("dify_waitdone", "success", rules=[{"rule_id": "R1"}])
    client = TestClient(app)
    resp = client.get("/api/dify/batches/dify_waitdone/wait?timeout=0")
    assert resp.status_code == 200
    body = resp.json()
    assert body["done"] is True
    assert body["status"] == "success"
    assert body["total_rules"] == 1
    assert body["rules"][0]["rule_id"] == "R1"


def test_wait_excludes_rules_when_flag_off():
    _register_batch("dify_waitnorules", "success", rules=[{"rule_id": "R1"}])
    client = TestClient(app)
    resp = client.get("/api/dify/batches/dify_waitnorules/wait?timeout=0&include_rules=false")
    body = resp.json()
    assert body["done"] is True
    assert "rules" not in body
    assert body["total_rules"] == 1


def test_wait_times_out_while_running():
    _register_batch("dify_waitrun", "running")
    client = TestClient(app)
    resp = client.get("/api/dify/batches/dify_waitrun/wait?timeout=0")
    assert resp.status_code == 200
    body = resp.json()
    assert body["done"] is False
    assert body["status"] == "running"
    assert "rules" not in body


def test_wait_unblocks_when_batch_finishes():
    _register_batch("dify_waitflip", "running")
    client = TestClient(app)

    # TestClient 是同步的；用后台线程翻转状态来验证长轮询会解除阻塞
    import threading

    threading.Timer(0.5, lambda: state.batches["dify_waitflip"].update(status="success")).start()
    resp = client.get("/api/dify/batches/dify_waitflip/wait?timeout=10")
    body = resp.json()
    assert body["done"] is True
    assert body["status"] == "success"


def test_wait_rejects_unknown_batch():
    client = TestClient(app)
    resp = client.get("/api/dify/batches/no_such_batch/wait?timeout=0")
    assert resp.status_code == 404


def test_wait_caps_timeout_param():
    client = TestClient(app)
    resp = client.get("/api/dify/batches/whatever/wait?timeout=300")
    # 超出上限被 FastAPI 校验拒绝（422），而不是阻塞 300 秒
    assert resp.status_code == 422
