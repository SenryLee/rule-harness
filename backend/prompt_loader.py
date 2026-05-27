"""
Prompt template loader.

Why this module exists
----------------------
The harness prompt files (`backend/prompts/*.txt`) contain `[SYSTEM]`, `[USER]`,
`[FEW-SHOT*]` and `[OUTPUT FORMAT]` section markers. Earlier code used
``str.format(...)`` to inject variables — but legal/contract source text often
contains literal ``{`` or ``}`` characters (e.g. JSON examples, ``{合同金额}``
placeholders). Those triggered ``KeyError`` and silently swallowed entire
extraction batches.

This loader splits the template into typed segments and substitutes variables
via ``str.replace`` (which doesn't interpret braces).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class PromptSections:
    """Decomposed prompt template."""

    system_template: str
    user_template: str
    appendix: str  # few-shot + output format; concatenated verbatim after user


_SECTION_MARKERS = ("[SYSTEM]", "[USER]")


def load_prompt(path: Path) -> PromptSections:
    """Load and split a prompt template file into named sections."""
    text = path.read_text(encoding="utf-8")
    if "[SYSTEM]" not in text or "[USER]" not in text:
        raise ValueError(f"Prompt {path.name} missing [SYSTEM] or [USER] markers")

    sys_start = text.index("[SYSTEM]") + len("[SYSTEM]")
    sys_end = text.index("[USER]")
    system_segment = text[sys_start:sys_end].strip()

    user_start = text.index("[USER]") + len("[USER]")

    # Look for any [FEW-SHOT ...] or [OUTPUT FORMAT] marker that ends the USER segment.
    appendix_idx = -1
    for marker in ("[FEW-SHOT", "[OUTPUT FORMAT]"):
        idx = text.find(marker, user_start)
        if idx != -1 and (appendix_idx == -1 or idx < appendix_idx):
            appendix_idx = idx

    if appendix_idx == -1:
        user_segment = text[user_start:].strip()
        appendix = ""
    else:
        user_segment = text[user_start:appendix_idx].strip()
        appendix = text[appendix_idx:].strip()

    return PromptSections(
        system_template=system_segment,
        user_template=user_segment,
        appendix=appendix,
    )


def render(template: str, variables: Mapping[str, str]) -> str:
    """Safely substitute ``{key}`` tokens in a template.

    Uses ``str.replace`` so braces inside the values do not blow up.
    Variables that do not appear in the template are silently ignored.
    """
    rendered = template
    for key, val in variables.items():
        token = "{" + key + "}"
        if token in rendered:
            rendered = rendered.replace(token, "" if val is None else str(val))
    return rendered


def render_system_user(
    sections: PromptSections,
    *,
    system_vars: Mapping[str, str],
    user_vars: Mapping[str, str],
) -> tuple[str, str]:
    """Render system + user prompts using the configured sections.

    The appendix (few-shot / output format) is appended verbatim to the user
    prompt — it is *never* substituted, so the literal braces in the JSON
    examples are preserved untouched.
    """
    system_text = render(sections.system_template, system_vars)
    user_text = render(sections.user_template, user_vars)
    if sections.appendix:
        user_text = f"{user_text}\n\n{sections.appendix}"
    return system_text, user_text
