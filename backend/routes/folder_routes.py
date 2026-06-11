"""v1.4 项目归档文件夹 + 跨任务手动合并去重路由。

「规则库」页面的替代品：用户按企业/项目建文件夹，把任务归档进去；
在文件夹里勾选多个任务手动「合并规则」，两级去重后存档，可分页查看与导出。
"""
from __future__ import annotations

import json
import logging
import uuid
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from .. import state
from .. import storage
from ..export_dicts import LOCATED_COLUMNS, TEMPLATE_COLUMNS, rules_to_csv
from ..folder_merge import merge_rules_across_batches
from .batch_routes import get_batch_rules_cached

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["folders"])


# ---- Folder CRUD ----

@router.get("/folders")
async def list_folders():
    return storage.list_folders()


@router.post("/folders")
async def create_folder(payload: dict):
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="文件夹名不能为空")
    if len(name) > 50:
        name = name[:50]
    folder_id = uuid.uuid4().hex[:10]
    storage.insert_folder(folder_id, name)
    return {"folder_id": folder_id, "name": name}


@router.patch("/folders/{folder_id}")
async def rename_folder(folder_id: str, payload: dict):
    if storage.get_folder(folder_id) is None:
        raise HTTPException(status_code=404, detail="Folder not found")
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="文件夹名不能为空")
    storage.rename_folder(folder_id, name[:50])
    return {"folder_id": folder_id, "name": name[:50]}


@router.delete("/folders/{folder_id}")
async def delete_folder(folder_id: str):
    if storage.get_folder(folder_id) is None:
        raise HTTPException(status_code=404, detail="Folder not found")
    storage.delete_folder(folder_id)
    # 同步内存态：该文件夹下任务移回未归档
    for batch in state.batches.values():
        if batch.get("folder_id") == folder_id:
            batch["folder_id"] = ""
    return {"folder_id": folder_id, "deleted": True}


# ---- 跨任务合并去重 ----

@router.post("/folders/{folder_id}/merge")
async def merge_folder_batches(folder_id: str, payload: dict):
    """payload: {batch_ids: [...], name?: str, main_only?: bool}"""
    folder = storage.get_folder(folder_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found")

    batch_ids = [str(b) for b in (payload.get("batch_ids") or []) if b]
    if len(batch_ids) < 2:
        raise HTTPException(status_code=422, detail="至少勾选 2 个任务才能合并")

    rules_by_batch: dict[str, list[dict]] = {}
    for batch_id in batch_ids:
        if batch_id not in state.batches:
            raise HTTPException(status_code=404, detail=f"Batch not found: {batch_id}")
        rules = get_batch_rules_cached(batch_id)
        if not rules:
            raise HTTPException(
                status_code=409,
                detail=f"任务 {state.batches[batch_id].get('name') or batch_id} 没有可合并的规则",
            )
        rules_by_batch[batch_id] = rules

    merged, stats = merge_rules_across_batches(
        rules_by_batch, main_only=bool(payload.get("main_only", True))
    )

    merge_id = uuid.uuid4().hex[:12]
    batch_names = [
        state.batches[b].get("name") or b for b in batch_ids
    ]
    name = str(payload.get("name") or "").strip() or f"合并 {len(batch_ids)} 个任务"
    stats["batch_names"] = batch_names
    storage.insert_folder_merge({
        "merge_id": merge_id,
        "folder_id": folder_id,
        "name": name[:60],
        "batch_ids": batch_ids,
        "rules": merged,
        "stats": stats,
    })
    return {"merge_id": merge_id, "name": name[:60], "stats": stats}


@router.get("/folders/{folder_id}/merges")
async def list_folder_merges(folder_id: str):
    if storage.get_folder(folder_id) is None:
        raise HTTPException(status_code=404, detail="Folder not found")
    return storage.list_folder_merges(folder_id)


@router.get("/merges/{merge_id}")
async def get_merge(
    merge_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    merge = storage.get_folder_merge(merge_id)
    if merge is None:
        raise HTTPException(status_code=404, detail="Merge not found")
    rules = merge.pop("rules", [])
    total = len(rules)
    start = (page - 1) * page_size
    merge["rules"] = rules[start:start + page_size]
    merge["total"] = total
    merge["page"] = page
    merge["page_size"] = page_size
    return merge


@router.delete("/merges/{merge_id}")
async def delete_merge(merge_id: str):
    if storage.get_folder_merge(merge_id) is None:
        raise HTTPException(status_code=404, detail="Merge not found")
    storage.delete_folder_merge(merge_id)
    return {"merge_id": merge_id, "deleted": True}


@router.get("/merges/{merge_id}/export")
async def export_merge(merge_id: str, kind: str = Query("template")):
    merge = storage.get_folder_merge(merge_id)
    if merge is None:
        raise HTTPException(status_code=404, detail="Merge not found")
    columns = LOCATED_COLUMNS if kind == "located" else TEMPLATE_COLUMNS
    csv_text = rules_to_csv(merge.get("rules", []), columns)
    filename = f"{merge.get('name') or merge_id}_{kind}.csv"
    return Response(
        content="\ufeff" + csv_text,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        },
    )
