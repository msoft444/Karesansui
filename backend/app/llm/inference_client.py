import os
from typing import Any

import openai

# Base URL for the host-side OpenAI-compatible inference engine.
# Injected via environment variable; defaults to the standard Docker host gateway address.
INFERENCE_API_BASE_URL: str = os.environ.get(
    "INFERENCE_API_BASE_URL",
    "http://host.docker.internal:8000/v1",
)

# API key placeholder — the local inference engine typically does not require a real key,
# but the openai client requires a non-empty value.
INFERENCE_API_KEY: str = os.environ.get("INFERENCE_API_KEY", "not-required")

# Default timeout in seconds for a single inference request.
_DEFAULT_TIMEOUT_SECONDS: float = 120.0

_client = openai.AsyncOpenAI(
    base_url=INFERENCE_API_BASE_URL,
    api_key=INFERENCE_API_KEY,
    timeout=_DEFAULT_TIMEOUT_SECONDS,
)


async def generate_response(
    model: str,
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    timeout: float | None = None,
) -> str:
    """Send a chat-completion request to the host-side inference engine.

    Args:
        model: Model identifier string (e.g. "prism-ml/Ternary-Bonsai-8B-mlx-2bit").
        messages: OpenAI-format message list (role/content dicts).
        temperature: Sampling temperature.
        max_tokens: Maximum tokens in the response.
        timeout: Per-call override for the request timeout in seconds.
            Uses the module-level default when *None*.

    Returns:
        The assistant message content as a plain string.

    Raises:
        RuntimeError: For all failure modes.  The message prefix indicates the category:
            ``[inference_client] connectivity-failure`` for network / timeout errors, or
            ``[inference_client] API error`` for HTTP status errors.  This mirrors the
            classification scheme used by ``structured_output.generate_structured`` so
            history consumers can classify failures without inspecting the source module.
    """
    effective_timeout = timeout if timeout is not None else _DEFAULT_TIMEOUT_SECONDS

    try:
        response = await _client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=effective_timeout,
        )
    except openai.APIConnectionError as exc:
        raise RuntimeError(
            f"[inference_client] connectivity-failure: inference backend unreachable"
            f" — url={INFERENCE_API_BASE_URL}, model={model}"
        ) from exc
    except openai.APITimeoutError as exc:
        raise RuntimeError(
            f"[inference_client] connectivity-failure: request timed out after {effective_timeout}s"
            f" — url={INFERENCE_API_BASE_URL}, model={model}"
        ) from exc
    except openai.APIStatusError as exc:
        raise RuntimeError(
            f"[inference_client] API error (status={exc.status_code}): url={INFERENCE_API_BASE_URL}, model={model} — {exc.message}"
        ) from exc

    content = response.choices[0].message.content
    return content if content is not None else ""
