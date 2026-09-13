"""Small DeepSeek boundary with explicit usage and no automatic billable retries."""

from dataclasses import dataclass, field
from types import TracebackType

import httpx

_ENDPOINT = "https://api.deepseek.com/chat/completions"


@dataclass(frozen=True)
class Completion:
    content: str = field(repr=False)
    model: str
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    finish_reason: str
    request_id: str | None


class ProviderError(Exception):
    """A safe message plus any known completion usage, including failed output."""

    def __init__(self, code: str, message: str, completion: Completion | None = None):
        super().__init__(message)
        self.code = code
        self.completion = completion


def _token_count(usage: dict, name: str) -> int:
    value = usage.get(name)
    if type(value) is not int or value < 0:
        raise ProviderError("invalid_usage", "DeepSeek returned missing or invalid token usage.")
    return value


def _parse_completion(payload: object) -> Completion:
    if not isinstance(payload, dict):
        raise ProviderError("invalid_response", "DeepSeek returned an invalid response envelope.")
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        raise ProviderError("invalid_usage", "DeepSeek returned missing or invalid token usage.")
    input_tokens = _token_count(usage, "prompt_tokens")
    cached = _token_count(usage, "prompt_cache_hit_tokens")
    output_tokens = _token_count(usage, "completion_tokens")
    if cached > input_tokens:
        raise ProviderError("invalid_usage", "DeepSeek returned inconsistent token usage.")
    if "prompt_cache_miss_tokens" in usage:
        if _token_count(usage, "prompt_cache_miss_tokens") + cached != input_tokens:
            raise ProviderError("invalid_usage", "DeepSeek returned inconsistent token usage.")
    if "total_tokens" in usage:
        if _token_count(usage, "total_tokens") != input_tokens + output_tokens:
            raise ProviderError("invalid_usage", "DeepSeek returned inconsistent token usage.")

    choices = payload.get("choices")
    model = payload.get("model")
    request_id = payload.get("id")
    if (
        not isinstance(choices, list)
        or len(choices) != 1
        or not isinstance(choices[0], dict)
        or not isinstance(model, str)
        or not model.strip()
        or len(model) > 100
        or (
            request_id is not None
            and (not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 255)
        )
    ):
        raise ProviderError("invalid_response", "DeepSeek returned an invalid response envelope.")
    message = choices[0].get("message")
    reason = choices[0].get("finish_reason")
    if (
        not isinstance(message, dict)
        or "content" not in message
        or (message["content"] is not None and not isinstance(message["content"], str))
        or not isinstance(reason, str)
        or not reason.strip()
        or len(reason) > 100
    ):
        raise ProviderError("invalid_response", "DeepSeek returned an invalid response envelope.")
    completion = Completion(
        content=message["content"] or "",
        model=model,
        input_tokens=input_tokens,
        cached_input_tokens=cached,
        output_tokens=output_tokens,
        finish_reason=reason,
        request_id=request_id,
    )
    if reason == "length":
        raise ProviderError(
            "truncated_output", "DeepSeek output exceeded the token limit.", completion
        )
    if reason != "stop":
        raise ProviderError(
            "incomplete_output", "DeepSeek did not finish the requested output.", completion
        )
    if not completion.content.strip():
        raise ProviderError("empty_output", "DeepSeek returned empty output.", completion)
    return completion


class DeepSeekClient:
    def __init__(
        self, api_key: str, timeout: float = 60, transport: httpx.AsyncBaseTransport | None = None
    ):
        if not isinstance(api_key, str) or not api_key.strip():
            raise ProviderError("missing_api_key", "A DeepSeek API key is required.")
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    async def __aenter__(self) -> "DeepSeekClient":
        await self._client.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._client.__aexit__(exc_type, exc, traceback)

    async def complete(self, *, model: str, messages: list[dict], max_tokens: int) -> Completion:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("A model name is required")
        if type(max_tokens) is not int or not 1 <= max_tokens <= 393216:
            raise ValueError("max_tokens must be an integer from 1 to 393216")
        if not isinstance(messages, list) or not messages:
            raise ValueError("At least one message is required")
        try:
            response = await self._client.post(
                _ENDPOINT,
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "response_format": {"type": "json_object"},
                    "thinking": {"type": "disabled"},
                    "stream": False,
                    "temperature": 0,
                },
            )
        except httpx.TimeoutException:
            raise ProviderError(
                "timeout", "DeepSeek timed out; request usage may be unknown. No retry was made."
            ) from None
        except httpx.HTTPError:
            raise ProviderError(
                "transport_error", "DeepSeek could not be reached. No retry was made."
            ) from None
        # Never include provider bodies, headers, or HTTPX exception strings in errors.
        status_errors = {
            401: ("unauthorized", "DeepSeek rejected the API key."),
            402: ("insufficient_balance", "DeepSeek requires additional API balance."),
            429: ("rate_limited", "DeepSeek rate limited the request. No retry was made."),
        }
        if not response.is_success:
            code, message = status_errors.get(
                response.status_code,
                (
                    "http_error",
                    f"DeepSeek returned HTTP {response.status_code}. No retry was made.",
                ),
            )
            raise ProviderError(code, message)
        try:
            payload = response.json()
        except ValueError:
            raise ProviderError("invalid_response", "DeepSeek returned invalid JSON.") from None
        return _parse_completion(payload)
