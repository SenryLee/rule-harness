from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml

THEME_KEYS_PATH = Path(__file__).resolve().parent.parent / "theme_keys.yaml"

CONNECTORS = ["且", "和", "并", "同时", "以及", "并且"]
# v1.2：check_item 原子性判罚收窄到谓语级连接词。
# "和/以及/并"在名词并列（如"设计和施工资质"）里大量误伤合法规则。
STRICT_CONNECTORS = ["且", "并且", "同时"]
NUMERIC_RX = re.compile(r"\d+(?:\.\d+)?%?")
_NON_WORD_CJK_RX = re.compile(r"[^\w一-鿿㐀-䶿\U00020000-\U0002a6df]")

CONTRACT_TYPE_MAP: dict[str, str] = {
    "采购": "PUR",
    "销售": "SLS",
    "服务": "SVC",
    "保密": "NDA",
    "技术": "TEC",
    "许可": "LIC",
    "租赁": "LEA",
    "劳动": "LAB",
    "通用商事": "COM",
    "其他": "COM",
    "合规": "REG",
    "*": "ALL",
}

RULE_TYPE_MAP: dict[str, str] = {
    "clause": "C",
    "governance": "G",
    "negative": "N",
}


def load_theme_keys() -> set[str]:
    if not THEME_KEYS_PATH.exists():
        raise FileNotFoundError(
            f"Theme keys file not found at {THEME_KEYS_PATH}"
        )
    raw = yaml.safe_load(THEME_KEYS_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "keys" not in raw:
        raise ValueError(
            f"Theme keys file at {THEME_KEYS_PATH} missing top-level 'keys' list"
        )
    return set(raw["keys"])


THEME_KEYS: set[str] = load_theme_keys()


def normalize_text(text: str) -> str:
    return _NON_WORD_CJK_RX.sub("", text.casefold())


def compute_fingerprint(rule: dict) -> str:
    parts = [
        normalize_text(rule.get("theme_key", "")),
        normalize_text(rule.get("subject", "")),
        normalize_text(rule.get("predicate", "")),
        normalize_text(rule.get("threshold_type", "无") or "无"),
        normalize_text(rule.get("direction", "正向") or "正向"),
    ]
    concatenated = "|".join(parts)
    return hashlib.sha256(concatenated.encode()).hexdigest()[:6].upper()


def build_rule_id(rule: dict, contract_types: list[str] | None = None) -> str:
    primary_ct = contract_types[0] if contract_types else "通用商事"
    ct_code = CONTRACT_TYPE_MAP.get(primary_ct, "COM")
    rule_type = rule.get("rule_type", "clause")
    rt_code = RULE_TYPE_MAP.get(rule_type, "C")
    fp = compute_fingerprint(rule)
    return f"{ct_code}-{rt_code}-{fp}"


def validate_atomic(rule: dict) -> list[str]:
    failures: list[str] = []

    check_item = rule.get("check_item", "")
    requirement = rule.get("requirement", "")
    notes = rule.get("notes", "")
    theme_key = rule.get("theme_key", "")
    risk_level = rule.get("risk_level", "")
    keywords = rule.get("keywords", [])

    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",") if k.strip()]

    if len(check_item) > 40:
        failures.append("check_item_too_long")
    if len(requirement) > 200:
        failures.append("requirement_too_long")
    if len(notes) > 500:
        failures.append("notes_too_long")

    if any(c in check_item for c in STRICT_CONNECTORS):
        failures.append("check_item_not_atomic")

    # 多阈值检测：同一数字重复出现不算冲突；至少 2 个不同的数字 token 才视为多阈值。
    nums = NUMERIC_RX.findall(requirement)
    if len(set(nums)) >= 2:
        failures.append("requirement_multi_threshold")

    if not requirement.startswith(("[条款]", "[合规]")):
        failures.append("requirement_missing_type_tag")

    if theme_key not in THEME_KEYS:
        failures.append("theme_key_not_in_whitelist")

    if risk_level not in {"高", "中", "低"}:
        failures.append("invalid_risk_level")

    if not (1 <= len(keywords) <= 8):
        failures.append("keyword_count_out_of_range")

    return failures


def map_theme_key(raw_key: str) -> str:
    """把模型输出的 theme_key 就近映射到白名单（v1.2）。

    顺序：完全匹配 → 同前缀（前两段）白名单键 → 同一级前缀 → 原样返回。
    映射不上时不再直接 struct fail，由调用方决定如何标记。
    """
    key = (raw_key or "").strip()
    if not key or key in THEME_KEYS:
        return key

    segments = key.split(".")
    if len(segments) >= 2:
        prefix2 = ".".join(segments[:2]) + "."
        for candidate in sorted(THEME_KEYS):
            if candidate.startswith(prefix2):
                return candidate
    # 一级前缀兜底过于激进（会映射到语义无关的键），映射不上原样返回，
    # 由调用方降级为 uncertainty 而非 struct fail。
    return key


def keyword_appears_in_excerpt(keyword: str, excerpt: str) -> bool:
    if not keyword or not excerpt:
        return False
    return normalize_text(keyword) in normalize_text(excerpt)


# ---------------------------------------------------------------------------
# v1.1 - 第五重门（忠实度）
# ---------------------------------------------------------------------------

def validate_fidelity(rule: dict, source_excerpt: str) -> list[str]:
    """对一条规则做数值忠实度校验，返回不能 ground 的 token 列表（空=通过）。

    这是 v1.0 ``validate_atomic`` 的姊妹函数；调用方应同时调用两者。详见
    :mod:`backend.fidelity`。
    """
    from .fidelity import check_fidelity

    result = check_fidelity(
        requirement=rule.get("requirement", "") or "",
        check_item=rule.get("check_item", "") or "",
        notes=rule.get("notes", "") or "",
        source_excerpt=source_excerpt or "",
    )
    return list(result.failures)


def validate_voice(rule: dict, source_excerpt: str) -> list[str]:
    """语态忠实度校验。返回失败项列表（空=通过）。"""
    from .voice_check import check_voice_match

    return check_voice_match(
        source_excerpt=source_excerpt or "",
        requirement=rule.get("requirement", "") or "",
    )
