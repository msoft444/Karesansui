"""Runtime resolution helper for RoleTemplate records.

Provides :func:`resolve_role_template` which looks up the authoritative
``RoleTemplate`` record for a named role, merges template ``default_params``
with Planner-provided ``dynamic_params``, interpolates ``{{key}}``
placeholders in the system prompt, and returns a compact
:class:`ResolvedTemplate` value for use by the orchestration runtime.

The Planner DAG schema is not changed by this module; callers are responsible
for passing the ``dynamic_params`` from the DAG node verbatim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

# Matches {{key}} placeholders used in seeded system prompts
# (e.g. "{{standpoint}}", "{{tone}}", "{{direction}}").
_PLACEHOLDER_RE = re.compile(r"\{\{([^}]+)\}\}")


def _interpolate(template_str: str, params: dict[str, Any]) -> str:
    """Replace ``{{key}}`` placeholders with their values from *params*.

    Unknown keys are left unchanged so callers can detect missing params
    rather than silently receiving empty strings.
    """
    def _replacer(match: re.Match) -> str:  # type: ignore[type-arg]
        key = match.group(1)
        return str(params[key]) if key in params else match.group(0)
    return _PLACEHOLDER_RE.sub(_replacer, template_str)


class TemplateNotFoundError(RuntimeError):
    """Raised when no RoleTemplate with the given name exists in the DB."""

    def __init__(self, role_name: str) -> None:
        self.role_name = role_name
        super().__init__(
            f"RoleTemplate not found: {role_name!r}. "
            "The Planner referenced a role that has no matching template in the database."
        )


@dataclass
class ResolvedTemplate:
    """Resolved runtime snapshot of a :class:`~app.models.RoleTemplate` record.

    Attributes
    ----------
    template_name:
        The canonical name stored in the DB (e.g. ``"Data_Gatherer"``).
    system_prompt:
        Authoritative system prompt text from the template record.
    tools:
        List of tool names declared by the template.
    resolved_params:
        Merged parameter dict: template ``default_params`` overridden by any
        Planner-provided ``dynamic_params``.
    """

    template_name: str
    system_prompt: str
    tools: list[str] = field(default_factory=list)
    resolved_params: dict[str, Any] = field(default_factory=dict)


def resolve_role_template(
    role_name: str,
    dynamic_params: dict[str, Any] | None,
    session: Session,
) -> ResolvedTemplate:
    """Look up the RoleTemplate for *role_name* and merge runtime params.

    Parameters
    ----------
    role_name:
        Canonical role name used as the DB lookup key (e.g. ``"Data_Gatherer"``).
    dynamic_params:
        Planner-provided overrides applied on top of ``RoleTemplate.default_params``.
        May be ``None`` or empty.
    session:
        Active SQLAlchemy session used for the DB lookup.

    Returns
    -------
    ResolvedTemplate

    Raises
    ------
    TemplateNotFoundError
        When no ``RoleTemplate`` record with ``name == role_name`` exists.
    """
    from app.models import RoleTemplate  # deferred to avoid import cycle at module load

    template = session.query(RoleTemplate).filter_by(name=role_name).first()
    if template is None:
        raise TemplateNotFoundError(role_name)

    # Merge: template defaults first; Planner-supplied values override
    resolved_params: dict[str, Any] = dict(template.default_params or {})
    if dynamic_params:
        resolved_params.update(dynamic_params)

    # Interpolate {{key}} placeholders in the system prompt using the
    # fully-merged resolved_params so that runtime values (e.g. standpoint,
    # tone, direction) replace the seed-data placeholders before inference.
    interpolated_prompt = _interpolate(template.system_prompt, resolved_params)

    return ResolvedTemplate(
        template_name=template.name,
        system_prompt=interpolated_prompt,
        tools=list(template.tools or []),
        resolved_params=resolved_params,
    )
