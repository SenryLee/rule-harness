"""FastAPI entry point for the Rule Extraction Harness.

Responsibilities (kept deliberately thin):
  * Route declarations.
  * Upload handling.
  * Spawning the orchestrator as a background task.
  * Static-file fallback for the built frontend.

All real work lives in :mod:`backend.orchestrator`.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import uvicorn
import yaml
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend import storage
from backend.config import (
    Config,
    PROJECT_ROOT,
    config_to_dict,
    load_config,
    save_config,
)
from backend.orchestrator import (
    BatchProgress,
    BatchResult,
    candidate_to_api_dict,
    decision_to_api_dict,
    run_batch,
)
from backend.preview import preview_classify_bytes

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

app = FastAPI(title="规则梳理 Harness", version="1.0.0")

# CORS: 本地开发 + 线上部署（Railway / 自定义域名）
_cors_origins = [
    "http://localhost:5199",
    "http://127.0.0.1:5199",
    "http://localhost:8765",
    "http://127.0.0.1:8765",
]
_extra_origins = os.environ.get("CORS_ORIGINS", "")
if _extra_origins:
    _cors_origins.extend(o.strip() for o in _extra_origins.split(",") if o.strip())
# 生产环境下前端与后端同源，无需额外 CORS；但保留 Railway 预览域名支持
if os.environ.get("RAILWAY_PUBLIC_DOMAIN"):
    _cors_origins.append(f"https://{os.environ['RAILWAY_PUBLIC_DOMAIN']}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PROFILES_DIR = PROJECT_ROOT / "profiles"
_UPLOAD_DIR = PROJECT_ROOT / "data" / "uploads"
_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# In-memory caches (per-process). SQLite is the persistent source of truth.
_batches: dict[str, dict] = {}
_batch_rules: dict[str, list[dict]] = {}
_batch_decisions: dict[str, list[dict]] = {}
_batch_progress: dict[str, BatchProgress] = {}
_batch_exports: dict[str, dict[str, Path]] = {}

_RISK_LEVELS = frozenset({"高", "中", "低"})
_RULE_TYPES = frozenset({"clause", "governance", "negative"})
_DEFAULT_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 1000


@app.on_event("startup")
def _init_db() -> None:
    """Make sure SQLite tables exist on every process start.

    v1.2 修订（Railway 部署）：先确保 data/ 目录存在，否则 sqlite3.connect 会
    抛 ``unable to open database file``。这在 Dockerfile 不显式建该目录时尤为重要。
    """
    try:
        (PROJECT_ROOT / "data").mkdir(parents=True, exist_ok=True)
        _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        storage.init_db()
        logger.info("startup: data dirs ready, sqlite initialised")
    except Exception:
        logger.exception("storage.init_db failed; persistence will be degraded")


# ---------------------------------------------------------------------------
# Health check (Railway / Docker / k8s liveness)
# ---------------------------------------------------------------------------

@app.get("/api/health")
@app.get("/health")
async def health() -> dict[str, str]:
    """极轻量健康检查端点：不读盘 / 不解析 yaml / 不查 sqlite。

    同时挂在 ``/health`` 和 ``/api/health`` 两个路径，是因为：
      - ``/api/*`` 路径有时会被反向代理 / 静态挂载吃掉（``app.mount("/")``
        虽然在路由表中靠后，但部分 ASGI middleware 会改路由匹配顺序）
      - 直接根路径 ``/health`` 永远在 mount("/") 之前被命中

    Railway healthcheck 配置（见 ``railway.toml``）现在指向 ``/health``。

    上线日志关键字：``startup: data dirs ready, sqlite initialised``。
    """
    return {"status": "ok", "service": "rule-harness"}


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _batch_dir(batch_id: str) -> Path:
    return _UPLOAD_DIR / batch_id


def _exports_dir(batch_id: str) -> Path:
    return _batch_dir(batch_id) / "exports"


def _load_yaml(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError) as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read YAML: {exc}") from exc


def _load_theme_keys() -> set[str]:
    raw = _load_yaml(PROJECT_ROOT / "theme_keys.yaml")
    return set(raw.get("keys", []) or [])


def _validate_risk_level(level: str) -> None:
    if level not in _RISK_LEVELS:
        raise HTTPException(status_code=422, detail=f"Invalid risk_level: {level}")


def _validate_rule_type(rule_type: str) -> None:
    if rule_type not in _RULE_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid rule_type: {rule_type}")


def _deep_merge(base: dict, update: dict) -> None:
    for k, v in update.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def _parse_full_config(raw: dict) -> Config:
    """Parse a full dict back into a Config (for PUT /api/config)."""
    from backend.config import _parse_config

    return _parse_config(raw)


# ---------------------------------------------------------------------------
# Config routes
# ---------------------------------------------------------------------------

@app.get("/api/config")
async def get_config():
    cfg = load_config()
    return config_to_dict(cfg)


@app.put("/api/config")
async def update_config(payload: dict):
    cfg = load_config()
    merged = config_to_dict(cfg)
    _deep_merge(merged, payload)
    raw = yaml.safe_load(yaml.safe_dump(merged, allow_unicode=True))
    new_cfg = _parse_full_config(raw)
    save_config(new_cfg)
    return config_to_dict(new_cfg)


@app.get("/api/profiles")
async def list_profiles():
    if not PROFILES_DIR.exists():
        return []
    result = []
    for f in sorted(PROFILES_DIR.glob("*.yaml")):
        raw = _load_yaml(f)
        result.append({
            "name": f.stem,
            "label": raw.get("name", f.stem),
            "description": raw.get("description", ""),
        })
    return result


@app.get("/api/profiles/{name}")
async def get_profile(name: str):
    path = PROFILES_DIR / f"{name}.yaml"
    if not path.exists():
        path = PROFILES_DIR / f"{name}.yml"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Profile not found: {name}")
    raw = _load_yaml(path)
    focus = raw.get("focus_points", "")
    return {
        "name": path.stem,
        "label": raw.get("name", path.stem),
        "description": raw.get("description", ""),
        "vocabulary": raw.get("vocabulary", []),
        "focus_points": focus.strip() if isinstance(focus, str) else focus,
        "priority_overrides": raw.get("priority_overrides", {}),
    }


@app.put("/api/profiles/{name}")
async def save_profile(name: str, payload: dict):
    """Persist a profile YAML.

    Accepts either a "profile-shaped" object (``name/description/vocabulary/...``)
    *or* a full :class:`Config`-shaped object (used by the legacy frontend);
    in the latter case only the industry-related slices are stored.
    """
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    if "vocabulary" in payload or "focus_points" in payload:
        data = {
            "name": payload.get("name", name),
            "description": payload.get("description", ""),
            "vocabulary": payload.get("vocabulary", []),
            "focus_points": payload.get("focus_points", ""),
            "priority_overrides": payload.get("priority_overrides", {}),
        }
    elif "extraction" in payload:
        extraction = payload.get("extraction", {})
        data = {
            "name": name,
            "description": payload.get("description", ""),
            "vocabulary": [s.strip() for s in extraction.get("industry_vocabulary", "").split("\n") if s.strip()],
            "focus_points": extraction.get("industry_focus_points", ""),
            "priority_overrides": payload.get("priority_overrides", {}),
        }
    else:
        data = payload

    path = PROFILES_DIR / f"{name}.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")
    return {"name": name, "saved": True}


@app.delete("/api/profiles/{name}")
async def delete_profile(name: str):
    for ext in (".yaml", ".yml"):
        p = PROFILES_DIR / f"{name}{ext}"
        if p.exists():
            p.unlink()
            return {"name": name, "deleted": True}
    raise HTTPException(status_code=404, detail=f"Profile not found: {name}")


# ---------------------------------------------------------------------------
# Batch routes
# ---------------------------------------------------------------------------

@app.post("/api/preview-classify")
async def preview_classify(file: UploadFile = File(...)):
    content = await file.read()
    return preview_classify_bytes(file.filename or "upload", content)


@app.post("/api/batches")
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
    _batches[batch_id] = {
        "batch_id": batch_id,
        "status": "running",
        "started_at": now,
        "finished_at": None,
        "total_files": len(files),
        "file_metas": saved_metas,
        "summary": {},
    }
    _batch_progress[batch_id] = BatchProgress(total_files=len(files))

    background_tasks.add_task(_run_batch_task, batch_id, saved_metas)
    return {"batch_id": batch_id, "status": "running"}


async def _run_batch_task(batch_id: str, file_metas: list[dict]) -> None:
    batch_dir = _batch_dir(batch_id)
    exports_dir = _exports_dir(batch_id)
    progress = _batch_progress[batch_id]

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
        _batch_rules[batch_id] = [candidate_to_api_dict(r) for r in result.rules]
        _batch_decisions[batch_id] = [decision_to_api_dict(d) for d in result.decisions]
        _batch_exports[batch_id] = result.exports
        _batches[batch_id]["status"] = progress.status
        _batches[batch_id]["finished_at"] = _now_iso()
        _batches[batch_id]["summary"] = result.summary
    except Exception as exc:
        logger.exception("Batch %s failed", batch_id)
        progress.errors.append(str(exc))
        progress.status = "partial"
        _batches[batch_id]["status"] = "partial"
        _batches[batch_id]["finished_at"] = _now_iso()


@app.get("/api/batches")
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
        for b in sorted(_batches.values(), key=lambda x: x["started_at"], reverse=True)
    ]


@app.get("/api/batches/{batch_id}")
async def get_batch(batch_id: str):
    batch = _batches.get(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    return batch


@app.get("/api/batches/{batch_id}/progress")
async def get_batch_progress(batch_id: str):
    if batch_id not in _batches:
        raise HTTPException(status_code=404, detail="Batch not found")
    progress = _batch_progress.get(batch_id)
    return progress.to_dict() if progress else {"status": "unknown"}


@app.get("/api/batches/{batch_id}/rules")
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
    if batch_id not in _batches:
        raise HTTPException(status_code=404, detail="Batch not found")

    rules = list(_batch_rules.get(batch_id, []))
    if risk_level:
        _validate_risk_level(risk_level)
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


@app.get("/api/batches/{batch_id}/exports/main-csv")
async def export_main_csv(batch_id: str):
    return _serve_export(batch_id, "main_csv", media_type="text/csv",
                         download_name=f"{batch_id}_main.csv")


@app.get("/api/batches/{batch_id}/exports/metadata-csv")
async def export_metadata_csv(batch_id: str):
    return _serve_export(batch_id, "metadata_csv", media_type="text/csv",
                         download_name=f"{batch_id}_metadata.csv")


@app.get("/api/batches/{batch_id}/exports/conflict-report")
async def export_conflict_report(batch_id: str):
    return _serve_export(batch_id, "conflict_report", media_type="text/html",
                         download_name=f"{batch_id}_conflicts.html")


@app.get("/api/batches/{batch_id}/exports/change-set")
async def export_change_set(batch_id: str):
    return _serve_export(batch_id, "change_set", media_type="text/csv",
                         download_name=f"{batch_id}_changes.csv")


@app.get("/api/batches/{batch_id}/exports/summary")
async def export_summary(batch_id: str):
    return _serve_export(batch_id, "summary_html", media_type="text/html",
                         download_name=f"{batch_id}_summary.html")


# v1.1 新增导出路由
@app.get("/api/batches/{batch_id}/exports/placeholders-csv")
async def export_placeholders(batch_id: str):
    return _serve_export(batch_id, "placeholders_csv", media_type="text/csv",
                         download_name=f"{batch_id}_placeholders.csv")


@app.get("/api/batches/{batch_id}/exports/discarded-csv")
async def export_discarded(batch_id: str):
    return _serve_export(batch_id, "discarded_csv", media_type="text/csv",
                         download_name=f"{batch_id}_discarded.csv")


@app.get("/api/batches/{batch_id}/exports/negotiation-csv")
async def export_negotiation(batch_id: str):
    return _serve_export(batch_id, "negotiation_csv", media_type="text/csv",
                         download_name=f"{batch_id}_negotiation.csv")


def _serve_export(batch_id: str, key: str, media_type: str, download_name: str):
    if batch_id not in _batches:
        raise HTTPException(status_code=404, detail="Batch not found")
    exports = _batch_exports.get(batch_id, {})
    path = exports.get(key)
    if path is None or not Path(path).exists():
        # fallback to default location on disk
        fname = {
            "main_csv": "main.csv",
            "metadata_csv": "metadata.csv",
            "conflict_report": "conflict_report.html",
            "change_set": "change_set.csv",
            "summary_html": "summary.html",
            "placeholders_csv": "placeholders.csv",
            "discarded_csv": "discarded.csv",
            "negotiation_csv": "negotiation.csv",
        }.get(key)
        if not fname:
            raise HTTPException(status_code=404, detail=f"Unknown export key: {key}")
        candidate = _exports_dir(batch_id) / fname
        if not candidate.exists():
            raise HTTPException(status_code=404, detail="Export not yet generated")
        path = candidate
    return FileResponse(path, media_type=media_type, filename=download_name)


@app.post("/api/batches/{batch_id}/apply")
async def apply_batch(batch_id: str):
    """Apply the merge decisions (no-op — orchestrator already persisted)."""
    if batch_id not in _batches:
        raise HTTPException(status_code=404, detail="Batch not found")
    batch = _batches[batch_id]
    if batch["status"] not in ("success", "partial"):
        raise HTTPException(status_code=409, detail="Batch is not ready")
    decisions = _batch_decisions.get(batch_id, [])
    applied = sum(1 for d in decisions if d.get("action") in ("new", "update", "add_variant"))
    skipped = len(decisions) - applied
    batch["status"] = "merged"
    return {"applied": applied, "skipped": skipped, "total": len(decisions)}


# ---------------------------------------------------------------------------
# Rule library
# ---------------------------------------------------------------------------

@app.get("/api/rules")
async def browse_rules(
    risk_level: Optional[str] = Query(None),
    rule_type: Optional[str] = Query(None),
    theme_key: Optional[str] = Query(None),
    contract_type: Optional[str] = Query(None),
    enabled: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(_DEFAULT_PAGE_SIZE, ge=1, le=_MAX_PAGE_SIZE),
):
    all_rules: list[dict] = []
    for rules in _batch_rules.values():
        all_rules.extend(rules)

    if risk_level:
        _validate_risk_level(risk_level)
        all_rules = [r for r in all_rules if r.get("risk_level") == risk_level]
    if rule_type:
        _validate_rule_type(rule_type)
        all_rules = [r for r in all_rules if r.get("rule_type") == rule_type]
    if theme_key:
        all_rules = [r for r in all_rules if r.get("theme_key") == theme_key]
    if contract_type:
        all_rules = [r for r in all_rules if contract_type in (r.get("contract_types") or [])]
    if enabled is not None:
        want = "启用" if enabled else "停用"
        all_rules = [r for r in all_rules if r.get("enabled", "启用") == want]
    if search:
        term = search.lower()
        all_rules = [
            r for r in all_rules
            if term in r.get("check_item", "").lower()
            or term in r.get("requirement", "").lower()
            or any(term in kw.lower() for kw in r.get("keywords", []))
        ]

    total = len(all_rules)
    start = (page - 1) * page_size
    items = all_rules[start:start + page_size]
    return {"rules": items, "total": total, "page": page, "page_size": page_size}


@app.put("/api/rules/{rule_id}/enabled")
async def toggle_rule_enabled(rule_id: str, payload: dict):
    enabled_val = payload.get("enabled")
    if not isinstance(enabled_val, bool):
        raise HTTPException(status_code=422, detail="Body must contain 'enabled' as boolean")
    want = "启用" if enabled_val else "停用"
    for rules in _batch_rules.values():
        for r in rules:
            if r.get("rule_id") == rule_id:
                r["enabled"] = want
                return {"rule_id": rule_id, "enabled": enabled_val}
    raise HTTPException(status_code=404, detail=f"Rule not found: {rule_id}")


# ---------------------------------------------------------------------------
# Themes
# ---------------------------------------------------------------------------

@app.get("/api/themes")
async def list_themes():
    return {"keys": sorted(_load_theme_keys())}


@app.get("/api/themes/pending")
async def list_pending_themes():
    whitelist = _load_theme_keys()
    pending: dict[str, list[dict]] = {}
    for rules in _batch_rules.values():
        for r in rules:
            tk = r.get("theme_key", "")
            if tk and tk not in whitelist:
                pending.setdefault(tk, []).append(r)
    result = [
        {"theme_key": tk, "rule_count": len(rs), "sample_rule": rs[0] if rs else None}
        for tk, rs in pending.items()
    ]
    return sorted(result, key=lambda x: x["theme_key"])


@app.post("/api/themes/approve")
async def approve_themes(payload: dict):
    mappings = payload.get("mappings")
    if not isinstance(mappings, dict):
        raise HTTPException(status_code=422, detail="Body must contain 'mappings' as dict")

    whitelist = _load_theme_keys()
    for _pending_key, approved_key in mappings.items():
        if approved_key and approved_key not in whitelist:
            raise HTTPException(
                status_code=422,
                detail=f"Approved key '{approved_key}' is not in the theme whitelist",
            )

    updated = 0
    for rules in _batch_rules.values():
        for r in rules:
            current = r.get("theme_key", "")
            if current in mappings and mappings[current]:
                r["theme_key"] = mappings[current]
                updated += 1
    return {"updated": updated, "mappings": mappings}


# ---------------------------------------------------------------------------
# Static frontend (production build)
# ---------------------------------------------------------------------------

_frontend_dist = PROJECT_ROOT / "frontend" / "dist"
if _frontend_dist.is_dir() and (_frontend_dist / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
else:
    logger.info("frontend/dist not found — serve frontend separately via vite (port 5199)")


# ---------------------------------------------------------------------------
# CLI entry: spawn vite + uvicorn together
# ---------------------------------------------------------------------------

def _start_vite() -> Optional[subprocess.Popen]:
    """Launch ``npm run dev`` so the dev server is reachable at :5199.

    Returns ``None`` if npm is not available — backend still works, frontend
    has to be served some other way.
    """
    if shutil.which("npm") is None:
        logger.warning("npm not on PATH; skipping frontend dev server")
        return None
    frontend_dir = PROJECT_ROOT / "frontend"
    if not frontend_dir.exists():
        return None
    try:
        return subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=str(frontend_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # 创建独立进程组，便于 killpg
        )
    except (FileNotFoundError, OSError) as exc:
        logger.warning("Failed to start vite: %s", exc)
        return None


def main() -> None:
    npm_proc = _start_vite()

    def _cleanup(*_: object) -> None:
        if npm_proc is not None:
            try:
                os.killpg(os.getpgid(npm_proc.pid), signal.SIGTERM)
                npm_proc.wait(timeout=5)
            except (ProcessLookupError, OSError):
                pass
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(npm_proc.pid), signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    pass
        sys.exit(0)

    signal.signal(signal.SIGINT, _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)

    print()
    print("  后端: http://localhost:8765")
    if npm_proc is not None:
        print("  前端: http://localhost:5199")
    else:
        print("  前端: 未启动（npm 不在 PATH 或 frontend/ 缺失）")
    print()

    uvicorn.run("backend.app:app", host="0.0.0.0", port=8765, reload=False)


if __name__ == "__main__":
    main()
