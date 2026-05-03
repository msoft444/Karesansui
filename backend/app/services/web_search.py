"""DuckDuckGo web-search provider for the Karesansui tool-dispatch layer.

Registers itself as the ``web_search`` provider on import.  Import this module
at worker / app startup (e.g. in ``app/tasks.py``) to activate the provider.

Design goals
------------
- **Deterministic mock injection**: callers may replace :data:`_ddgs_factory`
  with a test double to return canned fixtures without network access.
- **Compact normalisation**: raw DDG result keys (``title``, ``body``,
  ``href``) are remapped to the stable ``{title, snippet, url}`` schema
  expected by :func:`~app.services.tool_dispatch._normalize_item`.
- **Bounded output**: returns at most :data:`_WEB_SEARCH_MAX_RESULTS` raw
  items; the dispatch layer further caps via its own ``max_results`` limit.
- **Distinct diagnostics**: provider-unreachable, timeout, zero-results, and
  malformed responses are classified separately so run traces are actionable.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable

from app.services.tool_dispatch import register_tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_WEB_SEARCH_MAX_RESULTS: int = int(os.environ.get("WEB_SEARCH_MAX_RESULTS", "10"))
"""Maximum raw results requested from DuckDuckGo.

The tool-dispatch layer further caps output to ``max_results`` (default 5),
so this value acts as the upstream ceiling for raw API requests.
"""

# ---------------------------------------------------------------------------
# Testability hook
# ---------------------------------------------------------------------------

# Replace in unit/integration tests to return canned fixtures without
# touching the network:
#
#   import app.services.web_search as ws_mod
#
#   class _MockDDGS:
#       def __enter__(self): return self
#       def __exit__(self, *a): pass
#       def text(self, query, *, max_results=10):
#           return [{"title": "T", "body": "S", "href": "https://example.com"}]
#
#   ws_mod._ddgs_factory = lambda timeout: _MockDDGS()


def _default_ddgs_factory(timeout: float) -> Any:
    """Return a new :class:`duckduckgo_search.DDGS` instance for *timeout* seconds."""
    from duckduckgo_search import DDGS  # imported lazily to keep module loadable without the package installed in dev shells

    return DDGS(timeout=int(timeout))


_ddgs_factory: Callable[[float], Any] = _default_ddgs_factory
"""Factory for DDGS context-manager instances.  Replace in tests for mocking."""


# ---------------------------------------------------------------------------
# Provider function
# ---------------------------------------------------------------------------


def search(query: str, *, timeout: float = 15.0) -> list[dict[str, Any]]:
    """Search DuckDuckGo for *query* and return normalised result dicts.

    Parameters
    ----------
    query:
        The search string.  Include disambiguation hints (e.g. product name +
        brand) to guide DuckDuckGo's entity resolution for ambiguous names.
    timeout:
        Per-call network timeout in seconds forwarded to the DDGS client.

    Returns
    -------
    list[dict]
        Zero or more result dicts, each containing up to three keys:
        ``"title"``, ``"snippet"``, ``"url"``.  Returns an empty list when
        DuckDuckGo yields no results (dispatch classifies as ``"empty"``).

    Raises
    ------
    TimeoutError
        When the DDGS call exceeds *timeout*.  Re-raised or wrapped from
        library-specific timeout types so the dispatch layer classifies the
        result as ``"timeout"``.
    RuntimeError
        When the DuckDuckGo API is unreachable (connection error, DNS failure,
        HTTP error).  Classifies as ``"provider_error"`` at the dispatch layer.
    ValueError
        When the DuckDuckGo response is structurally malformed (unexpected
        type).  Classifies as ``"provider_error"`` at the dispatch layer.
    """
    raw: Any
    try:
        with _ddgs_factory(timeout) as ddgs:
            raw = ddgs.text(query, max_results=_WEB_SEARCH_MAX_RESULTS)
    except TimeoutError:
        raise  # Dispatch layer classifies as "timeout"
    except Exception as exc:
        exc_type_lower = type(exc).__name__.lower()
        # Promote library-specific timeout exceptions to stdlib TimeoutError.
        if "timeout" in exc_type_lower:
            raise TimeoutError(
                f"[web_search] DuckDuckGo timed out: {exc}"
            ) from exc
        # Classify data-level failures (malformed response from DuckDuckGo's
        # side) separately from network-level connectivity failures.  We use
        # the exception *type hierarchy* first (most reliable), then fall back
        # to a broad keyword check on the type name so that decode/parse/JSON
        # errors from any HTTP client library are also caught.
        # KeyError, TypeError, AttributeError, IndexError all indicate the
        # client received a structurally unexpected payload — treat as malformed.
        _MALFORMED_EXC_TYPES = (ValueError, KeyError, TypeError, AttributeError, IndexError)
        if isinstance(exc, _MALFORMED_EXC_TYPES) or any(
            kw in exc_type_lower for kw in ("decode", "parse", "json", "format")
        ):
            raise ValueError(
                f"[web_search] malformed DuckDuckGo response: {exc}"
            ) from exc
        raise RuntimeError(
            f"[web_search] DuckDuckGo provider unreachable: {exc}"
        ) from exc

    # None is structurally malformed, not a legitimate zero-results response.
    # Raise ValueError so the dispatch layer classifies it as "provider_error"
    # (malformed) rather than collapsing it into the "empty" (zero-results) bucket.
    if raw is None:
        raise ValueError(
            "[web_search] malformed DuckDuckGo response: got None instead of list"
        )

    if not isinstance(raw, list):
        raise ValueError(
            f"[web_search] malformed DuckDuckGo response: expected list, "
            f"got {type(raw).__name__}"
        )

    results: list[dict[str, Any]] = []
    malformed_count: int = 0
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            logger.warning(
                "[web_search] skipping malformed item[%d]: expected dict, got %s",
                i,
                type(item).__name__,
            )
            malformed_count += 1
            continue
        title_raw = str(item.get("title", "")).strip()
        body_raw = str(item.get("body", "")).strip()
        href_raw = str(item.get("href", "")).strip()
        # Accept only http/https URLs (mirrors tool_dispatch._normalize_item).
        href_safe = href_raw if href_raw.startswith(("http://", "https://")) else ""
        # Validate *after* applying the same whitespace-stripping and URL-scheme
        # checks that tool_dispatch._normalize_item will apply downstream.  A
        # dict item that survives this check with all effective fields empty would
        # produce an empty-dict output from _normalize_item and silently fall into
        # the "empty" (zero-results) bucket, destroying the malformed/empty
        # distinction required by plan.md Step 3.
        if not (title_raw or body_raw or href_safe):
            logger.warning(
                "[web_search] skipping post-normalisation-empty item[%d]: "
                "title=%r body=%r href=%r",
                i, item.get("title"), item.get("body"), item.get("href"),
            )
            malformed_count += 1
            continue
        results.append(
            {
                "title": title_raw,
                "snippet": body_raw,
                "url": href_raw,  # pass original; _normalize_item applies safe_url
            }
        )

    # If the provider returned items but every single one was malformed, the
    # response is structurally invalid — raise ValueError so the dispatch layer
    # classifies it as "provider_error" (malformed) rather than "empty"
    # (zero-results), preserving the diagnostic distinction required by plan.md.
    if malformed_count > 0 and not results:
        raise ValueError(
            f"[web_search] malformed DuckDuckGo response: "
            f"all {malformed_count} item(s) had unexpected types"
        )

    logger.info(
        "[web_search] DuckDuckGo returned %d result(s) for query=%r",
        len(results),
        query,
    )
    return results


# ---------------------------------------------------------------------------
# Self-registration — executed on import
# ---------------------------------------------------------------------------

register_tool("web_search", search)
logger.debug("[web_search] provider registered as 'web_search'")
