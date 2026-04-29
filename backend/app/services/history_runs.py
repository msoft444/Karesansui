"""history_runs.py — deterministic run-oriented read model for the History table.

Converts raw History rows into user-visible QueryRun aggregates (RunSummary /
RunDetail) without touching the orchestration write path.

Row classification
------------------
The aggregation layer recognises four categories of History rows:

1. **Planner topology row** — role=="Planner" AND task_id matches
   ``planner_run_{run_id}``.  Carries the full DAG topology in
   ``result.tasks``.  Used to derive task ordering and membership; excluded
   from the user-visible task list.

2. **Lifecycle rows** — task_id matches any of the fixed prefixes:
   ``bootstrap_``, ``planner_started_``, ``pipeline_failed_``.
   Drive run-level status (queued, running, failed) but are not Display Tasks.

3. **Debate round rows** — task_id matches ``{parent_task_id}:round{N}:{role}``.
   Aggregated under their parent Display Task via ``progress.parent_task_id``
   (preferred) or regex parsing of the compound task_id (fallback).

4. **Standard task rows** — everything else.  Keyed by task_id; match
   directly to Planner DAG entries.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from app.models import History
from app.schemas import (
    DisplayTask,
    HistoryResponse,
    RunDetail,
    RunStatus,
    RunSummary,
    TaskStatus,
)

# ---------------------------------------------------------------------------
# Compiled patterns for row classification
# ---------------------------------------------------------------------------

_PLANNER_ROW_RE = re.compile(r"^planner_run_")
_LIFECYCLE_PREFIXES_RE = re.compile(
    r"^(?:bootstrap|planner_started|pipeline_failed)_"
)
_DEBATE_ROUND_RE = re.compile(r"^(.+):round\d+:.+$")

# Result-level status strings that represent terminal failure states.
_FAILURE_STATUSES: frozenset[str] = frozenset(
    ["planner-failed", "orchestration-failed", "failed", "enqueue_failed"]
)
# Result-level status strings that mean the run has not yet started executing tasks.
_QUEUED_STATUSES: frozenset[str] = frozenset(["queued"])
# Result-level status strings that mean a non-terminal active state.
_RUNNING_STATUSES: frozenset[str] = frozenset(["planner-started"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_planner_row(record: History) -> bool:
    """Return True for the Planner topology row (role==Planner, task_id=planner_run_*)."""
    return record.role == "Planner" and bool(_PLANNER_ROW_RE.match(record.task_id))


def _is_lifecycle_row(record: History) -> bool:
    """Return True for bootstrap / planner_started / pipeline_failed rows."""
    return bool(_LIFECYCLE_PREFIXES_RE.match(record.task_id))


def _debate_parent_task_id(record: History) -> str | None:
    """Return the parent DAG task_id for a Debate round row, or None.

    Prefers the explicitly persisted ``progress.parent_task_id`` value written
    by DebateController._persist_turn().  Falls back to regex parsing of the
    compound ``{parent}:round{N}:{role}`` task_id pattern.
    """
    if record.progress and isinstance(record.progress, dict):
        parent = record.progress.get("parent_task_id")
        if parent and isinstance(parent, str):
            return parent
    m = _DEBATE_ROUND_RE.match(record.task_id)
    return m.group(1) if m else None


def _result_lifecycle_status(result: dict[str, Any] | None) -> str | None:
    """Extract the lifecycle ``status`` string from a result dict, if present."""
    if result and isinstance(result, dict):
        s = result.get("status")
        return str(s) if s is not None else None
    return None


def _result_has_error(result: dict[str, Any] | None) -> bool:
    """Return True if the result dict contains a non-None ``error`` field."""
    if result and isinstance(result, dict):
        return bool(result.get("error"))
    return False


def _derive_task_status(records: list[History]) -> TaskStatus:
    """Derive a TaskStatus from one or more raw History rows for the same Display Task."""
    for r in records:
        st = _result_lifecycle_status(r.result)
        if st in _FAILURE_STATUSES or _result_has_error(r.result):
            return TaskStatus.failed
    for r in records:
        if r.result and not _result_lifecycle_status(r.result):
            # A result with no lifecycle-status field means a real agent output.
            return TaskStatus.completed
    for r in records:
        if r.progress:
            return TaskStatus.running
    return TaskStatus.pending


def _derive_run_status(
    lifecycle_rows: list[History],
    task_records: dict[str, list[History]],
    dag_task_ids: list[str],
) -> RunStatus:
    """Derive the overall RunStatus for one run from its classified row buckets."""
    # Terminal failure: lifecycle row or task row carries a failure status.
    for r in lifecycle_rows:
        st = _result_lifecycle_status(r.result)
        if st in _FAILURE_STATUSES:
            return RunStatus.failed

    for records in task_records.values():
        for r in records:
            st = _result_lifecycle_status(r.result)
            if st in _FAILURE_STATUSES or _result_has_error(r.result):
                return RunStatus.failed

    # No task rows yet: derive from lifecycle rows.
    if not task_records:
        for r in lifecycle_rows:
            st = _result_lifecycle_status(r.result)
            if st in _QUEUED_STATUSES:
                return RunStatus.queued
            if st in _RUNNING_STATUSES:
                return RunStatus.running
        return RunStatus.queued

    # All DAG tasks completed when every topology task has at least one primary
    # (non-sub-record) row with a real completed result.
    if dag_task_ids:
        all_completed = all(
            (
                tid in task_records
                and any(
                    r.result and not _result_lifecycle_status(r.result)
                    for r in task_records[tid]
                    if not _debate_parent_task_id(r)  # primary rows only
                )
            )
            for tid in dag_task_ids
        )
        if all_completed:
            return RunStatus.completed
    else:
        # No topology available (Planner row write failed but tasks succeeded).
        # Consider the run completed when every task bucket has at least one
        # primary completed row and no failures were detected above.
        all_primary_complete = bool(task_records) and all(
            any(
                r.result and not _result_lifecycle_status(r.result)
                for r in rows
                if not _debate_parent_task_id(r)
            )
            for rows in task_records.values()
        )
        if all_primary_complete:
            return RunStatus.completed

    return RunStatus.running


def _find_terminal_result(
    topology: list[dict[str, Any]],
    task_records: dict[str, list[History]],
    lifecycle_rows: list[History],
) -> dict[str, Any] | None:
    """Return the canonical final result for a run.

    Selection logic (highest priority first):
    1. If the DAG topology is available, locate the terminal task (a task that
       is not referenced as a parent by any other task) and return its result.
    2. If multiple terminal tasks exist, take the first one that has a
       completed (non-lifecycle-status) result.
    3. Fall back to the lifecycle rows for the latest terminal failure payload.
    4. If no result is available, return None.
    """
    if topology:
        parent_ids: set[str] = set()
        for t in topology:
            for pid in t.get("parent_ids", []):
                parent_ids.add(pid)

        terminal_ids = [t["task_id"] for t in topology if t["task_id"] not in parent_ids]
        if not terminal_ids:
            terminal_ids = [t["task_id"] for t in topology]

        for tid in terminal_ids:
            # Scan primary rows only — Debate sub-records must not be returned
            # as the run-level final result before the parent summary row exists.
            records = sorted(
                [
                    r for r in task_records.get(tid, [])
                    if not _debate_parent_task_id(r)
                ],
                key=lambda r: r.created_at,
                reverse=True,
            )
            for r in records:
                if r.result and not _result_lifecycle_status(r.result):
                    return r.result

    else:
        # No topology available — return the most-recently created primary
        # completed row across all task buckets as the best-available result.
        all_primary = [
            r
            for rows in task_records.values()
            for r in rows
            if not _debate_parent_task_id(r)
            and r.result
            and not _result_lifecycle_status(r.result)
        ]
        if all_primary:
            all_primary.sort(key=lambda r: r.created_at, reverse=True)
            return all_primary[0].result

    # No topology or no terminal task result found — fall back to failure payload.
    for r in sorted(lifecycle_rows, key=lambda r: r.created_at, reverse=True):
        st = _result_lifecycle_status(r.result)
        if st in _FAILURE_STATUSES:
            return r.result

    return None


def _make_preview(result: dict[str, Any] | None) -> str | None:
    """Generate a ≤120-character preview string from a result dict."""
    if not result:
        return None
    # Lifecycle status strings are human-readable as-is.
    st = _result_lifecycle_status(result)
    if st:
        return st
    # Agent results contain a ``summary`` or ``output`` top-level field.
    for key in ("summary", "output", "conclusion"):
        v = result.get(key)
        if v and isinstance(v, str):
            return v[:120]
    return str(result)[:120]


def _to_history_response(r: History) -> HistoryResponse:
    return HistoryResponse(
        id=r.id,
        run_id=r.run_id,
        task_id=r.task_id,
        role=r.role,
        result=r.result,
        progress=r.progress,
        created_at=r.created_at,
    )


def _bucket_rows(
    rows: list[History],
) -> tuple[
    History | None,             # planner_row
    list[History],              # lifecycle_rows
    dict[str, list[History]],  # task_records keyed by Display Task task_id
]:
    """Separate a run's History rows into three buckets for aggregation."""
    planner_row: History | None = None
    lifecycle_rows: list[History] = []
    task_records: dict[str, list[History]] = {}

    for r in rows:
        if _is_planner_row(r):
            planner_row = r
            continue
        if _is_lifecycle_row(r):
            lifecycle_rows.append(r)
            continue
        # Debate round → bucket under parent task_id.
        parent = _debate_parent_task_id(r)
        key = parent if parent else r.task_id
        task_records.setdefault(key, []).append(r)

    return planner_row, lifecycle_rows, task_records


