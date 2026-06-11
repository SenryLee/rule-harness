"""v1.4 批次持久化助手 + 启动恢复。

网页端（batch_routes）与 Dify 端（dify_routes）共用，保证两条创建路径
的任务都能在重启/重新部署后恢复。state 仍是运行期主数据，SQLite 为副本。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from . import state
from . import storage
from .config import PROJECT_ROOT

logger = logging.getLogger(__name__)

_UPLOAD_DIR = PROJECT_ROOT / "data" / "uploads"

# orchestrator._do_exports 的 key → 文件名（恢复 batch_exports 用）
_EXPORT_FILENAMES: dict[str, str] = {
    "main_csv": "main.csv",
    "located_csv": "located.csv",
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


def persist_finish(batch_id: str) -> None:
    """批次结束后调用：状态/摘要/规则载荷一次性落库。"""
    batch = state.batches.get(batch_id)
    if not batch:
        return
    try:
        storage.upsert_batch_fields(batch_id, {
            "status": batch.get("status"),
            "finished_at": batch.get("finished_at"),
            "summary_json": json.dumps(batch.get("summary") or {}, ensure_ascii=False),
            "name": batch.get("name"),
        })
        storage.save_batch_payload(
            batch_id,
            state.batch_rules.get(batch_id, []),
            state.batch_decisions.get(batch_id, []),
        )
    except Exception:
        logger.exception("persist_finish failed for %s", batch_id)


def restore_state_from_db() -> int:
    """启动时恢复任务列表 + 导出索引（规则载荷懒加载）。返回恢复条数。"""
    try:
        records = storage.list_batches(limit=500)
    except Exception:
        logger.exception("restore: list_batches failed")
        return 0

    restored = 0
    for rec in records:
        if rec.batch_id in state.batches:
            continue
        try:
            file_metas = json.loads(rec.file_metas or "[]")
        except json.JSONDecodeError:
            file_metas = []
        try:
            summary = json.loads(rec.summary_json or "{}")
        except json.JSONDecodeError:
            summary = {}

        # 进程死亡时仍在跑的批次：恢复为 partial（无法续跑）
        status = rec.status or "unknown"
        if status in ("running", "pending", "stopping"):
            status = "partial"

        state.batches[rec.batch_id] = {
            "batch_id": rec.batch_id,
            "name": rec.name or rec.batch_id,
            "folder_id": rec.folder_id or "",
            "status": status,
            "started_at": rec.started_at or "",
            "finished_at": rec.finished_at or None,
            "total_files": len(file_metas),
            "file_metas": file_metas,
            "summary": summary,
        }

        exports_dir = _UPLOAD_DIR / rec.batch_id / "exports"
        if exports_dir.is_dir():
            exports: dict[str, Path] = {}
            for key, fname in _EXPORT_FILENAMES.items():
                path = exports_dir / fname
                if path.exists():
                    exports[key] = path
            if exports:
                state.batch_exports[rec.batch_id] = exports
        restored += 1

    if restored:
        logger.info("restore: %d batches restored from sqlite", restored)
    return restored
