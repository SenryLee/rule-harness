"""Config & profile routes."""
from __future__ import annotations

import yaml
from fastapi import APIRouter, HTTPException
from pathlib import Path

from ..config import (
    Config,
    PROJECT_ROOT,
    config_to_dict,
    load_config,
    save_config,
    _parse_config,
)

router = APIRouter(prefix="/api", tags=["config"])
PROFILES_DIR = PROJECT_ROOT / "profiles"


def _load_yaml(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError) as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read YAML: {exc}") from exc


def _deep_merge(base: dict, update: dict) -> None:
    for k, v in update.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def _strip_blank_api_keys(payload: dict) -> None:
    """剥离 payload 里为空的 api_key，避免覆盖已存的密钥。

    多个前端保存路径会回传整份 config；若某个组件在 key 尚未填充时保存，
    payload 会带 api_key=""，blind merge 就会把服务器上已配置的密钥清空
    （"每次更新后 key 丢失"的根因）。空值视为"不修改"，非空才更新。
    """
    models = payload.get("models")
    if not isinstance(models, dict):
        return
    for slot in ("primary", "fallback"):
        slot_cfg = models.get(slot)
        if isinstance(slot_cfg, dict) and not str(slot_cfg.get("api_key", "") or "").strip():
            slot_cfg.pop("api_key", None)


# ---- Config CRUD ----

@router.get("/config")
async def get_config():
    cfg = load_config()
    return config_to_dict(cfg)


@router.put("/config")
async def update_config(payload: dict):
    cfg = load_config()
    merged = config_to_dict(cfg)
    _strip_blank_api_keys(payload)
    _deep_merge(merged, payload)
    raw = yaml.safe_load(yaml.safe_dump(merged, allow_unicode=True))
    new_cfg = _parse_config(raw)
    save_config(new_cfg)
    return config_to_dict(new_cfg)


# ---- Profiles ----

@router.get("/profiles")
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


@router.get("/profiles/{name}")
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


@router.put("/profiles/{name}")
async def save_profile(name: str, payload: dict):
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


@router.delete("/profiles/{name}")
async def delete_profile(name: str):
    for ext in (".yaml", ".yml"):
        p = PROFILES_DIR / f"{name}{ext}"
        if p.exists():
            p.unlink()
            return {"name": name, "deleted": True}
    raise HTTPException(status_code=404, detail=f"Profile not found: {name}")
