"""FastAPI entry point for the Rule Extraction Harness.

Thin shell: setup, middleware, router include, static mount, CLI entry.
All route logic lives in :mod:`backend.routes`.
"""
from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend import storage
from backend.config import PROJECT_ROOT
from backend.routes.archive_routes import router as archive_router
from backend.routes.batch_routes import router as batch_router
from backend.routes.config_routes import router as config_router
from backend.routes.dify_routes import router as dify_router
from backend.routes.folder_routes import router as folder_router
from backend.routes.rule_routes import router as rule_router

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

app = FastAPI(title="规则梳理 Harness", version="2.0.0")

# CORS
_cors_origins = [
    "http://localhost:5199",
    "http://127.0.0.1:5199",
    "http://localhost:8765",
    "http://127.0.0.1:8765",
]
_extra_origins = os.environ.get("CORS_ORIGINS", "")
if _extra_origins:
    _cors_origins.extend(o.strip() for o in _extra_origins.split(",") if o.strip())
if os.environ.get("RAILWAY_PUBLIC_DOMAIN"):
    _cors_origins.append(f"https://{os.environ['RAILWAY_PUBLIC_DOMAIN']}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(archive_router)
app.include_router(batch_router)
app.include_router(config_router)
app.include_router(dify_router)
app.include_router(folder_router)
app.include_router(rule_router)

_UPLOAD_DIR = PROJECT_ROOT / "data" / "uploads"


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
def _init_db() -> None:
    try:
        (PROJECT_ROOT / "data").mkdir(parents=True, exist_ok=True)
        _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        storage.init_db()
        logger.info("startup: data dirs ready, sqlite initialised")
    except Exception:
        logger.exception("storage.init_db failed; persistence will be degraded")
    # v1.4：从 SQLite 恢复任务列表/导出索引（规则载荷懒加载），重启不丢任务
    try:
        from backend.batch_persist import restore_state_from_db
        restore_state_from_db()
    except Exception:
        logger.exception("restore_state_from_db failed; task list starts empty")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/api/health")
@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "rule-harness"}


# ---------------------------------------------------------------------------
# Static frontend (production build)
# ---------------------------------------------------------------------------

_frontend_dist = PROJECT_ROOT / "frontend" / "dist"
if _frontend_dist.is_dir() and (_frontend_dist / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
else:
    logger.info("frontend/dist not found — serve frontend separately via vite (port 5199)")


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------

def _start_vite() -> Optional[subprocess.Popen]:
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
            start_new_session=True,
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
