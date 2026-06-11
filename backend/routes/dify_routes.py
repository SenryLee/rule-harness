"""Dify 集成路由 — 文件上传 & JSON 导出。

本模块独立于已有 batch/rule 路由，专为对接 Dify 工作流设计：
  1. POST /api/dify/upload — 接收 Dify HTTP 节点传入的文件，创建批次并触发抽取
  2. GET  /api/dify/batches/{batch_id}/status — 轮询批次状态（供 Dify 轮询节点）
  3. GET  /api/dify/batches/{batch_id}/rules.json — 下载规则 JSON（供 Dify 后续节点消费）
  4. GET  /api/dify/batches/{batch_id}/wait — 服务端长轮询（v1.3，给 Dify 链式等待用）

后续直接在此文件扩展 Dify 相关接口即可，不影响已有路由。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import Query

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from ..config import PROJECT_ROOT, load_config
from ..orchestrator import (
    BatchProgress,
    BatchResult,
    candidate_to_api_dict,
    decision_to_api_dict,
    run_batch,
)
from .. import state
from .. import storage
from ..batch_persist import persist_finish
from .batch_routes import auto_batch_name

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dify", tags=["dify"])


def _persist_dify_create(batch_id: str) -> None:
    batch = state.batches.get(batch_id)
    if not batch:
        return
    try:
        storage.upsert_batch_fields(batch_id, {
            "started_at": batch.get("started_at"),
            "status": batch.get("status", "running"),
            "name": batch.get("name"),
            "file_metas": json.dumps(batch.get("file_metas") or [], ensure_ascii=False),
        })
    except Exception:
        logger.exception("persist dify batch create failed for %s", batch_id)

_UPLOAD_DIR = PROJECT_ROOT / "data" / "uploads"

# source_tag 的默认占位值：表示「Dify 没显式指定来源」，需要自动分类来补。
_DEFAULT_SOURCE_TAGS = frozenset({"dify", "", None})


async def _auto_classify_metas(batch_dir: Path, file_metas: list[dict], cfg) -> None:
    """对 Dify 传入的文件做自动分类，补齐 source_tag / is_redline / is_case。

    网页端上传会先走 /preview-classify 拿到正确来源标签，但 Dify 的 upload/extract
    之前直接写死 source_tag="dify"，导致所有文件都按「优先级5的通用文件」处理、管道
    路由全错。这里复用与网页端相同的分类器（有 api_key 时走 LLM，否则关键词兜底），
    只在用户未显式指定 source_tag 时覆盖。就地修改 file_metas。
    """
    from ..preview import extract_preview_text
    from ..classifier import classify_document, classify_document_sync

    router_obj = None
    try:
        if cfg.models.primary.api_key:
            from ..llm import create_llm_router

            router_obj = create_llm_router(cfg)
    except Exception:  # noqa: BLE001 — 分类是增强项，失败不应阻断抽取
        logger.debug("Dify 自动分类：LLM router 不可用，退回关键词分类")

    for meta in file_metas:
        if meta.get("source_tag") not in _DEFAULT_SOURCE_TAGS:
            continue  # 用户显式指定了来源，尊重之
        path = batch_dir / meta["filename"]
        try:
            content = path.read_bytes()
            text = extract_preview_text(meta.get("original_name") or path.name, content)
            name = meta.get("original_name") or path.name
            if router_obj is not None:
                clf = await classify_document(name, text, router=router_obj)
            else:
                clf = classify_document_sync(name, text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Dify 自动分类失败 %s: %s", meta.get("filename"), exc)
            continue
        meta["source_tag"] = clf.source_tag
        meta["is_redline"] = clf.is_redline
        meta["is_case"] = clf.is_case


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
    files: list[UploadFile] = File(default=[]),
    text: str = Form(default=""),
    source_tag: str = Form(default="dify"),
    priority: int = Form(default=5),
    contract_types: str = Form(default=""),
):
    """接收 Dify 传入的文件或文本，创建批次并**异步**抽取，立即返回 batch_id。

    异步：本接口在几百毫秒内返回 batch_id，抽取在后台进行，**不会被 Cloudflare 等
    网关的请求超时掐断**。后续用 /status 轮询、用 /rules.json 取结果（每次调用都很快）。

    两种传入方式（二选一）：
      - files —— multipart 文件（保真，走全部管道）
      - text  —— 纯文本（由 Dify「文档提取器」先抽好，绕开 HTTP 节点文件大小限制）

    其它表单字段：source_tag / priority / contract_types 均可选。
    """
    if not files and not text.strip():
        raise HTTPException(status_code=422, detail="需要提供 files 或 text 之一")

    batch_id = f"dify_{uuid.uuid4().hex[:10]}"
    batch_dir = _batch_dir(batch_id)
    batch_dir.mkdir(parents=True, exist_ok=True)

    ct_list = [t.strip() for t in contract_types.split(",") if t.strip()]

    saved_metas: list[dict] = []
    if files:
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
    else:
        safe_name = "000_dify_text.txt"
        (batch_dir / safe_name).write_text(text, encoding="utf-8")
        saved_metas.append({
            "filename": safe_name,
            "original_name": "dify_text.txt",
            "source_tag": source_tag,
            "priority": priority,
            "contract_types": ct_list,
        })

    now = _now_iso()
    state.batches[batch_id] = {
        "batch_id": batch_id,
        "name": f"[Dify] {auto_batch_name(saved_metas)}",
        "folder_id": "",
        "status": "running",
        "started_at": now,
        "finished_at": None,
        "total_files": len(saved_metas),
        "file_metas": saved_metas,
        "summary": {},
        "source": "dify",
    }
    state.batch_progress[batch_id] = BatchProgress(total_files=len(saved_metas))
    _persist_dify_create(batch_id)

    background_tasks.add_task(_run_dify_batch, batch_id, saved_metas)

    return {"batch_id": batch_id, "status": "running", "total_files": len(saved_metas)}


async def _run_dify_batch(batch_id: str, file_metas: list[dict]) -> None:
    """后台执行批次抽取（与 batch_routes 逻辑一致）。"""
    batch_dir = _batch_dir(batch_id)
    exports_dir = _exports_dir(batch_id)
    progress = state.batch_progress[batch_id]

    try:
        cfg = load_config()
        await _auto_classify_metas(batch_dir, file_metas, cfg)
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
    persist_finish(batch_id)


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
# 2.5 服务端长轮询 — Dify 1.13.3 无 loop/wait 节点 + Cloudflare ~100s 硬超时的解法
# ---------------------------------------------------------------------------

# 单次长轮询的最大阻塞秒数。必须明显小于 Cloudflare 的 ~100s 网关超时，
# 留出 TLS/排队余量。Dify 侧串 N 个 wait 节点即可接力等待 N*85 秒。
_WAIT_MAX_TIMEOUT = 85
_WAIT_POLL_INTERVAL = 2.0

_TERMINAL_STATUSES = frozenset({"success", "partial", "failed", "merged"})


@router.get("/batches/{batch_id}/wait")
async def dify_batch_wait(
    batch_id: str,
    timeout: int = Query(default=80, ge=0, le=_WAIT_MAX_TIMEOUT),
    include_rules: bool = Query(default=True),
):
    """阻塞至批次完成或 timeout 秒后返回（服务端长轮询）。

    设计动机：抽取任务常跑 3–5 分钟，而公网走 Cloudflare 有 ~100s 硬超时，
    同步接口必被掐断；Dify 1.13.3 又没有 loop/wait 节点没法在画布轮询。
    解法：把"等待"放进服务端——本接口单次最多阻塞 85 秒（CF 安全线内），
    Dify 工作流串联多个本接口的 HTTP 节点接力等待：
      - 批次已完成 → 秒回（后续接力节点几乎零成本）；
      - 批次运行中 → 阻塞到完成或超时，返回当前状态。

    返回：
      { batch_id, status, done, total_rules, summary,
        rules: [...]  # 仅 done 且 include_rules=true 时返回 }
    """
    batch = state.batches.get(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    deadline = time.monotonic() + timeout
    while (
        state.batches[batch_id]["status"] not in _TERMINAL_STATUSES
        and time.monotonic() < deadline
    ):
        await asyncio.sleep(_WAIT_POLL_INTERVAL)

    batch = state.batches[batch_id]
    status = batch["status"]
    done = status in _TERMINAL_STATUSES
    rules = state.batch_rules.get(batch_id, []) if done else []

    payload: dict = {
        "batch_id": batch_id,
        "status": status,
        "done": done,
        "total_rules": len(rules),
        "summary": batch.get("summary", {}),
        "finished_at": batch.get("finished_at"),
    }
    if done and include_rules:
        payload["rules"] = rules
    return payload


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
# 4. 同步抽取 — 一次调用完成「上传→抽取→返回规则」（供 Dify 工作流单节点调用）
# ---------------------------------------------------------------------------

@router.post("/extract")
async def dify_extract(
    files: list[UploadFile] = File(default=[]),
    text: str = Form(default=""),
    source_tag: str = Form(default="dify"),
    priority: int = Form(default=5),
    contract_types: str = Form(default=""),
):
    """同步抽取：阻塞到抽取完成，直接返回规则 JSON。

    与 /upload（异步、返回 batch_id）不同，本接口在一次 HTTP 请求内跑完整个
    抽取流程再返回，省去 Dify 侧的轮询/循环。适合在 Dify 1.13.3 工作流里用
    单个节点调用（无 loop 节点也能用）。

    两种传入方式（二选一）：
      1. files —— multipart 文件（保真，走 docx 批注/修订等全部管道）
      2. text  —— 纯文本（由 Dify document-extractor 先抽好文本再传，绕开
                  HTTP 节点的文件大小限制；仅走正文类管道）

    返回：{batch_id, status, total_rules, summary, rules}
    """
    if not files and not text.strip():
        raise HTTPException(status_code=422, detail="需要提供 files 或 text 之一")

    batch_id = f"difysync_{uuid.uuid4().hex[:10]}"
    batch_dir = _batch_dir(batch_id)
    exports_dir = _exports_dir(batch_id)
    batch_dir.mkdir(parents=True, exist_ok=True)

    ct_list = [t.strip() for t in contract_types.split(",") if t.strip()]

    file_metas: list[dict] = []
    if files:
        for idx, file in enumerate(files):
            safe_name = f"{idx:03d}_{file.filename or 'upload.bin'}"
            (batch_dir / safe_name).write_bytes(await file.read())
            file_metas.append({
                "filename": safe_name,
                "original_name": file.filename,
                "source_tag": source_tag,
                "priority": priority,
                "contract_types": ct_list,
            })
    else:
        safe_name = "000_dify_text.txt"
        (batch_dir / safe_name).write_text(text, encoding="utf-8")
        file_metas.append({
            "filename": safe_name,
            "original_name": "dify_text.txt",
            "source_tag": source_tag,
            "priority": priority,
            "contract_types": ct_list,
        })

    # 注册到共享状态，使该批次像网页端自己上传的任务一样出现在任务列表里，
    # 并可被网页端实时轮询进度 / 查看规则 / 删除 / 生成 Skill。
    # （单进程单 worker 下，网页端与本接口共享同一份 state。）
    now = _now_iso()
    progress = BatchProgress(total_files=len(file_metas))
    state.batches[batch_id] = {
        "batch_id": batch_id,
        "name": f"[Dify] {auto_batch_name(file_metas)}",
        "folder_id": "",
        "status": "running",
        "started_at": now,
        "finished_at": None,
        "total_files": len(file_metas),
        "file_metas": file_metas,
        "summary": {},
        "source": "dify",
    }
    state.batch_progress[batch_id] = progress
    _persist_dify_create(batch_id)

    try:
        cfg = load_config()
        await _auto_classify_metas(batch_dir, file_metas, cfg)
        result: BatchResult = await run_batch(
            batch_id=batch_id,
            file_metas=file_metas,
            batch_dir=batch_dir,
            exports_dir=exports_dir,
            cfg=cfg,
            progress=progress,
        )
    except Exception as exc:  # noqa: BLE001 — 把异常透传给 Dify 节点，同时让网页端看到失败状态
        logger.exception("Dify sync extract %s failed", batch_id)
        progress.errors.append(str(exc))
        progress.status = "partial"
        state.batches[batch_id]["status"] = "partial"
        state.batches[batch_id]["finished_at"] = _now_iso()
        persist_finish(batch_id)
        raise HTTPException(status_code=500, detail=f"抽取失败: {exc}") from exc

    rules = [candidate_to_api_dict(r) for r in result.rules]
    state.batch_rules[batch_id] = rules
    state.batch_decisions[batch_id] = [decision_to_api_dict(d) for d in result.decisions]
    state.batch_exports[batch_id] = result.exports
    state.batches[batch_id]["status"] = progress.status
    state.batches[batch_id]["finished_at"] = _now_iso()
    persist_finish(batch_id)
    state.batches[batch_id]["summary"] = result.summary

    return {
        "batch_id": batch_id,
        "status": progress.status,
        "total_rules": len(rules),
        "summary": result.summary,
        "rules": rules,
    }


# ---------------------------------------------------------------------------
# 5. Dify 自定义工具 Schema — 供 Dify「从 URL 中导入」一键创建工具
# ---------------------------------------------------------------------------

# 对外公网地址：Dify 会按此 URL 调用本服务。**部署后务必设环境变量 PUBLIC_BASE_URL
# 为新服务器的公网地址**（如 https://你的域名）。默认值仅为占位，避免再指向已废弃的 Render 实例。
_PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://api-rules.448898.xyz")


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
            "/api/dify/extract": {
                "post": {
                    "operationId": "extractSync",
                    "summary": "同步抽取（一次返回规则）",
                    "description": "阻塞到抽取完成，直接返回规则 JSON。传 files（保真）或 text（绕开文件大小限制）二选一。",
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
                                            "description": "要抽取规则的文件（与 text 二选一）",
                                        },
                                        "text": {
                                            "type": "string",
                                            "description": "已抽好的文本（与 files 二选一）",
                                        },
                                        "source_tag": {"type": "string", "default": "dify"},
                                        "priority": {"type": "integer", "default": 5},
                                        "contract_types": {"type": "string", "default": ""},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "成功，返回 rules 数组"}},
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
            "/api/dify/batches/{batch_id}/wait": {
                "get": {
                    "operationId": "waitBatch",
                    "summary": "长轮询等待抽取完成（≤85秒/次，Cloudflare 安全）",
                    "description": "阻塞至批次完成或 timeout 秒。完成时附带规则数组。Dify 工作流串联多个本接口节点即可接力等待数分钟的长任务。",
                    "parameters": [
                        {
                            "name": "batch_id",
                            "in": "path",
                            "required": True,
                            "description": "upload 返回的批次 ID",
                            "schema": {"type": "string"},
                        },
                        {
                            "name": "timeout",
                            "in": "query",
                            "required": False,
                            "description": "单次最大阻塞秒数（0-85，默认80）",
                            "schema": {"type": "integer", "default": 80},
                        },
                        {
                            "name": "include_rules",
                            "in": "query",
                            "required": False,
                            "description": "完成时是否附带规则数组（默认 true）",
                            "schema": {"type": "boolean", "default": True},
                        },
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
