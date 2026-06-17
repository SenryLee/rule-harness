"""api_key 安全防护测试。

安全策略：前端永远不接触明文 key，key 只通过服务器环境变量
（DASHSCOPE_API_KEY / RULE_HARNESS_API_KEY）或服务器本地
data/config.yaml 配置。PUT /api/config 无条件丢弃前端传来的 api_key。

覆盖：
  1. _strip_all_api_keys：前端传来的 api_key 不管空不空一律剥离；
  2. _parse_model 环境变量兜底：config.yaml 留空时从 env 读取。
"""
from __future__ import annotations

import os

from backend.config import _parse_model
from backend.routes.config_routes import _strip_all_api_keys


def test_blank_api_key_is_stripped_from_payload():
    payload = {"models": {"primary": {"api_key": "", "rpm_limit": 120}}}
    _strip_all_api_keys(payload)
    # 空 key 被剥离 → merge 时保留已存值；其余字段照常更新
    assert "api_key" not in payload["models"]["primary"]
    assert payload["models"]["primary"]["rpm_limit"] == 120


def test_nonblank_api_key_is_also_stripped_from_payload():
    """安全策略升级：前端传来的非空 key 也必须被丢弃，防止注入/覆盖。"""
    payload = {"models": {"primary": {"api_key": "sk-attacker-injected"}}}
    _strip_all_api_keys(payload)
    assert "api_key" not in payload["models"]["primary"]


def test_whitespace_only_api_key_is_stripped():
    payload = {"models": {"fallback": {"api_key": "   "}}}
    _strip_all_api_keys(payload)
    assert "api_key" not in payload["models"]["fallback"]


def test_both_slots_stripped():
    payload = {
        "models": {
            "primary": {"api_key": "sk-primary", "model": "qwen"},
            "fallback": {"api_key": "sk-fallback", "model": "deepseek"},
        }
    }
    _strip_all_api_keys(payload)
    assert "api_key" not in payload["models"]["primary"]
    assert "api_key" not in payload["models"]["fallback"]
    # 非 key 字段保留
    assert payload["models"]["primary"]["model"] == "qwen"
    assert payload["models"]["fallback"]["model"] == "deepseek"


def test_no_models_key_is_safe():
    """payload 不含 models 字段时不报错。"""
    payload = {"extraction": {"granularity_level": 3}}
    _strip_all_api_keys(payload)  # should not raise


def test_parse_model_env_fallback_when_config_blank(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-from-env")
    model = _parse_model({"provider": "qwen", "api_key": ""})
    assert model.api_key == "sk-from-env"


def test_parse_model_config_value_beats_env(monkeypatch):
    """服务器本地 config.yaml 中的 key 优先于环境变量（仅运维可写）。"""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-from-env")
    model = _parse_model({"provider": "qwen", "api_key": "sk-from-file"})
    assert model.api_key == "sk-from-file"
