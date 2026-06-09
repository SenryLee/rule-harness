"""Dify 集成路由 — 文件上传 & JSON 导出。

本模块独立于已有 batch/rule 路由，专为对接 Dify 工作流设计：
  1. POST /api/dify/upload — 接收 Dify HTTP 节点传入的文件，创建批次并触发抽取
  2. GET  /api/dify/batches/{batch_id}/status — 轮询批次状态（供 Dify 轮询节点）
  3. GET  /api/dify/batches/{batch_id}/rules.json — 下载规则 JSON（供 Dify 后续节点消费）

后续直接在此文件扩展 Dify 相关接口即可，不影响已有路由。
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from ..config import PROJECT_ROOT, load_config
from ..orchestrator import BatchProgress, BatchResult, candidate_to_api_dict, run_batch
from .. import state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dify", tags=["dify"])

_UPLOAD_DIR = PROJECT_ROOT / "data" / "uploads"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _batch_dir(batch_id: str) -> Path:
    return _UPLOAD_DIR / batch_id


def _exports_dir(batch_id: str) -> Path:
    return _batch_dir(batch_id) / "exports"


# ---------------------------------------------------------------------------
# 1. Dify 文件上传 — 接收文件并创建批次
# ---------------------------------------------------------------------------

@router.post("/upload")
async def dify_upload(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    source_tag: str = Form(default="dify"),
    priority: int = Form(default=5),
    contract_types: str = Form(default=""),
):
    """接收 Dify HTTP 请求节点上传的文件。

    Dify 工作流中 HTTP 节点配置：
      - Method: POST
      - URL: {base_url}/api/dify/upload
      - Body type: form-data
      - files: 文件变量
      - source_tag: 来源标签（可选，默认 "dify"）
      - priority: 源优先级（可选，默认 5）
      - contract_types: 逗号分隔的合同类型（可选）

    返回 batch_id 供后续轮询状态和下载结果。
    """
    if not files:
        raise HTTPException(status_code=422, detail="至少需要上传一个文件")

    batch_id = f"dify_{uuid.uuid4().hex[:10]}"
    batch_dir = _batch_dir(batch_id)
    batch_dir.mkdir(parents=True, exist_ok=True)

    ct_list = [t.strip() for t in contract_types.split(",") if t.strip()]

    saved_metas: list[dict] = []
    for idx, file in enumerate(files):
        safe_name = f"{idx:03d}_{file.filename or 'upload.bin'}"
        dest = batch_dir / safe_name
        content = await file.read()
        dest.write_bytes(content)
        saved_metas.append({
            "filename": safe_name,
            "original_name": file.filename,
            "source_tag": source_tag,
            "priority": priority,
            "contract_types": ct_list,
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
        "source": "dify",
    }
    state.batch_progress[batch_id] = BatchProgress(total_files=len(files))

    background_tasks.add_task(_run_dify_batch, batch_id, saved_metas)

    return {"batch_id": batch_id, "status": "running", "total_files": len(files)}


async def _run_dify_batch(batch_id: str, file_metas: list[dict]) -> None:
    """后台执行批次抽取（与 batch_routes 逻辑一致）。"""
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
        state.batch_exports[batch_id] = result.exports
        state.batches[batch_id]["status"] = progress.status
        state.batches[batch_id]["finished_at"] = _now_iso()
        state.batches[batch_id]["summary"] = result.summary
    except Exception as exc:
        logger.exception("Dify batch %s failed", batch_id)
        progress.errors.append(str(exc))
        progress.status = "partial"
        state.batches[batch_id]["status"] = "partial"
        state.batches[batch_id]["finished_at"] = _now_iso()


# ---------------------------------------------------------------------------
# 2. 批次状态轮询 — 供 Dify 循环/条件节点判断
# ---------------------------------------------------------------------------

@router.get("/batches/{batch_id}/status")
async def dify_batch_status(batch_id: str):
    """返回精简的批次状态，方便 Dify 条件节点判断。

    返回字段：
      - status: running / success / partial / failed
      - total_rules: 已抽取规则数（仅完成后有值）
      - summary: 统计摘要
    """
    batch = state.batches.get(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    rules = state.batch_rules.get(batch_id, [])
    return {
        "batch_id": batch_id,
        "status": batch["status"],
        "total_rules": len(rules),
        "summary": batch.get("summary", {}),
        "finished_at": batch.get("finished_at"),
    }


# ---------------------------------------------------------------------------
# 3. JSON 导出 — 供 Dify 下游节点消费或用户预览
# ---------------------------------------------------------------------------

@router.get("/batches/{batch_id}/rules.json")
async def dify_export_rules_json(batch_id: str):
    """下载该批次所有规则的 JSON 格式文件。

    字段与现有 API /api/batches/{id}/rules 返回的结构完全一致，
    便于 Dify 后续节点直接解析、或用户预览校验。

    响应为 JSON 文件下载（Content-Disposition: attachment）。
    """
    batch = state.batches.get(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch["status"] == "running":
        raise HTTPException(status_code=409, detail="Batch is still running")

    rules = state.batch_rules.get(batch_id, [])

    payload = {
        "batch_id": batch_id,
        "status": batch["status"],
        "total_rules": len(rules),
        "exported_at": _now_iso(),
        "rules": rules,
    }

    # 同时写到 exports 目录以便持久化
    exports_dir = _exports_dir(batch_id)
    exports_dir.mkdir(parents=True, exist_ok=True)
    json_path = exports_dir / "rules.json"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    content = json.dumps(payload, ensure_ascii=False, indent=2)
    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{batch_id}_rules.json"',
        },
    )


# ---------------------------------------------------------------------------
# 4. Dify 自定义工具 Schema — 供 Dify「从 URL 中导入」一键创建工具
# ---------------------------------------------------------------------------

# 对外公网地址：Dify 会按此 URL 调用本服务。换域名时改这里或设环境变量 PUBLIC_BASE_URL。
_PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://rule-harness-demo.onrender.com")


@router.get("/openapi.json")
async def dify_openapi_schema():
    """返回专供 Dify 导入的 OpenAPI 3.0 规范（仅含 3 个 dify 接口）。

    在 Dify「工具 → 自定义 → 创建自定义工具 → 从 URL 中导入」处填入：
        {PUBLIC_BASE_URL}/api/dify/openapi.json
    即可一键生成 3 个 Action：上传 / 查状态 / 取规则。
    """
    spec = {
        "openapi": "3.0.1",
        "info": {
            "title": "规则梳理工具 - Dify 接入",
            "description": "上传法律文件→后台抽取结构化规则。异步流程：upload 拿 batch_id → 轮询 status → 完成后取 rules.json。",
            "version": "1.0.0",
        },
        "servers": [{"url": _PUBLIC_BASE_URL}],
        "paths": {
            "/api/dify/upload": {
                "post": {
                    "operationId": "uploadFiles",
                    "summary": "上传文件并启动规则抽取",
                    "description": "上传一个或多个法律文件，立即返回 batch_id；抽取在后台异步进行。",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "multipart/form-data": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "files": {
                                            "type": "array",
                                            "items": {"type": "string", "format": "binary"},
                                            "description": "要抽取规则的文件（可多个）",
                                        },
                                        "source_tag": {
                                            "type": "string",
                                            "description": "来源标签（可选）",
                                            "default": "dify",
                                        },
                                        "priority": {
                                            "type": "integer",
                                            "description": "来源优先级（可选）",
                                            "default": 5,
                                        },
                                        "contract_types": {
                                            "type": "string",
                                            "description": "逗号分隔的合同类型（可选）",
                                            "default": "",
                                        },
                                    },
                                    "required": ["files"],
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "成功，返回 batch_id"}},
                }
            },
            "/api/dify/batches/{batch_id}/status": {
                "get": {
                    "operationId": "getBatchStatus",
                    "summary": "查询抽取状态",
                    "description": "轮询批次状态。status=success/partial 表示完成，running 表示进行中。",
                    "parameters": [
                        {
                            "name": "batch_id",
                            "in": "path",
                            "required": True,
                            "description": "upload 返回的批次 ID",
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {"200": {"description": "OK"}},
                }
            },
            "/api/dify/batches/{batch_id}/rules.json": {
                "get": {
                    "operationId": "getBatchRules",
                    "summary": "获取抽取出的规则(JSON)",
                    "description": "完成后获取规则数组；运行中会返回 409。",
                    "parameters": [
                        {
                            "name": "batch_id",
                            "in": "path",
                            "required": True,
                            "description": "upload 返回的批次 ID",
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {"200": {"description": "OK"}},
                }
            },
        },
    }
    return JSONResponse(spec)
