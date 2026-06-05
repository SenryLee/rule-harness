"""Archive routes: classify uploaded files, confirm archive, browse results."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..archive_engine import (
    ArchiveResult,
    FileClassification,
    archive_result_to_dict,
    classification_to_dict,
    classify_files,
    enhance_with_llm,
    execute_archive,
)
from ..config import PROJECT_ROOT, load_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/archive", tags=["archive"])

_ARCHIVE_UPLOAD_DIR = PROJECT_ROOT / "data" / "archive_uploads"
_ARCHIVE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# In-memory state for pending classifications
_pending: dict[str, dict] = {}  # session_id → {classifications, source_dir, file_contents}
_archive_results: dict[str, dict] = {}  # archive_id → serialised ArchiveResult


# ── Step 1: Upload + classify ───────────────────────────────────────

@router.post("/classify")
async def classify_uploaded_files(
    files: list[UploadFile] = File(...),
    use_llm: str = Form("false"),
):
    """Upload files and get classification preview. Does not archive yet."""
    session_id = uuid.uuid4().hex[:12]
    session_dir = _ARCHIVE_UPLOAD_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: list[Path] = []
    file_contents: dict[str, bytes] = {}

    for file in files:
        filename = file.filename or "unknown"
        content = await file.read()
        dest = session_dir / filename
        # Handle duplicate filenames
        if dest.exists():
            stem = dest.stem
            suffix = dest.suffix
            counter = 1
            while dest.exists():
                dest = session_dir / f"{stem}_{counter}{suffix}"
                counter += 1
            filename = dest.name
        dest.write_bytes(content)
        saved_paths.append(dest)
        file_contents[filename] = content

    # Rule-based classification
    classifications = classify_files(saved_paths, file_contents)

    # LLM classification is ON by default; user can opt out with use_llm=false
    skip_llm = use_llm.lower() in {"false", "0", "no"}
    if not skip_llm:
        try:
            cfg = load_config()
            if cfg.models.primary.api_key:
                classifications = await enhance_with_llm(
                    classifications, file_contents, cfg
                )
        except Exception as exc:
            logger.warning("LLM classification failed, using keyword-only: %s", exc)

    # Store pending state
    _pending[session_id] = {
        "classifications": classifications,
        "source_dir": session_dir,
        "file_contents": file_contents,
    }

    return {
        "session_id": session_id,
        "total_files": len(classifications),
        "files": [classification_to_dict(c) for c in classifications],
        "categories": _build_category_summary(classifications),
    }


# ── Step 2: User adjusts classification (optional) ──────────────────

@router.put("/classify/{session_id}")
async def update_classification(session_id: str, updates: list[dict]):
    """Allow user to override classification for specific files.

    Body: [{original_name: "xxx.docx", category_dir: "法律法规/司法解释"}, ...]
    """
    pending = _pending.get(session_id)
    if not pending:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    classifications: list[FileClassification] = pending["classifications"]
    update_map = {u["original_name"]: u for u in updates}

    for item in classifications:
        if item.original_name in update_map:
            override = update_map[item.original_name]
            if "category_dir" in override:
                item.category_dir = override["category_dir"]
                item.evidence.append(f"用户手动修改分类: {override['category_dir']}")
                item.confidence = 1.0  # user override = max confidence

    return {
        "session_id": session_id,
        "files": [classification_to_dict(c) for c in classifications],
    }


# ── Step 3: Confirm archive ─────────────────────────────────────────

@router.post("/confirm/{session_id}")
async def confirm_archive(session_id: str):
    """Execute the archive: copy files into structured directories."""
    pending = _pending.get(session_id)
    if not pending:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    classifications = pending["classifications"]
    source_dir = pending["source_dir"]
    archive_id = session_id

    try:
        result = execute_archive(
            classifications=classifications,
            source_dir=source_dir,
            archive_id=archive_id,
        )
    except Exception as exc:
        logger.exception("Archive execution failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Store result, clean pending
    serialised = archive_result_to_dict(result)
    _archive_results[archive_id] = serialised
    _pending.pop(session_id, None)

    return serialised


# ── Browse archives ─────────────────────────────────────────────────

@router.get("/results")
async def list_archives():
    """List all completed archive sessions."""
    return list(_archive_results.values())


@router.get("/results/{archive_id}")
async def get_archive(archive_id: str):
    result = _archive_results.get(archive_id)
    if not result:
        raise HTTPException(status_code=404, detail="Archive not found")
    return result


@router.get("/categories")
async def list_available_categories():
    """Return the full category hierarchy for the frontend dropdown."""
    from ..archive_engine import _CATEGORY_MAP
    tree: dict[str, list[str]] = {}
    for _, (top, sub) in _CATEGORY_MAP.items():
        tree.setdefault(top, [])
        if sub not in tree[top]:
            tree[top].append(sub)
    return tree


# ── Helpers ─────────────────────────────────────────────────────────

def _build_category_summary(items: list[FileClassification]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.category_dir] = counts.get(item.category_dir, 0) + 1
    return dict(sorted(counts.items()))
