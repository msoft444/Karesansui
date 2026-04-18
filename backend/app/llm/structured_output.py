import os
from typing import Any, TypeVar

import instructor
import openai
from pydantic import BaseModel

# Base URL and API key are read from environment variables — same source as inference_client.
INFERENCE_API_BASE_URL: str = os.environ.get(
    "INFERENCE_API_BASE_URL",
    "http://host.docker.internal:8000/v1",
)
INFERENCE_API_KEY: str = os.environ.get("INFERENCE_API_KEY", "not-required")

# Default timeout in seconds for a single structured inference request.
_DEFAULT_TIMEOUT_SECONDS: float = 120.0

# instructor.Mode.JSON_SCHEMA sends response_format={"type":"json_schema",
# "json_schema":{"name":...,"schema":...,"strict":True}} so the server is
# asked to constrain output to the exact Pydantic schema — satisfying the
# "JSON Schema constraints at the Logits level" requirement
# (requirement_specification.md §8, implementation_guide.md Phase 4 Step 2).
# This mode avoids the tool_call protocol entirely, which is necessary because
# mlx_lm can return multiple tool calls in a single response — a pattern that
# instructor.Mode.TOOLS rejects with AssertionError.
_raw_client = openai.AsyncOpenAI(
    base_url=INFERENCE_API_BASE_URL,
    api_key=INFERENCE_API_KEY,
    timeout=_DEFAULT_TIMEOUT_SECONDS,
)
_client: instructor.AsyncInstructor = instructor.from_openai(
    _raw_client,
    mode=instructor.Mode.JSON_SCHEMA,
)

T = TypeVar("T", bound=BaseModel)


async def generate_structured(
    model: str,
    messages: list[dict[str, Any]],
    response_model: type[T],
    *,
    temperature: float = 0.0,
    max_tokens: int = 2048,
    max_retries: int = 3,
    timeout: float | None = None,
) -> T:
    """Send a chat-completion request and enforce 100% JSON-schema-compliant output.

    The instructor library wraps the OpenAI client and automatically retries
    the request (up to *max_retries*) when the model produces output that does
    not validate against *response_model*.

    Args:
        model: Model identifier string.
        messages: OpenAI-format message list (role/content dicts).
        response_model: A Pydantic BaseModel subclass that defines the expected
            output schema.  The returned value will always be a fully-validated
            instance of this class.
        temperature: Sampling temperature (default 0.0 for deterministic output).
        max_tokens: Maximum tokens in the model response.
        max_retries: Number of JSON-parsing / validation retries before raising.
        timeout: Per-call timeout override in seconds.

    Returns:
        A validated instance of *response_model*.

    Raises:
        instructor.exceptions.InstructorRetryException: When the model fails to
            produce schema-compliant output within *max_retries* attempts.
        openai.APIConnectionError: When the inference engine is unreachable.
        openai.APITimeoutError: When the request exceeds the configured timeout.
        openai.APIStatusError: When the inference engine returns an HTTP error status.
    """
    effective_timeout = timeout if timeout is not None else _DEFAULT_TIMEOUT_SECONDS

    try:
        result: T = await _client.chat.completions.create(
            model=model,
            messages=messages,
            response_model=response_model,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
            timeout=effective_timeout,
        )
    except openai.APIConnectionError as exc:
        raise RuntimeError(
            f"[structured_output] Connection failed: url={INFERENCE_API_BASE_URL}, model={model}"
        ) from exc
    except openai.APITimeoutError as exc:
        raise RuntimeError(
            f"[structured_output] Request timed out after {effective_timeout}s: url={INFERENCE_API_BASE_URL}, model={model}"
        ) from exc
    except openai.APIStatusError as exc:
        raise RuntimeError(
            f"[structured_output] API error (status={exc.status_code}): url={INFERENCE_API_BASE_URL}, model={model} — {exc.message}"
        ) from exc

    return result
