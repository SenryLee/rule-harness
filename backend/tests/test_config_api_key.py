"""api_key 持久化防护测试。

覆盖"每次更新后 key 丢失"的两条防线：
  1. 后端 _strip_blank_api_keys：空 api_key 不得覆盖已存密钥；
  2. _parse_model 环境变量兜底：config.yaml 留空时从 env 读取。
"""
from __future__ import annotations

import os

from backend.config import _parse_model
from backend.routes.config_routes import _strip_blank_api_keys


def test_blank_api_key_is_stripped_from_payload():
    payload = {"models": {"primary": {"api_key": "", "rpm_limit": 120}}}
    _strip_blank_api_keys(payload)
    # 空 key 被剥离 → merge 时保留已存值；其余字段照常更新
    assert "api_key" not in payload["models"]["primary"]
    assert payload["models"]["primary"]["rpm_limit"] == 120


def test_nonblank_api_key_is_preserved_in_payload():
    payload = {"models": {"primary": {"api_key": "sk-new"}}}
    _strip_blank_api_keys(payload)
    assert payload["models"]["primary"]["api_key"] == "sk-new"


def test_whitespace_only_api_key_treated_as_blank():
    payload = {"models": {"fallback": {"api_key": "   "}}}
    _strip_blank_api_keys(payload)
    assert "api_key" not in payload["models"]["fallback"]


def test_parse_model_env_fallback_when_config_blank(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-from-env")
    model = _parse_model({"provider": "qwen", "api_key": ""})
    assert model.api_key == "sk-from-env"


def test_parse_model_config_value_beats_env(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-from-env")
    model = _parse_model({"provider": "qwen", "api_key": "sk-from-file"})
    assert model.api_key == "sk-from-file"
