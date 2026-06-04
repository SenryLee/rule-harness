"""Rule library & theme management routes."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, HTTPException, Query

from ..config import PROJECT_ROOT
from .. import state

router = APIRouter(prefix="/api", tags=["rules"])

_RISK_LEVELS = frozenset({"高", "中", "低"})
_RULE_TYPES = frozenset({"clause", "governance", "negative"})
_DEFAULT_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 1000


def _load_theme_keys() -> set[str]:
    path = PROJECT_ROOT / "theme_keys.yaml"
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError) as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read theme_keys: {exc}") from exc
    return set(raw.get("keys", []) or [])


# ---- Rule library ----

@router.get("/rules")
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
    for rules in state.batch_rules.values():
        all_rules.extend(rules)

    if risk_level:
        if risk_level not in _RISK_LEVELS:
            raise HTTPException(status_code=422, detail=f"Invalid risk_level: {risk_level}")
        all_rules = [r for r in all_rules if r.get("risk_level") == risk_level]
    if rule_type:
        if rule_type not in _RULE_TYPES:
            raise HTTPException(status_code=422, detail=f"Invalid rule_type: {rule_type}")
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


@router.put("/rules/{rule_id}/enabled")
async def toggle_rule_enabled(rule_id: str, payload: dict):
    enabled_val = payload.get("enabled")
    if not isinstance(enabled_val, bool):
        raise HTTPException(status_code=422, detail="Body must contain 'enabled' as boolean")
    want = "启用" if enabled_val else "停用"
    for rules in state.batch_rules.values():
        for r in rules:
            if r.get("rule_id") == rule_id:
                r["enabled"] = want
                return {"rule_id": rule_id, "enabled": enabled_val}
    raise HTTPException(status_code=404, detail=f"Rule not found: {rule_id}")


# ---- Themes ----

@router.get("/themes")
async def list_themes():
    return {"keys": sorted(_load_theme_keys())}


@router.get("/themes/pending")
async def list_pending_themes():
    whitelist = _load_theme_keys()
    pending: dict[str, list[dict]] = {}
    for rules in state.batch_rules.values():
        for r in rules:
            tk = r.get("theme_key", "")
            if tk and tk not in whitelist:
                pending.setdefault(tk, []).append(r)
    result = [
        {"theme_key": tk, "rule_count": len(rs), "sample_rule": rs[0] if rs else None}
        for tk, rs in pending.items()
    ]
    return sorted(result, key=lambda x: x["theme_key"])


@router.post("/themes/approve")
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
    for rules in state.batch_rules.values():
        for r in rules:
            current = r.get("theme_key", "")
            if current in mappings and mappings[current]:
                r["theme_key"] = mappings[current]
                updated += 1
    return {"updated": updated, "mappings": mappings}
