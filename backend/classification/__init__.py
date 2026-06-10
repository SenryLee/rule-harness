"""统一分类词表加载（v1.2 批次④）。

classifier.py 的体裁预筛规则与 preview.py 的来源标签规则统一从
``taxonomy.yaml`` 加载——词表只维护一处。加载失败时调用方使用各自的
内置兜底词表（保持可运行）。
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

TAXONOMY_PATH = Path(__file__).resolve().parent / "taxonomy.yaml"


@lru_cache(maxsize=1)
def _load_taxonomy() -> dict[str, Any]:
    try:
        raw = yaml.safe_load(TAXONOMY_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    except Exception:
        logger.warning("taxonomy.yaml load failed, callers fall back to built-ins", exc_info=True)
    return {}


def load_genre_rules() -> list[dict[str, Any]] | None:
    """classifier 预筛规则。返回 None 表示加载失败（用内置兜底）。"""
    rules = _load_taxonomy().get("genre_rules")
    if not isinstance(rules, list) or not rules:
        return None
    out: list[dict[str, Any]] = []
    for rule in rules:
        item: dict[str, Any] = {
            "genre": str(rule.get("genre", "")),
            "filename_kw": tuple(rule.get("filename_kw") or ()),
            "body_kw": tuple(rule.get("body_kw") or ()),
            "weight": int(rule.get("weight", 1)),
        }
        if rule.get("anti_filename_kw"):
            item["anti_filename_kw"] = tuple(rule["anti_filename_kw"])
        if rule.get("suffixes"):
            item["suffixes"] = set(rule["suffixes"])
        out.append(item)
    return out


def load_source_rules() -> list[dict[str, Any]] | None:
    """preview 来源标签规则。返回 None 表示加载失败（用内置兜底）。"""
    rules = _load_taxonomy().get("source_rules")
    if not isinstance(rules, list) or not rules:
        return None
    return [
        {
            "label": str(rule.get("label", "")),
            "filename": tuple(rule.get("filename") or ()),
            "body": tuple(rule.get("body") or ()),
            "reason": str(rule.get("reason", "")),
        }
        for rule in rules
    ]
