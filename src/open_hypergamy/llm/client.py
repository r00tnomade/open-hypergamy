"""OpenAI-compatible chat client for the FreeLLMAPI loopback gateway (LLD §9.2).

Never follows redirects, never reads keys from anywhere but the environment, never logs
prompts, and only talks to a loopback address. A failed or throttled gateway raises
`LLMUnavailable`; this module has no fallback route to any other provider.
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from open_hypergamy.errors import ConfigurationError, LLMInvalidResponse, LLMUnavailable

_LOOPBACK = {"127.0.0.1", "localhost", "::1"}
_UNAVAILABLE_STATUS = {401, 403, 404, 408, 429, 500, 502, 503, 504}
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


class LLMClient(Protocol):
    model: str
    last_model: str | None

    def healthy(self) -> bool: ...
    def list_models(self) -> list[str]: ...
    def complete_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        schema: dict[str, Any],
        cache_key: str,
    ) -> dict[str, Any]: ...


def extract_json(content: str) -> dict[str, Any]:
    """Parse a model reply that may be wrapped in code fences or surrounded by prose."""
    text = _FENCE.sub("", content.strip())
    for candidate in (text, text[text.find("{") : text.rfind("}") + 1] if "{" in text else ""):
        try:
            parsed = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise LLMInvalidResponse("model reply was not a JSON object")


class OpenAICompatClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None,
        *,
        timeout: float = 90,
        temperature: float = 0.0,
        max_tokens: int = 4000,
        forbidden: list[str] | None = None,
        transport: httpx.BaseTransport | None = None,
        require_key: bool = False,
    ) -> None:
        host = urlparse(base_url).hostname
        if host not in _LOOPBACK:
            raise ConfigurationError(f"LLM endpoint must be loopback, got {host!r}")
        self.model = model
        self._require_key = require_key
        self.last_model: str | None = None
        self._key, self._temp, self._max = api_key, temperature, max_tokens
        # Strings that must never appear in an outgoing request (secrets, local paths, ids).
        self._forbidden = [f for f in (forbidden or []) if f and len(f) >= 4]
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            transport=transport,
            follow_redirects=False,
            trust_env=False,  # the loopback gateway must never be routed through a proxy
            timeout=httpx.Timeout(10.0, read=timeout),
        )

    def close(self) -> None:
        self._http.close()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key}"} if self._key else {}

    def healthy(self) -> bool:
        try:
            return self._http.get("/models", headers=self._headers(), timeout=3.0).is_success
        except httpx.HTTPError:
            return False

    def list_models(self) -> list[str]:
        try:
            r = self._http.get("/models", headers=self._headers(), timeout=5.0)
            r.raise_for_status()
            return [str(m.get("id")) for m in r.json().get("data", []) if isinstance(m, dict)]
        except (httpx.HTTPError, ValueError, AttributeError) as e:
            raise LLMUnavailable(f"could not list models ({type(e).__name__})") from None

    def _guard(self, body: str) -> None:
        if any(f in body for f in self._forbidden):
            raise LLMUnavailable("outgoing request failed the privacy guard; nothing was sent")

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        schema: dict[str, Any],
        cache_key: str,
    ) -> dict[str, Any]:
        if self._require_key and not self._key:
            raise LLMUnavailable("LLM API key is not set; nothing was sent")
        _ = (
            schema,
            cache_key,
        )  # the schema is embedded in `system_prompt`; caching is the caller's
        body = {
            "model": self.model,
            "temperature": self._temp,
            "max_tokens": self._max,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
        }
        self._guard(json.dumps(body, ensure_ascii=False))
        try:
            r = self._http.post("/chat/completions", json=body, headers=self._headers())
        except httpx.TimeoutException:
            raise LLMUnavailable("LLM gateway timed out") from None
        except httpx.HTTPError as e:
            raise LLMUnavailable(f"LLM gateway unreachable ({type(e).__name__})") from None
        if 300 <= r.status_code < 400:
            raise LLMUnavailable("LLM gateway attempted a redirect; refused")
        if r.status_code in _UNAVAILABLE_STATUS:
            raise LLMUnavailable(f"LLM gateway returned HTTP {r.status_code}")
        if not r.is_success:
            raise LLMInvalidResponse(f"LLM gateway rejected the request (HTTP {r.status_code})")
        try:
            data = r.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise LLMInvalidResponse("unexpected gateway response shape") from None
        self.last_model = str(data.get("model") or self.model)
        if not isinstance(content, str):
            raise LLMInvalidResponse("model reply had no text content")
        return extract_json(content)
