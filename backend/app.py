"""
FastAPI application for the Rule Extraction Harness system.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml
from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.config import load_config, save_config, Config, config_to_dict, PROJECT_ROOT

app = FastAPI(title="规则梳理 Harness", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

PROFILES_DIR = PROJECT_ROOT / "profiles"

_batches: dict[str, dict] = {}
_batch_rules: dict[str, list[dict]] = {}
_batch_merge_decisions: dict[str, list[dict]] = {}
_batch_progress: dict[str, dict] = {}
_upload_dir = PROJECT_ROOT / "data" / "uploads"

_RISK_LEVELS = frozenset({"高", "中", "低"})
_RULE_TYPES = frozenset({"clause", "governance", "negative"})
_DEFAULT_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 200


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_yaml(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError) as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read YAML: {exc}")


def _validate_risk_level(level: str) -> None:
    if level not in _RISK_LEVELS:
        raise HTTPException(status_code=422, detail=f"Invalid risk_level: {level}")


def _validate_rule_type(rule_type: str) -> None:
    if rule_type not in _RULE_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid rule_type: {rule_type}")


def _load_theme_keys() -> set[str]:
    theme_yaml = PROJECT_ROOT / "theme_keys.yaml"
    raw = _load_yaml(theme_yaml)
    return set(raw.get("keys", []))


def _load_redline_keywords() -> list[str]:
    redline_yaml = PROJECT_ROOT / "redline_keywords.yaml"
    raw = _load_yaml(redline_yaml)
    return list(raw.get("keywords", []))


def _batch_dir(batch_id: str) -> Path:
    return _upload_dir / batch_id


def _exports_dir(batch_id: str) -> Path:
    return _batch_dir(batch_id) / "exports"


# =============================================================================
# Config Routes
# =============================================================================

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
    new_cfg = _parse_config_partial(raw, cfg)
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


# =============================================================================
# Batch Routes
# =============================================================================

@app.post("/api/batches")
async def create_batch(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    meta: str = Form(...),
):
    try:
        file_metas: list[dict] = json.loads(meta)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid meta JSON: {exc}")

    if len(files) != len(file_metas):
        raise HTTPException(
            status_code=422,
            detail=f"Files count ({len(files)}) must match meta count ({len(file_metas)})",
        )

    batch_id = uuid.uuid4().hex[:12]
    now = _now_iso()
    _batches[batch_id] = {
        "batch_id": batch_id,
        "status": "running",
        "started_at": now,
        "finished_at": None,
        "total_files": len(files),
        "file_metas": [],
        "summary": {},
    }
    _batch_progress[batch_id] = {
        "status": "running",
        "current_step": "uploading",
        "total_files": len(files),
        "processed_files": 0,
        "total_blocks": 0,
        "processed_blocks": 0,
        "total_rules": 0,
        "tokens_used": 0,
        "errors": [],
    }

    batch_dir = _batch_dir(batch_id)
    batch_dir.mkdir(parents=True, exist_ok=True)

    saved_metas = []
    for idx, (file, meta_item) in enumerate(zip(files, file_metas)):
        safe_name = f"{idx:03d}_{file.filename or 'upload.bin'}"
        dest = batch_dir / safe_name
        content = await file.read()
        dest.write_bytes(content)
        saved_metas.append({**meta_item, "filename": safe_name, "original_name": file.filename})

    _batches[batch_id]["file_metas"] = saved_metas

    background_tasks.add_task(_process_batch, batch_id, saved_metas)
    return {"batch_id": batch_id, "status": "running"}


@app.get("/api/batches")
async def list_batches():
    result = []
    for b in sorted(_batches.values(), key=lambda x: x["started_at"], reverse=True):
        result.append({
            "batch_id": b["batch_id"],
            "status": b["status"],
            "started_at": b["started_at"],
            "finished_at": b.get("finished_at"),
            "total_files": b["total_files"],
        })
    return result


@app.get("/api/batches/{batch_id}")
async def get_batch(batch_id: str):
    batch = _batches.get(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    rules = _batch_rules.get(batch_id, [])
    summary = {
        "total_rules": len(rules),
        "by_risk": {"高": 0, "中": 0, "低": 0},
        "by_pipeline": {},
        "by_type": {},
        "conflicts": sum(1 for r in rules if r.get("has_conflict")),
    }
    for r in rules:
        summary["by_risk"][r.get("risk_level", "中")] += 1
        pipeline = r.get("pipeline", "unknown")
        summary["by_pipeline"][pipeline] = summary["by_pipeline"].get(pipeline, 0) + 1
        rtype = r.get("rule_type", "clause")
        summary["by_type"][rtype] = summary["by_type"].get(rtype, 0) + 1

    return {**batch, "summary": summary}


@app.get("/api/batches/{batch_id}/progress")
async def get_batch_progress(batch_id: str):
    batch = _batches.get(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    progress = _batch_progress.get(batch_id, {})
    rules = _batch_rules.get(batch_id, [])
    progress["total_rules"] = len(rules)
    return progress


@app.get("/api/batches/{batch_id}/rules")
async def list_batch_rules(
    batch_id: str,
    risk_level: Optional[str] = Query(None),
    pipeline: Optional[str] = Query(None),
    confidence_min: Optional[float] = Query(None),
    confidence_max: Optional[float] = Query(None),
    conflict_flag: Optional[bool] = Query(None),
    contract_type: Optional[str] = Query(None),
    source_file: Optional[str] = Query(None),
):
    if batch_id not in _batches:
        raise HTTPException(status_code=404, detail="Batch not found")

    rules = _batch_rules.get(batch_id, [])

    if risk_level:
        _validate_risk_level(risk_level)
        rules = [r for r in rules if r.get("risk_level") == risk_level]
    if pipeline:
        rules = [r for r in rules if r.get("pipeline") == pipeline]
    if confidence_min is not None:
        rules = [r for r in rules if r.get("confidence", 0) >= confidence_min]
    if confidence_max is not None:
        rules = [r for r in rules if r.get("confidence", 0) <= confidence_max]
    if conflict_flag is not None:
        rules = [r for r in rules if r.get("has_conflict", False) == conflict_flag]
    if contract_type:
        rules = [
            r for r in rules
            if contract_type in (r.get("contract_types") or [])
        ]
    if source_file:
        rules = [r for r in rules if r.get("source_file") == source_file]

    return {"rules": rules, "total": len(rules), "page": 1, "page_size": len(rules)}


@app.get("/api/batches/{batch_id}/exports/main-csv")
async def export_main_csv(batch_id: str):
    if batch_id not in _batches:
        raise HTTPException(status_code=404, detail="Batch not found")
    path = _exports_dir(batch_id) / "main.csv"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Export not yet generated")
    return FileResponse(path, media_type="text/csv", filename=f"{batch_id}_main.csv")


@app.get("/api/batches/{batch_id}/exports/metadata-csv")
async def export_metadata_csv(batch_id: str):
    if batch_id not in _batches:
        raise HTTPException(status_code=404, detail="Batch not found")
    path = _exports_dir(batch_id) / "metadata.csv"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Export not yet generated")
    return FileResponse(path, media_type="text/csv", filename=f"{batch_id}_metadata.csv")


@app.get("/api/batches/{batch_id}/exports/conflict-report")
async def export_conflict_report(batch_id: str):
    if batch_id not in _batches:
        raise HTTPException(status_code=404, detail="Batch not found")
    path = _exports_dir(batch_id) / "conflict_report.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Export not yet generated")
    return FileResponse(path, media_type="text/html", filename=f"{batch_id}_conflicts.html")


@app.get("/api/batches/{batch_id}/exports/change-set")
async def export_change_set(batch_id: str):
    if batch_id not in _batches:
        raise HTTPException(status_code=404, detail="Batch not found")
    path = _exports_dir(batch_id) / "change_set.csv"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Change set not available for this batch")
    return FileResponse(path, media_type="text/csv", filename=f"{batch_id}_changes.csv")


@app.post("/api/batches/{batch_id}/apply")
async def apply_batch(batch_id: str):
    if batch_id not in _batches:
        raise HTTPException(status_code=404, detail="Batch not found")
    batch = _batches[batch_id]
    if batch["status"] != "success":
        raise HTTPException(status_code=409, detail="Can only apply completed batches")

    decisions = _batch_merge_decisions.get(batch_id, [])
    if not decisions:
        raise HTTPException(status_code=409, detail="No merge decisions available for this batch")

    applied = 0
    skipped = 0
    for decision in decisions:
        if decision.get("action") == "apply":
            applied += 1
        else:
            skipped += 1

    batch["status"] = "merged"
    return {"applied": applied, "skipped": skipped, "total": len(decisions)}


# =============================================================================
# Rule Library Routes
# =============================================================================

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
        all_rules = [
            r for r in all_rules
            if contract_type in (r.get("contract_types") or [])
        ]
    if enabled is not None:
        all_rules = [r for r in all_rules if r.get("enabled", True) == enabled]
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

    return {
        "rules": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@app.put("/api/rules/{rule_id}/enabled")
async def toggle_rule_enabled(rule_id: str, payload: dict):
    enabled_val = payload.get("enabled")
    if not isinstance(enabled_val, bool):
        raise HTTPException(status_code=422, detail="Body must contain 'enabled' as boolean")

    for rules in _batch_rules.values():
        for r in rules:
            if r.get("rule_id") == rule_id:
                r["enabled"] = enabled_val
                return {"rule_id": rule_id, "enabled": enabled_val}

    raise HTTPException(status_code=404, detail=f"Rule not found: {rule_id}")


# =============================================================================
# Theme Routes
# =============================================================================

@app.get("/api/themes")
async def list_themes():
    return {"keys": sorted(_load_theme_keys())}


@app.get("/api/themes/pending")
async def list_pending_themes():
    whitelist = _load_theme_keys()
    all_rules: list[dict] = []
    for rules in _batch_rules.values():
        all_rules.extend(rules)

    pending: dict[str, list[dict]] = {}
    for r in all_rules:
        tk = r.get("theme_key", "")
        if tk and tk not in whitelist:
            pending.setdefault(tk, []).append(r)

    result = []
    for tk, rules in pending.items():
        result.append({
            "theme_key": tk,
            "rule_count": len(rules),
            "sample_rule": rules[0] if rules else None,
        })
    return sorted(result, key=lambda x: x["theme_key"])


@app.post("/api/themes/approve")
async def approve_themes(payload: dict):
    mappings = payload.get("mappings")
    if not isinstance(mappings, dict):
        raise HTTPException(status_code=422, detail="Body must contain 'mappings' as dict")

    whitelist = _load_theme_keys()
    theme_yaml = PROJECT_ROOT / "theme_keys.yaml"

    for pending_key, approved_key in mappings.items():
        if approved_key and approved_key not in whitelist:
            raise HTTPException(
                status_code=422,
                detail=f"Approved key '{approved_key}' is not in the theme whitelist",
            )

    all_rules: list[dict] = []
    for rules in _batch_rules.values():
        all_rules.extend(rules)

    updated = 0
    for r in all_rules:
        current = r.get("theme_key", "")
        if current in mappings:
            new_key = mappings[current]
            if new_key:
                r["theme_key"] = new_key
                updated += 1

    return {"updated": updated, "mappings": mappings}


# =============================================================================
# Background Batch Processing
# =============================================================================

async def _process_batch(batch_id: str, file_metas: list[dict]):
    batch_dir = _batch_dir(batch_id)
    exports_dir = _exports_dir(batch_id)
    exports_dir.mkdir(parents=True, exist_ok=True)
    progress = _batch_progress[batch_id]

    try:
        _update_progress(progress, "parsing", processed_files=0, processed_blocks=0)
        docs = await _parse_files(batch_id, file_metas, batch_dir, progress)

        _update_progress(progress, "extracting", processed_blocks=0)
        all_candidates = await _extract_rules(docs, progress)

        _update_progress(progress, "deduping")
        deduped = _deduplicate_rules(all_candidates)

        _update_progress(progress, "scoring")
        scored = _score_rules(deduped)

        _update_progress(progress, "identifying")
        final_rules = _assign_rule_ids(scored, file_metas)

        _update_progress(progress, "merging")
        merge_decisions = _generate_merge_decisions(final_rules)
        _batch_merge_decisions[batch_id] = merge_decisions

        _update_progress(progress, "exporting")
        _generate_exports(final_rules, merge_decisions, exports_dir)

        _batch_rules[batch_id] = final_rules
        _batches[batch_id]["status"] = "success"
        _batches[batch_id]["finished_at"] = _now_iso()
        progress["status"] = "success"
        progress["total_rules"] = len(final_rules)

    except Exception as exc:
        _batches[batch_id]["status"] = "partial"
        _batches[batch_id]["finished_at"] = _now_iso()
        progress["status"] = "partial"
        progress["errors"].append(str(exc))


def _update_progress(progress: dict, step: str, **kwargs):
    progress["current_step"] = step
    for k, v in kwargs.items():
        progress[k] = v


async def _parse_files(batch_id: str, file_metas: list[dict], batch_dir: Path, progress: dict) -> list[dict]:
    sem = asyncio.Semaphore(4)

    async def parse_one(idx: int, meta: dict) -> dict:
        async with sem:
            filepath = batch_dir / meta["filename"]
            contract_types = meta.get("contract_types", [])
            source_tag = meta.get("source_tag", "历史合同")
            is_scanned = meta.get("is_scanned", False)
            is_redline = meta.get("is_redline", False)
            is_case = meta.get("is_case", False)
            jurisdiction = meta.get("jurisdiction", "中国大陆")

            try:
                text = filepath.read_text(encoding="utf-8-sig", errors="replace")
            except Exception:
                text = filepath.read_bytes().decode("utf-8", errors="replace")

            blocks = _split_into_blocks(text)
            doc = {
                "source_file": meta.get("original_name", filepath.name),
                "filename": meta["filename"],
                "source_tag": source_tag,
                "contract_types": contract_types,
                "is_scanned": is_scanned,
                "is_redline": is_redline,
                "is_case": is_case,
                "jurisdiction": jurisdiction,
                "blocks": blocks,
            }
            progress["processed_files"] = idx + 1
            progress["total_blocks"] += len(blocks)
            return doc

    tasks = [parse_one(i, meta) for i, meta in enumerate(file_metas)]
    return await asyncio.gather(*tasks)


async def _extract_rules(docs: list[dict], progress: dict) -> list[dict]:
    sem = asyncio.Semaphore(8)
    cfg = load_config()
    redline_keywords = _load_redline_keywords()
    theme_keys_set = _load_theme_keys()
    theme_keys_str = "\n".join(sorted(theme_keys_set))
    redline_str = "\n".join(redline_keywords)

    async def extract_block(doc: dict, block: dict, block_idx: int) -> list[dict]:
        async with sem:
            is_case = doc.get("is_case", False)
            if is_case:
                return _extract_case_rules(block, doc, redline_str, theme_keys_str)
            return _extract_body_rules(block, doc, redline_str, theme_keys_str, block_idx)

    all_tasks = []
    for doc in docs:
        for i, block in enumerate(doc.get("blocks", [])):
            all_tasks.append(extract_block(doc, block, i))

    results = await asyncio.gather(*all_tasks)
    all_candidates = []
    for result in results:
        all_candidates.extend(result)
        progress["processed_blocks"] += 1

    return all_candidates


def _extract_body_rules(block: dict, doc: dict, redline_str: str, theme_keys_str: str, block_idx: int) -> list[dict]:
    candidates = []
    text = block.get("text", "")
    if not text.strip() or len(text.strip()) < 10:
        return candidates

    patterns = [
        ("违约金", "payment.late_fee.cap_ratio", "clause"),
        ("保密", "confidentiality.term.duration", "clause"),
        ("知识产权", "ip.ownership.foreground", "clause"),
        ("赔偿", "liability.damages.direct", "clause"),
        ("争议", "dispute.arbitration.institution", "clause"),
        ("付款", "payment.term.days", "clause"),
        ("发票", "payment.invoice.requirement", "clause"),
        ("生效", "counterpart.effective_date.condition", "clause"),
        ("管辖", "dispute.jurisdiction.exclusive", "clause"),
        ("适用.*法律", "dispute.governing_law.choice", "clause"),
    ]

    import re
    for pattern, theme_key, rule_type in patterns:
        if not re.search(pattern, text):
            continue
        candidate = _build_rule_candidate(text, theme_key, rule_type, doc, block, block_idx)
        candidates.append(candidate)

    return candidates


def _extract_case_rules(block: dict, doc: dict, redline_str: str, theme_keys_str: str) -> list[dict]:
    import re
    candidates = []
    text = block.get("text", "")

    case_patterns = [
        (r"最终解释权", "format_clause.invalid_final_interpretation", "最终解释权"),
        (r"概不退换", "format_clause.invalid_no_return", "概不退换"),
        (r"过高.*违约金|违约金.*过高", "format_clause.invalid_excessive_liquidated_damages", "过高违约金"),
        (r"免除.*责任|责任.*免除", "format_clause.invalid_exempt_all_liability", "免除责任"),
        (r"单方.*修改|单方.*变更|修改.*单方", "format_clause.invalid_unilateral_modification", "单方修改"),
    ]

    for pattern, theme_key, label in case_patterns:
        if not re.search(pattern, text):
            continue
        candidate = _build_rule_candidate(text, theme_key, "negative", doc, block, 0)
        candidate["notes"] = f"案例引用: {doc.get('source_file', '')} - {label}"
        candidates.append(candidate)

    return candidates


def _build_rule_candidate(text: str, theme_key: str, rule_type: str, doc: dict, block: dict, block_idx: int) -> dict:
    import hashlib, re

    excerpt = text[:200].replace("\n", " ")
    keywords = _extract_keywords_from_text(text, theme_key)
    risk_level = _compute_risk(text, rule_type)

    if rule_type == "negative":
        requirement = f"[条款] 禁止使用'{theme_key.split('.')[-1]}'类表述"
    elif rule_type == "governance":
        requirement = f"[合规] {excerpt[:80]}"
    else:
        requirement = f"[条款] {excerpt[:80]}"

    return {
        "check_item": excerpt[:30],
        "requirement": requirement,
        "notes": "",
        "risk_level": risk_level,
        "keywords": keywords,
        "theme_key": theme_key,
        "rule_type": rule_type,
        "source_file": doc.get("source_file", ""),
        "source_tag": doc.get("source_tag", ""),
        "contract_types": doc.get("contract_types", []),
        "jurisdiction": doc.get("jurisdiction", "中国大陆"),
        "pipeline": "P5" if rule_type == "negative" else "P1",
        "block_index": block_idx,
        "excerpt": excerpt,
        "subject": _extract_subject(text, theme_key),
        "predicate": _extract_predicate(text, theme_key),
        "threshold_type": _extract_threshold_type(theme_key),
        "direction": "反向" if rule_type == "negative" else "正向",
        "self_confidence": 0.85,
        "uncertainty_points": [],
        "fingerprint": hashlib.sha256(
            f"{theme_key}:{excerpt[:50]}".encode()
        ).hexdigest()[:12],
        "enabled": True,
        "has_conflict": False,
    }


def _extract_keywords_from_text(text: str, theme_key: str) -> list[str]:
    parts = theme_key.split(".")
    candidates = set()
    for part in parts:
        if part not in {"format_clause", "invalid", "dispute", "payment", "confidentiality",
                         "ip", "liability", "compliance", "breach", "delivery", "warranty",
                         "termination", "insurance", "force_majeure", "assignment", "notice",
                         "amendment", "entire_agreement", "counterpart", "employment",
                         "data_privacy", "tax", "environment", "third_party", "audit",
                         "exclusivity", "most_favored_nation", "non_compete", "severability",
                         "renewal", "scope_of_work"}:
            candidates.add(part)

    result = list(candidates)[:6]
    if len(result) < 3:
        result.append(theme_key.replace(".", ""))
    return result


def _compute_risk(text: str, rule_type: str) -> str:
    redline_keywords = _load_redline_keywords()
    text_lower = text
    for kw in redline_keywords:
        if kw in text_lower:
            return "高"
    if rule_type == "negative":
        return "高"
    for kw in ["应当", "不得", "禁止", "必须"]:
        if kw in text_lower:
            return "高"
    return "中"


def _extract_subject(text: str, theme_key: str) -> str:
    if "买方" in text:
        return "买方"
    if "卖方" in text:
        return "卖方"
    if "双方" in text:
        return "双方"
    return "合同方"


def _extract_predicate(text: str, theme_key: str) -> str:
    if "不得" in text:
        return "不得"
    if "应当" in text:
        return "应当"
    if "禁止" in text:
        return "禁止"
    return "应满足"


def _extract_threshold_type(theme_key: str) -> str:
    if "days" in theme_key or "duration" in theme_key or "period" in theme_key:
        return "期限"
    if "ratio" in theme_key or "rate" in theme_key or "cap" in theme_key:
        return "比例"
    if "amount" in theme_key or "fee" in theme_key or "price" in theme_key:
        return "金额"
    return "无"


def _split_into_blocks(text: str, max_chars: int = 2000) -> list[dict]:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    blocks = []
    for i, para in enumerate(paragraphs):
        if len(para) > max_chars:
            for j in range(0, len(para), max_chars):
                blocks.append({
                    "text": para[j:j + max_chars],
                    "location": f"段落{i+1}.{j//max_chars+1}",
                })
        else:
            blocks.append({"text": para, "location": f"段落{i+1}"})
    return blocks


def _deduplicate_rules(candidates: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for rule in candidates:
        fp = rule.get("fingerprint", "")
        if not fp:
            continue
        if fp in seen:
            existing = seen[fp]
            existing_pipeline = existing.get("pipeline", "")
            new_pipeline = rule.get("pipeline", "")
            if new_pipeline < existing_pipeline:
                seen[fp] = rule
        else:
            seen[fp] = rule
    return list(seen.values())


def _score_rules(rules: list[dict]) -> list[dict]:
    for r in rules:
        base = r.get("self_confidence", 0.85)
        r["confidence"] = round(base, 2)
    return rules


def _assign_rule_ids(rules: list[dict], file_metas: list[dict]) -> list[dict]:
    import hashlib

    all_cts: set[str] = set()
    for meta in file_metas:
        for ct in meta.get("contract_types", []):
            all_cts.add(ct)

    type_map = {"采购": "PUR", "服务": "SVC", "销售": "SAL", "租赁": "LEA",
                "合作": "COP", "许可": "LIC", "通用商事": "COM", "劳动": "EMP"}
    abbrev_map = {"clause": "C", "governance": "G", "negative": "N"}

    for r in rules:
        cts = r.get("contract_types", [])
        prefix = "ALL"
        for ct in cts:
            mapped = type_map.get(ct)
            if mapped:
                prefix = mapped
                break
        abbrev = abbrev_map.get(r.get("rule_type", "clause"), "C")
        fp = r.get("fingerprint", "")[:6].upper()
        r["rule_id"] = f"{prefix}-{abbrev}-{fp}"

    return rules


def _generate_merge_decisions(rules: list[dict]) -> list[dict]:
    decisions = []
    for r in rules:
        decisions.append({
            "rule_id": r.get("rule_id", ""),
            "action": "apply",
            "reason": "new",
            "fingerprint": r.get("fingerprint", ""),
            "check_item": r.get("check_item", ""),
        })
    return decisions


def _generate_exports(rules: list[dict], decisions: list[dict], exports_dir: Path):
    import csv

    main_path = exports_dir / "main.csv"
    fieldnames = [
        "rule_id", "rule_type", "theme_key", "risk_level", "check_item",
        "requirement", "notes", "keywords", "subject", "predicate",
        "threshold_type", "direction", "confidence", "source_file",
        "source_tag", "pipeline", "has_conflict",
    ]
    with open(main_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in rules:
            row = dict(r)
            row["keywords"] = "|".join(r.get("keywords", []))
            row["contract_types"] = "|".join(r.get("contract_types", []))
            writer.writerow(row)

    meta_path = exports_dir / "metadata.csv"
    meta_fields = [
        "rule_id", "fingerprint", "pipeline", "block_index", "self_confidence",
        "uncertainty_points", "jurisdiction",
    ]
    with open(meta_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=meta_fields, extrasaction="ignore")
        writer.writeheader()
        for r in rules:
            row = dict(r)
            row["uncertainty_points"] = "|".join(r.get("uncertainty_points", []))
            writer.writerow(row)

    conflict_path = exports_dir / "conflict_report.html"
    conflict_rules = [r for r in rules if r.get("has_conflict")]
    html = _build_conflict_html(conflict_rules)
    conflict_path.write_text(html, encoding="utf-8")

    change_path = exports_dir / "change_set.csv"
    change_fields = ["rule_id", "action", "reason", "fingerprint", "check_item"]
    with open(change_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=change_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(decisions)


def _build_conflict_html(conflict_rules: list[dict]) -> str:
    rows = ""
    for r in conflict_rules:
        rows += (
            f"<tr><td>{r.get('rule_id','')}</td>"
            f"<td>{r.get('check_item','')}</td>"
            f"<td>{r.get('risk_level','')}</td>"
            f"<td>{r.get('theme_key','')}</td></tr>\n"
        )
    return (
        "<!DOCTYPE html>\n<html><head><meta charset='utf-8'>"
        "<title>冲突报告</title>"
        "<style>body{font-family:sans-serif;margin:2em}"
        "table{border-collapse:collapse;width:100%}"
        "th,td{border:1px solid #ddd;padding:8px;text-align:left}"
        "th{background:#f5f5f5}</style></head>"
        f"<body><h1>冲突规则报告</h1><p>共 {len(conflict_rules)} 条冲突规则</p>"
        "<table><tr><th>规则ID</th><th>检查项</th><th>风险等级</th><th>主题</th></tr>"
        f"{rows}</table></body></html>"
    )


def _deep_merge(base: dict, update: dict):
    for k, v in update.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def _parse_config_partial(raw: dict, existing: Config) -> Config:
    from dataclasses import replace

    cfg = existing

    if "models" in raw:
        models_raw = raw["models"]
        if "primary" in models_raw:
            p = models_raw["primary"]
            primary = replace(cfg.models.primary,
                provider=p.get("provider", cfg.models.primary.provider),
                api_key=p.get("api_key", cfg.models.primary.api_key),
                base_url=p.get("base_url", cfg.models.primary.base_url),
                model=p.get("model", cfg.models.primary.model),
                rpm_limit=p.get("rpm_limit", cfg.models.primary.rpm_limit),
                tpm_limit=p.get("tpm_limit", cfg.models.primary.tpm_limit),
            )
            cfg = replace(cfg, models=replace(cfg.models, primary=primary))
        if "fallback" in models_raw:
            f = models_raw["fallback"]
            fallback = replace(cfg.models.fallback,
                provider=f.get("provider", cfg.models.fallback.provider),
                api_key=f.get("api_key", cfg.models.fallback.api_key),
                base_url=f.get("base_url", cfg.models.fallback.base_url),
                model=f.get("model", cfg.models.fallback.model),
                rpm_limit=f.get("rpm_limit", cfg.models.fallback.rpm_limit),
                tpm_limit=f.get("tpm_limit", cfg.models.fallback.tpm_limit),
            )
            cfg = replace(cfg, models=replace(cfg.models, fallback=fallback))

    return cfg


# =============================================================================
# Static Files & Startup
# =============================================================================

frontend_dir = PROJECT_ROOT / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")


def main():
    import uvicorn, subprocess, signal, sys, os
    frontend_dir = str(Path(__file__).parent.parent / "frontend")
    npm = subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=frontend_dir,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        preexec_fn=os.setpgrp,
    )

    def cleanup(*_):
        npm.terminate()
        npm.wait(timeout=5)
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    print(f"\n  后端: http://localhost:8765")
    print(f"  前端: http://localhost:5199\n")
    uvicorn.run("backend.app:app", host="0.0.0.0", port=8765, reload=False)


if __name__ == "__main__":
    main()
