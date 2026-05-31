from __future__ import annotations

from backend.llm import MimoProvider, _resolve_provider


def test_resolve_mimo_provider_uses_official_defaults():
    provider = _resolve_provider({
        "provider": "mimo",
        "api_key": "test-key",
        "base_url": "",
        "model": "",
    })

    assert isinstance(provider, MimoProvider)
    assert provider.base_url == "https://api.xiaomimimo.com/v1"
    assert provider.model == "mimo-v2.5-pro"


def test_mimo_payload_uses_max_completion_tokens_and_disables_thinking():
    provider = MimoProvider(
        api_key="test-key",
        base_url="https://api.xiaomimimo.com/v1",
        model="mimo-v2.5-pro",
    )

    payload = provider._build_payload(
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.2,
        max_tokens=123,
        response_format="json",
    )

    assert payload["max_completion_tokens"] == 123
    assert "max_tokens" not in payload
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["response_format"] == {"type": "json_object"}
    assert provider._headers()["api-key"] == "test-key"
