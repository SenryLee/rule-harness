"""任务级配置覆盖 + 任务预设的白名单/校验测试（v1.3）。"""
from __future__ import annotations

from backend.config import load_config
from backend.orchestrator import _apply_task_overrides
from backend.routes.config_routes import _sanitize_preset


def _cfg():
    return load_config()


def test_no_overrides_returns_same_config():
    cfg = _cfg()
    assert _apply_task_overrides(cfg, [{}]) is cfg


def test_top_level_granularity_override_still_works():
    cfg = _cfg()
    out = _apply_task_overrides(cfg, [{"granularity_level": 2}])
    assert out.extraction.granularity_level == 2
    assert out.extraction.granularity == "balanced"


def test_extraction_overrides_whitelist():
    cfg = _cfg()
    out = _apply_task_overrides(cfg, [{
        "extraction_overrides": {
            "granularity_level": 5,
            "regulation_depth": "limited",
            "consistency_sampling": True,
            "industry_vocabulary": "EPC\n总承包",
            "industry_focus_points": "工期索赔",
            "evil_key": "ignored",
        },
    }])
    assert out.extraction.granularity_level == 5
    assert out.extraction.granularity == "fine"
    assert out.extraction.regulation_depth == "limited"
    assert out.extraction.consistency_sampling is True
    assert out.extraction.industry_vocabulary == "EPC\n总承包"
    assert out.extraction.industry_focus_points == "工期索赔"
    assert not hasattr(out.extraction, "evil_key")


def test_invalid_override_values_are_ignored():
    cfg = _cfg()
    out = _apply_task_overrides(cfg, [{
        "granularity_level": "abc",
        "extraction_overrides": {
            "regulation_depth": "bogus",
            "consistency_sampling": "yes",  # 非 bool 忽略
            "industry_vocabulary": "   ",
        },
    }])
    assert out.extraction.regulation_depth == cfg.extraction.regulation_depth
    assert out.extraction.consistency_sampling == cfg.extraction.consistency_sampling
    assert out.extraction.industry_vocabulary == cfg.extraction.industry_vocabulary


def test_sanitize_preset_whitelist_and_clamp():
    cleaned = _sanitize_preset({
        "granularity_level": 99,
        "task_mode": "template_focused",
        "regulation_depth": "full",
        "our_party": "承包人",
        "api_key": "sk-should-not-pass",
        "random": 1,
    })
    assert cleaned["granularity_level"] == 5
    assert cleaned["task_mode"] == "template_focused"
    assert cleaned["our_party"] == "承包人"
    assert "api_key" not in cleaned
    assert "random" not in cleaned


def test_sanitize_preset_drops_invalid_enums():
    cleaned = _sanitize_preset({
        "task_mode": "hack_mode",
        "regulation_depth": "deepest",
        "scope_description": "只看付款条款",
    })
    assert "task_mode" not in cleaned
    assert "regulation_depth" not in cleaned
    assert cleaned["scope_description"] == "只看付款条款"
