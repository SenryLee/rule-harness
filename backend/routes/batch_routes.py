"""Batch lifecycle routes: create, progress, rules, exports, apply, delete."""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from ..config import PROJECT_ROOT, load_config
from ..orchestrator import (
    BatchProgress,
    BatchResult,
    candidate_to_api_dict,
    decision_to_api_dict,
    run_batch,
)
from ..preview import preview_classify_bytes, preview_classify_with_llm
from ..skill_builder import SkillConfig, build_skill_zip, built_skill_to_dict
from .. import state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["batches"])

_UPLOAD_DIR = PROJECT_ROOT / "data" / "uploads"
_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

_RISK_LEVELS = frozenset({"高", "中", "低"})
_DEFAULT_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 1000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _batch_dir(batch_id: str) -> Path:
    return _UPLOAD_DIR / batch_id


def _exports_dir(batch_id: str) -> Path:
    return _batch_dir(batch_id) / "exports"


# ---- Preview ----

@router.post("/preview-classify")
async def preview_classify(file: UploadFile = File(...)):
    """Classify a file using LLM by default, fallback to keyword-only."""
    content = await file.read()
    filename = file.filename or "upload"
    try:
        cfg = load_config()
        if cfg.models.primary.api_key:
            from ..llm import create_llm_router
            llm_router = create_llm_router(cfg)
            try:
                return await preview_classify_with_llm(filename, content, llm_router)
            finally:
                try:
                    await llm_router.aclose()
                except Exception:
                    logger.debug("preview router close failed", exc_info=True)
    except Exception:
        logger.debug("LLM classify unavailable, falling back to keyword-only")
    return preview_classify_bytes(filename, content)


# ---- Batch CRUD ----

@router.post("/batches")
async def create_batch(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    meta: str = Form(...),
):
    try:
        file_metas: list[dict] = json.loads(meta)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid meta JSON: {exc}") from exc

    if len(files) != len(file_metas):
        raise HTTPException(
            status_code=422,
            detail=f"Files count ({len(files)}) must match meta count ({len(file_metas)})",
        )

    batch_id = uuid.uuid4().hex[:12]
    batch_dir = _batch_dir(batch_id)
    batch_dir.mkdir(parents=True, exist_ok=True)

    saved_metas = []
    for idx, (file, meta_item) in enumerate(zip(files, file_metas)):
        safe_name = f"{idx:03d}_{file.filename or 'upload.bin'}"
        dest = batch_dir / safe_name
        content = await file.read()
        dest.write_bytes(content)
        saved_metas.append({
            **meta_item,
            "filename": safe_name,
            "original_name": file.filename,
        })

    now = _now_iso()
    state.batches[batch_id] = {
        "batch_id": batch_id,
        "status": "running",
        "started_at": now,
        "finished_at": None,
        "total_files": len(files),
        "file_metas": saved_metas,
        "summary": {},
    }
    state.batch_progress[batch_id] = BatchProgress(total_files=len(files))

    background_tasks.add_task(_run_batch_task, batch_id, saved_metas)
    return {"batch_id": batch_id, "status": "running"}


async def _run_batch_task(batch_id: str, file_metas: list[dict]) -> None:
    batch_dir = _batch_dir(batch_id)
    exports_dir = _exports_dir(batch_id)
    progress = state.batch_progress[batch_id]

    try:
        cfg = load_config()
        result: BatchResult = await run_batch(
            batch_id=batch_id,
            file_metas=file_metas,
            batch_dir=batch_dir,
            exports_dir=exports_dir,
            cfg=cfg,
            progress=progress,
        )
        state.batch_rules[batch_id] = [candidate_to_api_dict(r) for r in result.rules]
        state.batch_decisions[batch_id] = [decision_to_api_dict(d) for d in result.decisions]
        state.batch_exports[batch_id] = result.exports
        state.batches[batch_id]["status"] = progress.status
        state.batches[batch_id]["finished_at"] = _now_iso()
        state.batches[batch_id]["summary"] = result.summary
    except Exception as exc:
        logger.exception("Batch %s failed", batch_id)
        progress.errors.append(str(exc))
        progress.status = "partial"
        state.batches[batch_id]["status"] = "partial"
        state.batches[batch_id]["finished_at"] = _now_iso()


@router.get("/batches")
async def list_batches():
    return [
        {
            "batch_id": b["batch_id"],
            "status": b["status"],
            "started_at": b["started_at"],
            "finished_at": b.get("finished_at"),
            "total_files": b["total_files"],
            "stats": b.get("summary", {}),
        }
        for b in sorted(state.batches.values(), key=lambda x: x["started_at"], reverse=True)
    ]


