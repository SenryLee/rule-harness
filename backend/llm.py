from __future__ import annotations

import asyncio
import json
import random
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Optional


class LLMTransientError(Exception):
    pass


class LLMRateLimitError(LLMTransientError):
    pass


class LLMValidationError(Exception):
    pass


@dataclass(frozen=True)
class LLMResponse:
    content: str
    usage: dict
    raw: dict
    latency_ms: int


class LLMProvider(ABC):
    name: str

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        rpm_limit: int = 60,
        tpm_limit: int = 200_000,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._rpm_semaphore = asyncio.Semaphore(rpm_limit)
        self._tpm_limit = tpm_limit

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.2,
        max_tokens: int = 4000,
        response_format: str | None = None,
        timeout: int = 60,
    ) -> LLMResponse:
        ...

    def estimate_tokens(self, text: str) -> int:
        en_chars = 0
        cn_chars = 0
        for ch in text:
            if "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿":
                cn_chars += 1
            elif ch.isalpha():
                en_chars += 1
        return int(en_chars / 4 + cn_chars / 1.5)


class DeepSeekProvider(LLMProvider):
    name = "deepseek"
    token_limit_field = "max_tokens"

    def _build_payload(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        response_format: str | None,
    ) -> dict:
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            self.token_limit_field: max_tokens,
        }
        if response_format == "json":
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.2,
        max_tokens: int = 4000,
        response_format: str | None = None,
        timeout: int = 60,
    ) -> LLMResponse:
        import aiohttp

        payload = self._build_payload(messages, temperature, max_tokens, response_format)
        headers = self._headers()

        url = f"{self.base_url}/chat/completions"
        max_retries = 4

        async with self._rpm_semaphore:
            for attempt in range(max_retries):
                t0 = time.time()
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            url,
                            json=payload,
                            headers=headers,
                            timeout=aiohttp.ClientTimeout(total=timeout),
                        ) as resp:
                            raw_text = await resp.text()
                            try:
                                raw = json.loads(raw_text)
                            except json.JSONDecodeError:
                                raw = {"raw": raw_text}

                            if resp.status == 429:
                                retry_after = _extract_retry_after(raw, attempt)
                                await asyncio.sleep(retry_after + random.uniform(0, 1))
                                continue

                            if resp.status >= 500:
                                if attempt < max_retries - 1:
                                    await asyncio.sleep(2**attempt + random.uniform(0, 1))
                                    continue
                                raise LLMTransientError(
                                    f"Server error {resp.status}: {raw}"
                                )

                            if resp.status >= 400:
                                raise LLMValidationError(
                                    f"Client error {resp.status}: {raw}"
                                )

                            latency_ms = int((time.time() - t0) * 1000)
                            content = raw["choices"][0]["message"]["content"]
                            usage = raw.get("usage", {})

                            return LLMResponse(
                                content=content,
                                usage=usage,
                                raw=raw,
                                latency_ms=latency_ms,
                            )
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2**attempt + random.uniform(0, 1))
                        continue
                    raise LLMTransientError(f"Connection error: {e}") from e

        raise LLMTransientError("Max retries exhausted")


class OpenAIProvider(DeepSeekProvider):
    name = "openai"


class MimoProvider(DeepSeekProvider):
    name = "mimo"
    token_limit_field = "max_completion_tokens"

    def _build_payload(
        self,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        response_format: str | None,
    ) -> dict:
        payload = super()._build_payload(messages, temperature, max_tokens, response_format)
        payload["thinking"] = {"type": "disabled"}
        payload.setdefault("stream", False)
        return payload

    def _headers(self) -> dict:
        return {
            "api-key": self.api_key,
            "Content-Type": "application/json",
        }


def _extract_retry_after(raw: dict, attempt: int) -> float:
    base = 2.0 ** min(attempt, 4)
    message = raw.get("error", {}).get("message", "")
    if "retry after" in str(message).lower():
        import re

        match = re.search(r"(\d+(?:\.\d+)?)\s*(s|sec|second|seconds)", str(message))
        if match:
            return float(match.group(1))
    return base


class LLMRouter:
    def __init__(
        self,
        primary: LLMProvider,
        fallback: Optional[LLMProvider] = None,
        usage_callback: Callable[[dict], None] | None = None,
    ):
        self.primary = primary
        self.fallback = fallback
        self.usage_callback = usage_callback

    async def chat(self, **kwargs) -> LLMResponse:
        try:
            return await self.primary.chat(**kwargs)
        except (LLMTransientError, LLMRateLimitError):
            if self.fallback:
                return await self.fallback.chat(**kwargs)
            raise

    async def chat_json(
        self,
        system: str,
        user: str,
        temperature: float = 0.2,
        retries: int = 2,
    ) -> dict:
        messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        last_err: Optional[Exception] = None
        for attempt in range(retries + 1):
            t = 0.0 if attempt > 0 else temperature
            resp = await self.chat(
                messages=messages,
                temperature=t,
                response_format="json",
            )
            if self.usage_callback:
                self.usage_callback(resp.usage)
            try:
                return json.loads(resp.content)
            except json.JSONDecodeError as e:
                last_err = e
                continue
        raise LLMValidationError(
            f"JSON parse failed after {retries} retries: {last_err}"
        )


def _resolve_provider(raw: dict) -> LLMProvider:
    provider_name = raw.get("provider", "").lower()
    if provider_name == "mimo":
        return MimoProvider(
            api_key=raw["api_key"],
            base_url=raw.get("base_url") or "https://api.xiaomimimo.com/v1",
            model=raw.get("model") or "mimo-v2.5-pro",
            rpm_limit=raw.get("rpm_limit", 60),
            tpm_limit=raw.get("tpm_limit", 200_000),
        )
    if provider_name == "openai":
        return OpenAIProvider(
            api_key=raw["api_key"],
            base_url=raw["base_url"],
            model=raw["model"],
            rpm_limit=raw.get("rpm_limit", 500),
            tpm_limit=raw.get("tpm_limit", 1_000_000),
        )
    return DeepSeekProvider(
        api_key=raw["api_key"],
        base_url=raw["base_url"],
        model=raw["model"],
        rpm_limit=raw.get("rpm_limit", 60),
        tpm_limit=raw.get("tpm_limit", 200_000),
    )


def create_llm_router(cfg) -> LLMRouter:
    models = cfg.models
    primary = _resolve_provider(
        {
            "provider": models.primary.provider,
            "api_key": models.primary.api_key,
            "base_url": models.primary.base_url,
            "model": models.primary.model,
            "rpm_limit": models.primary.rpm_limit,
            "tpm_limit": models.primary.tpm_limit,
        }
    )

    fallback_cfg = models.fallback
    if fallback_cfg and fallback_cfg.provider and fallback_cfg.api_key:
        fallback = _resolve_provider(
            {
                "provider": fallback_cfg.provider,
                "api_key": fallback_cfg.api_key,
                "base_url": fallback_cfg.base_url,
                "model": fallback_cfg.model,
                "rpm_limit": fallback_cfg.rpm_limit,
                "tpm_limit": fallback_cfg.tpm_limit,
            }
        )
    else:
        fallback = None

    return LLMRouter(primary=primary, fallback=fallback)