def _build_display_tasks(
    topology: list[dict[str, Any]],
    task_records: dict[str, list[History]],
) -> list[DisplayTask]:
    """Construct the ordered Display Task list for the detail screen.

    If a Planner topology is available it determines both the ordering and the
    task metadata (type, role, parents, dynamic params).  Without a topology,
    tasks are derived from the raw task_records and ordered by earliest
    created_at.
    """
    display_tasks: list[DisplayTask] = []

    if topology:
        for t in topology:
            tid = t["task_id"]
            records = task_records.get(tid, [])

            # Separate primary records (no parent_task_id) from Debate sub-records.
            primary = [r for r in records if not _debate_parent_task_id(r)]
            sub = [r for r in records if _debate_parent_task_id(r)]

            primary_sorted = sorted(primary, key=lambda r: r.created_at, reverse=True)
            latest = primary_sorted[0] if primary_sorted else None
            # Derive status from primary rows only; Debate sub-records are not
            # completion signals for the parent Display Task.
            if primary:
                task_status = _derive_task_status(primary)
            elif sub:
                task_status = TaskStatus.running
            else:
                task_status = TaskStatus.pending

            display_tasks.append(
                DisplayTask(
                    task_id=tid,
                    task_type=t.get("task_type", "Standard"),
                    role=t.get("role") or None,
                    participants=t.get("participants") or None,
                    mediator=t.get("mediator") or None,
                    parent_ids=t.get("parent_ids", []),
                    dynamic_params=t.get("dynamic_params") or {},
                    status=task_status,
                    created_at=latest.created_at if latest else None,
                    result=latest.result if latest else None,
                    progress=latest.progress if latest else None,
                    sub_records=[
                        _to_history_response(r)
                        for r in sorted(sub, key=lambda r: r.created_at)
                    ],
                )
            )
    else:
        # No topology: flat list ordered by earliest row timestamp.
        for tid, records in sorted(
            task_records.items(),
            key=lambda kv: min(r.created_at for r in kv[1]),
        ):
            primary = [r for r in records if not _debate_parent_task_id(r)]
            sub = [r for r in records if _debate_parent_task_id(r)]
            primary_sorted = sorted(primary, key=lambda r: r.created_at, reverse=True)
            latest = primary_sorted[0] if primary_sorted else None
            # Derive status from primary rows only.
            if primary:
                task_status = _derive_task_status(primary)
            elif sub:
                task_status = TaskStatus.running
            else:
                task_status = TaskStatus.pending

            # When the Planner topology is unavailable but round rows are
            # present, the bucket is deterministically a Debate task.
            inferred_task_type: str = "Debate" if sub else "Standard"

            display_tasks.append(
                DisplayTask(
                    task_id=tid,
                    task_type=inferred_task_type,
                    role=latest.role if latest else None,
                    # Debate metadata (participants, mediator) is stored only in
                    # the Planner topology row; without it we surface None and
                    # let the frontend handle the absent metadata gracefully.
                    participants=None,
                    mediator=None,
                    parent_ids=[],
                    dynamic_params={},
                    status=task_status,
                    created_at=latest.created_at if latest else None,
                    result=latest.result if latest else None,
                    progress=latest.progress if latest else None,
                    sub_records=[
                        _to_history_response(r)
                        for r in sorted(sub, key=lambda r: r.created_at)
                    ],
                )
            )

    return display_tasks


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def aggregate_runs(records: list[History]) -> list[RunSummary]:
    """Convert a flat list of raw History rows into one RunSummary per run_id.

    Rows without a run_id are skipped.  Returns summaries ordered
    newest-created-at first.
    """
    by_run: dict[str, list[History]] = {}
    for r in records:
        if r.run_id:
            by_run.setdefault(r.run_id, []).append(r)

    summaries: list[RunSummary] = []
    for run_id, rows in by_run.items():
        summaries.append(_build_run_summary(run_id, rows))

    summaries.sort(key=lambda s: s.created_at, reverse=True)
    return summaries