@router.get("/batches/{batch_id}")
async def get_batch(batch_id: str):
    batch = state.batches.get(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    return batch


@router.delete("/batches/{batch_id}")
async def delete_batch(batch_id: str):
    batch = state.batches.get(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch.get("status") in {"running", "pending"}:
        raise HTTPException(status_code=409, detail="Batch is still running")

    state.batches.pop(batch_id, None)
    state.batch_rules.pop(batch_id, None)
    state.batch_decisions.pop(batch_id, None)
    state.batch_progress.pop(batch_id, None)
    state.batch_exports.pop(batch_id, None)

    batch_dir = _batch_dir(batch_id)
    if batch_dir.exists():
        shutil.rmtree(batch_dir)

    return {"batch_id": batch_id, "deleted": True}


@router.post("/batches/{batch_id}/cancel")
async def cancel_batch(batch_id: str):
    """协作式停止：置取消标志，编排器停止启动新文本块；已抽规则照常去重/合并/导出。"""
    batch = state.batches.get(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    progress = state.batch_progress.get(batch_id)
    if progress is None or batch.get("status") not in {"running", "pending", "stopping"}:
        # 已结束或无进度对象：幂等返回当前状态
        return {
            "batch_id": batch_id,
            "status": batch.get("status", "unknown"),
            "cancel_requested": bool(progress and progress.cancel_requested),
        }
    progress.cancel_requested = True
    batch["status"] = "stopping"
    return {"batch_id": batch_id, "status": "stopping", "cancel_requested": True}


# ---- Progress (polling + SSE) ----

@router.get("/batches/{batch_id}/progress")
async def get_batch_progress(batch_id: str):
    if batch_id not in state.batches:
        raise HTTPException(status_code=404, detail="Batch not found")
    progress = state.batch_progress.get(batch_id)
    return progress.to_dict() if progress else {"status": "unknown"}


@router.get("/batches/{batch_id}/progress/stream")
async def stream_batch_progress(batch_id: str):
    """SSE endpoint — pushes progress events until the batch finishes."""
    if batch_id not in state.batches:
        raise HTTPException(status_code=404, detail="Batch not found")

    async def event_generator():
        last_json = ""
        while True:
            progress = state.batch_progress.get(batch_id)
            if not progress:
                yield f"data: {json.dumps({'status': 'unknown'})}\n\n"
                break
            current = json.dumps(progress.to_dict(), ensure_ascii=False)
            if current != last_json:
                yield f"data: {current}\n\n"
                last_json = current
            if progress.status in ("success", "partial", "failed", "cancelled"):
                break
            await asyncio.sleep(0.8)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---- Batch rules ----

@router.get("/batches/{batch_id}/rules")
async def list_batch_rules(
    batch_id: str,
    risk_level: Optional[str] = Query(None),
    pipeline: Optional[str] = Query(None),
    confidence_min: Optional[float] = Query(None),
    confidence_max: Optional[float] = Query(None),
    conflict_flag: Optional[str] = Query(None),
    contract_type: Optional[str] = Query(None),
    source_file: Optional[str] = Query(None),
    output_target: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(_DEFAULT_PAGE_SIZE, ge=1, le=_MAX_PAGE_SIZE),
):
    if batch_id not in state.batches:
        raise HTTPException(status_code=404, detail="Batch not found")

    rules = list(state.batch_rules.get(batch_id, []))
    if risk_level:
        if risk_level not in _RISK_LEVELS:
            raise HTTPException(status_code=422, detail=f"Invalid risk_level: {risk_level}")
        rules = [r for r in rules if r.get("risk_level") == risk_level]
    if pipeline:
        rules = [r for r in rules if r.get("pipeline") == pipeline]
    if confidence_min is not None:
        rules = [r for r in rules if r.get("combined_confidence", 0) >= confidence_min]
    if confidence_max is not None:
        rules = [r for r in rules if r.get("combined_confidence", 0) <= confidence_max]
    if conflict_flag is not None:
        rules = [r for r in rules if r.get("conflict_flag") == conflict_flag]
    if contract_type:
        rules = [r for r in rules if contract_type in (r.get("contract_types") or [])]
    if source_file:
        rules = [r for r in rules if r.get("source_file") == source_file]
    if output_target:
        rules = [r for r in rules if r.get("output_target", "main") == output_target]

    total = len(rules)
    start = (page - 1) * page_size
    items = rules[start:start + page_size]
    return {"rules": items, "total": total, "page": page, "page_size": page_size}


# ---- Exports ----

_EXPORT_KEYS: dict[str, str] = {
    "main_csv": "main.csv",
    "metadata_csv": "metadata.csv",
    "conflict_report": "conflict_report.html",
    "change_set": "change_set.csv",
    "summary_html": "summary.html",
    "placeholders_csv": "placeholders.csv",
    "discarded_csv": "discarded.csv",
    "negotiation_csv": "negotiation.csv",
    "out_of_scope_csv": "out_of_scope.csv",
    "skipped_csv": "skipped_blocks.csv",
    "template_strategy_md": "template_strategy.md",
}


def _serve_export(batch_id: str, key: str, media_type: str, download_name: str):
    if batch_id not in state.batches:
        raise HTTPException(status_code=404, detail="Batch not found")
    exports = state.batch_exports.get(batch_id, {})
    path = exports.get(key)
    if path is None or not Path(path).exists():
        fname = _EXPORT_KEYS.get(key)
        if not fname:
            raise HTTPException(status_code=404, detail=f"Unknown export key: {key}")
        candidate = _exports_dir(batch_id) / fname
        if not candidate.exists():
            raise HTTPException(status_code=404, detail="Export not yet generated")
        path = candidate
    return FileResponse(path, media_type=media_type, filename=download_name)


@router.get("/batches/{batch_id}/exports/main-csv")
async def export_main_csv(batch_id: str):
    return _serve_export(batch_id, "main_csv", "text/csv", f"{batch_id}_main.csv")


@router.get("/batches/{batch_id}/exports/metadata-csv")
async def export_metadata_csv(batch_id: str):
    return _serve_export(batch_id, "metadata_csv", "text/csv", f"{batch_id}_metadata.csv")


@router.get("/batches/{batch_id}/exports/conflict-report")
async def export_conflict_report(batch_id: str):
    return _serve_export(batch_id, "conflict_report", "text/html", f"{batch_id}_conflicts.html")


@router.get("/batches/{batch_id}/exports/change-set")
async def export_change_set(batch_id: str):
    return _serve_export(batch_id, "change_set", "text/csv", f"{batch_id}_changes.csv")


@router.get("/batches/{batch_id}/exports/summary")
async def export_summary(batch_id: str):
    return _serve_export(batch_id, "summary_html", "text/html", f"{batch_id}_summary.html")


@router.get("/batches/{batch_id}/exports/placeholders-csv")
async def export_placeholders(batch_id: str):
    return _serve_export(batch_id, "placeholders_csv", "text/csv", f"{batch_id}_placeholders.csv")


@router.get("/batches/{batch_id}/exports/discarded-csv")
async def export_discarded(batch_id: str):
    return _serve_export(batch_id, "discarded_csv", "text/csv", f"{batch_id}_discarded.csv")


@router.get("/batches/{batch_id}/exports/negotiation-csv")
async def export_negotiation(batch_id: str):
    return _serve_export(batch_id, "negotiation_csv", "text/csv", f"{batch_id}_negotiation.csv")


@router.get("/batches/{batch_id}/exports/out-of-scope-csv")
async def export_out_of_scope(batch_id: str):
    return _serve_export(batch_id, "out_of_scope_csv", "text/csv", f"{batch_id}_out_of_scope.csv")


@router.get("/batches/{batch_id}/exports/skipped-csv")
async def export_skipped(batch_id: str):
    return _serve_export(batch_id, "skipped_csv", "text/csv", f"{batch_id}_skipped_blocks.csv")


@router.get("/batches/{batch_id}/exports/template-strategy")
async def export_template_strategy(batch_id: str):
    return _serve_export(batch_id, "template_strategy_md", "text/markdown", f"{batch_id}_template_strategy.md")


# ---- Skill generation ----

@router.post("/batches/{batch_id}/generate-skill")
async def generate_skill(batch_id: str, body: dict):
    if batch_id not in state.batches:
        raise HTTPException(status_code=404, detail="Batch not found")
    batch = state.batches[batch_id]
    if batch["status"] not in ("success", "partial", "merged"):
        raise HTTPException(status_code=409, detail="Batch is not ready")

    rules = state.batch_rules.get(batch_id, [])
    if not rules:
        raise HTTPException(status_code=409, detail="No rules extracted in this batch")

    cfg = SkillConfig(
        domain_name=body.get("domain_name", "通用合同"),
        party_perspectives=body.get("party_perspectives", ["甲方", "乙方"]),
        include_drafting=body.get("include_drafting", True),
        llm_enhance=body.get("llm_enhance", False),
    )

    try:
        result = build_skill_zip(rules, cfg, batch_id)
        # Store zip path for download
        exports = state.batch_exports.setdefault(batch_id, {})
        exports["skill_zip"] = result.zip_path
        return built_skill_to_dict(result)
    except Exception as exc:
        logger.exception("Skill generation failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/batches/{batch_id}/exports/skill-zip")
async def export_skill_zip(batch_id: str):
    if batch_id not in state.batches:
        raise HTTPException(status_code=404, detail="Batch not found")
    exports = state.batch_exports.get(batch_id, {})
    path = exports.get("skill_zip")
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail="Skill ZIP not yet generated. Call generate-skill first.")
    return FileResponse(
        path,
        media_type="application/zip",
        filename=Path(path).name,
    )


# ---- Apply merge ----

@router.post("/batches/{batch_id}/apply")
async def apply_batch(batch_id: str):
    if batch_id not in state.batches:
        raise HTTPException(status_code=404, detail="Batch not found")
    batch = state.batches[batch_id]
    if batch["status"] not in ("success", "partial"):
        raise HTTPException(status_code=409, detail="Batch is not ready")
    decisions = state.batch_decisions.get(batch_id, [])
    applied = sum(1 for d in decisions if d.get("action") in ("new", "update", "add_variant"))
    skipped = len(decisions) - applied
    batch["status"] = "merged"
    return {"applied": applied, "skipped": skipped, "total": len(decisions)}
