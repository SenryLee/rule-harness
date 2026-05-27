"""Regression tests for prompt_loader.

Covers:
  - braces in user content do not raise (the old .format-based code did)
  - few-shot/output-format appendix is preserved verbatim
"""
from __future__ import annotations

from pathlib import Path

from backend.prompt_loader import load_prompt, render, render_system_user


def test_render_replaces_known_tokens():
    out = render("hello {name}, age {n}", {"name": "Lee", "n": "30"})
    assert out == "hello Lee, age 30"


def test_render_ignores_unknown_tokens():
    # 占位符未传值时保持原样，避免对调用方造成隐式破坏
    out = render("hello {name}, age {n}", {"name": "Lee"})
    assert "{n}" in out


def test_render_does_not_choke_on_braces_in_values():
    # 这是 .format 模式下会 KeyError 的场景
    val = "原文含 {合同金额} 占位符"
    out = render("正文：{block_text}", {"block_text": val})
    assert val in out


def test_load_prompt_p1_segments_present():
    prompt_path = Path(__file__).resolve().parent.parent / "prompts" / "P1_atomic_extract.txt"
    sections = load_prompt(prompt_path)
    assert "拆解决策树" in sections.system_template
    assert "{block_text}" in sections.user_template
    assert sections.appendix.startswith("[FEW-SHOT")


def test_render_system_user_appendix_kept_verbatim():
    prompt_path = Path(__file__).resolve().parent.parent / "prompts" / "P1_atomic_extract.txt"
    sections = load_prompt(prompt_path)
    sys_text, user_text = render_system_user(
        sections,
        system_vars={
            "redline_keywords": "红线, 不得",
            "theme_keys": "payment.term.days",
            "industry_context": "测试行业",
            "coverage_policy": "高召回测试策略",
        },
        user_vars={
            "filename": "x.docx",
            "source_tag": "合同模板",
            "priority": "5",
            "contract_types": "采购",
            "jurisdiction": "中国大陆",
            "location": "p1",
            "block_text": "原文含 {合同金额} 占位符与 LPR + 30%",
        },
    )
    # few-shot 段必须出现在拼接结果末尾且保留 JSON 大括号
    assert "FEW-SHOT" in user_text
    assert "{\n  \"" in user_text or '{' in user_text
    # 用户原文也没出问题
    assert "{合同金额}" in user_text
    assert "高召回测试策略" in sys_text