def _build_run_summary(run_id: str, rows: list[History]) -> RunSummary:
    planner_row, lifecycle_rows, task_records = _bucket_rows(rows)

    topology: list[dict[str, Any]] = []
    if planner_row and planner_row.result:
        topology = planner_row.result.get("tasks", []) or []
    dag_task_ids = [t["task_id"] for t in topology]

    status = _derive_run_status(lifecycle_rows, task_records, dag_task_ids)
    final_result = _find_terminal_result(topology, task_records, lifecycle_rows)
    preview = _make_preview(final_result)
    created_at = min((r.created_at for r in rows), default=datetime.now(timezone.utc))
    task_count = len(dag_task_ids) if dag_task_ids else len(task_records)

    return RunSummary(
        run_id=run_id,
        status=status,
        created_at=created_at,
        final_result_preview=preview,
        task_count=task_count,
    )


def aggregate_run_detail(run_id: str, records: list[History]) -> RunDetail | None:
    """Build a full RunDetail for one run_id from its raw History rows.

    Returns None when no rows exist for the given run_id.
    """
    rows = [r for r in records if r.run_id == run_id]
    if not rows:
        return None

    planner_row, lifecycle_rows, task_records = _bucket_rows(rows)

    topology: list[dict[str, Any]] = []
    if planner_row and planner_row.result:
        topology = planner_row.result.get("tasks", []) or []
    dag_task_ids = [t["task_id"] for t in topology]

    status = _derive_run_status(lifecycle_rows, task_records, dag_task_ids)
    final_result = _find_terminal_result(topology, task_records, lifecycle_rows)
    preview = _make_preview(final_result)
    created_at = min((r.created_at for r in rows), default=datetime.now(timezone.utc))

    display_tasks = _build_display_tasks(topology, task_records)

    return RunDetail(
        run_id=run_id,
        status=status,
        created_at=created_at,
        final_result=final_result,
        final_result_preview=preview,
        dag_topology=topology if topology else None,
        tasks=display_tasks,
    )
