"""Regression tests for the run-oriented aggregation layer and history/runs API endpoints.

Unit tests (TestBucketRows, TestDeriveTaskStatus, TestDeriveRunStatus,
TestFindTerminalResult, TestBuildDisplayTasks, TestAggregateRuns) operate
entirely in-memory with stub History objects.  No DB or Celery required.

DB-backed tests (TestRunsApiEndpoints, TestRawHistoryCompatibility) use the
``client`` fixture from conftest.py and are automatically skipped when
DATABASE_URL is not set or the PostgreSQL instance is unreachable.

Frontend source-verification tests (TestFrontendSourceVerification) parse the
TypeScript/TSX source files and confirm the UI contracts from Steps 3 & 4 of
the feature plan without needing a running server or JS test framework.

Integration tests (marked ``integration``) require the full stack including
the frontend at http://localhost:3000 and backend at http://localhost:8001.
Run them explicitly::

    pytest tests/ -v -m integration
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Sentinel timestamps used across unit tests
# ---------------------------------------------------------------------------

_T0 = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)
_T1 = datetime(2026, 4, 1, 0, 1, 0, tzinfo=timezone.utc)
_T2 = datetime(2026, 4, 1, 0, 2, 0, tzinfo=timezone.utc)
_T3 = datetime(2026, 4, 1, 0, 3, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_row(
    *,
    run_id: str | None = "run_aaa",
    task_id: str = "task_1",
    role: str = "TestAgent",
    result: dict[str, Any] | None = None,
    progress: dict[str, Any] | None = None,
    created_at: datetime | None = None,
) -> MagicMock:
    """Return a stub History-like object with the minimum attributes used by history_runs."""
    row = MagicMock()
    row.run_id = run_id
    row.task_id = task_id
    row.role = role
    row.result = result
    row.progress = progress
    row.created_at = created_at or _T0
    row.id = uuid.uuid4()
    return row


def _cleanup_run(run_id: str) -> None:
    """Delete all History rows for run_id.  Always call in a finally block."""
    from app.database import SessionLocal
    from app.models import History

    db = SessionLocal()
    try:
        db.query(History).filter(History.run_id == run_id).delete()
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# TestBucketRows — _bucket_rows separates rows into three buckets
# ---------------------------------------------------------------------------

class TestBucketRows:
    """_bucket_rows separates rows into planner, lifecycle, and task buckets."""

    def test_planner_row_isolated(self) -> None:
        """A role==Planner + task_id=planner_run_* row lands in planner_row only."""
        from app.services.history_runs import _bucket_rows

        planner = _make_row(task_id="planner_run_abc", role="Planner")
        p, lc, tr = _bucket_rows([planner])

        assert p is planner
        assert lc == []
        assert tr == {}

    def test_lifecycle_rows_separated(self) -> None:
        """bootstrap / planner_started / pipeline_failed rows land in lifecycle_rows."""
        from app.services.history_runs import _bucket_rows

        bootstrap = _make_row(task_id="bootstrap_abc", role="System")
        started = _make_row(task_id="planner_started_abc", role="System")
        failed = _make_row(task_id="pipeline_failed_abc", role="System")

        _, lc, tr = _bucket_rows([bootstrap, started, failed])

        assert len(lc) == 3
        assert tr == {}

    def test_standard_task_row_bucketed(self) -> None:
        """A standard task row is bucketed under its own task_id."""
        from app.services.history_runs import _bucket_rows

        row = _make_row(task_id="research_1", role="Researcher", result={"summary": "ok"})
        _, _, tr = _bucket_rows([row])

        assert "research_1" in tr
        assert tr["research_1"] == [row]

    def test_debate_round_row_bucketed_under_parent_via_progress(self) -> None:
        """A Debate round row with progress.parent_task_id lands under the parent bucket."""
        from app.services.history_runs import _bucket_rows

        round_row = _make_row(
            task_id="debate_1:round1:Advocate",
            role="Advocate",
            progress={"parent_task_id": "debate_1"},
        )
        _, _, tr = _bucket_rows([round_row])

        assert "debate_1" in tr
        assert tr["debate_1"] == [round_row]
        assert "debate_1:round1:Advocate" not in tr

    def test_debate_round_row_bucketed_under_parent_via_regex(self) -> None:
        """A Debate round row without progress falls back to regex task_id parsing."""
        from app.services.history_runs import _bucket_rows

        round_row = _make_row(
            task_id="debate_1:round2:Disrupter",
            role="Disrupter",
            progress=None,
        )
        _, _, tr = _bucket_rows([round_row])

        assert "debate_1" in tr
        assert "debate_1:round2:Disrupter" not in tr

    def test_planner_row_not_in_task_records(self) -> None:
        """The Planner topology row must never appear in task_records."""
        from app.services.history_runs import _bucket_rows

        planner = _make_row(task_id="planner_run_abc", role="Planner")
        standard = _make_row(task_id="task_1", role="Agent")

        _, _, tr = _bucket_rows([planner, standard])

        assert "planner_run_abc" not in tr
        assert "task_1" in tr


# ---------------------------------------------------------------------------
# TestDeriveTaskStatus
# ---------------------------------------------------------------------------

class TestDeriveTaskStatus:
    """_derive_task_status returns the correct TaskStatus for a set of rows."""

    def _call(self, rows: list[MagicMock]):  # noqa: ANN201
        from app.services.history_runs import _derive_task_status
        from app.schemas import TaskStatus

        return _derive_task_status(rows), TaskStatus

    def test_failure_status_field_returns_failed(self) -> None:
        row = _make_row(result={"status": "failed"})
        status, TaskStatus = self._call([row])
        assert status == TaskStatus.failed

    def test_error_field_returns_failed(self) -> None:
        row = _make_row(result={"error": "something went wrong"})
        status, TaskStatus = self._call([row])
        assert status == TaskStatus.failed

    def test_real_agent_result_returns_completed(self) -> None:
        """A result with no lifecycle-status field means a completed agent output."""
        row = _make_row(result={"summary": "Analysis complete.", "details": []})
        status, TaskStatus = self._call([row])
        assert status == TaskStatus.completed

    def test_progress_only_returns_running(self) -> None:
        row = _make_row(result=None, progress={"step": 1, "total": 3})
        status, TaskStatus = self._call([row])
        assert status == TaskStatus.running

    def test_no_result_no_progress_returns_pending(self) -> None:
        row = _make_row(result=None, progress=None)
        status, TaskStatus = self._call([row])
        assert status == TaskStatus.pending


# ---------------------------------------------------------------------------
# TestDeriveRunStatus
# ---------------------------------------------------------------------------

class TestDeriveRunStatus:
    """_derive_run_status returns the correct RunStatus for a run's row buckets."""

    def _call(self, lifecycle, task_records, dag_ids):  # noqa: ANN201
        from app.services.history_runs import _derive_run_status
        from app.schemas import RunStatus

        return _derive_run_status(lifecycle, task_records, dag_ids), RunStatus

    def test_lifecycle_failure_returns_failed(self) -> None:
        lc = [_make_row(result={"status": "planner-failed", "error": "boom"})]
        status, RunStatus = self._call(lc, {}, [])
        assert status == RunStatus.failed

    def test_task_row_with_error_returns_failed(self) -> None:
        row = _make_row(result={"error": "task crashed"})
        status, RunStatus = self._call([], {"task_1": [row]}, ["task_1"])
        assert status == RunStatus.failed

    def test_bootstrap_lifecycle_row_returns_queued(self) -> None:
        lc = [_make_row(task_id="bootstrap_abc", result={"status": "queued"})]
        status, RunStatus = self._call(lc, {}, [])
        assert status == RunStatus.queued

    def test_planner_started_lifecycle_row_returns_running(self) -> None:
        lc = [_make_row(task_id="planner_started_abc", result={"status": "planner-started"})]
        status, RunStatus = self._call(lc, {}, [])
        assert status == RunStatus.running

    def test_all_dag_tasks_completed_returns_completed(self) -> None:
        row = _make_row(task_id="task_1", result={"summary": "done"})
        status, RunStatus = self._call([], {"task_1": [row]}, ["task_1"])
        assert status == RunStatus.completed

    def test_partial_dag_task_completion_returns_running(self) -> None:
        """When task_2 has no rows yet, the run is still running."""
        row = _make_row(task_id="task_1", result={"summary": "done"})
        status, RunStatus = self._call([], {"task_1": [row]}, ["task_1", "task_2"])
        assert status == RunStatus.running


# ---------------------------------------------------------------------------
# TestFindTerminalResult
# ---------------------------------------------------------------------------

class TestFindTerminalResult:
    """_find_terminal_result selects the correct canonical final result for a run."""

    def test_terminal_dag_task_result_selected(self) -> None:
        """The task not referenced as a parent_id is the terminal task."""
        from app.services.history_runs import _find_terminal_result

        topology = [
            {"task_id": "task_1", "parent_ids": []},
            {"task_id": "task_2", "parent_ids": ["task_1"]},
        ]
        rows_t1 = [_make_row(task_id="task_1", result={"summary": "intermediate"})]
        rows_t2 = [_make_row(task_id="task_2", result={"summary": "final answer"})]
        task_records = {"task_1": rows_t1, "task_2": rows_t2}

        result = _find_terminal_result(topology, task_records, [])

        assert result is not None
        assert result.get("summary") == "final answer"

    def test_multiple_terminal_tasks_returns_first_with_completed_result(self) -> None:
        """When topology has two independent root tasks, pick the first completed one."""
        from app.services.history_runs import _find_terminal_result

        topology = [
            {"task_id": "task_a", "parent_ids": []},
            {"task_id": "task_b", "parent_ids": []},
        ]
        rows_a = [_make_row(task_id="task_a", result={"summary": "result A"})]
        task_records = {"task_a": rows_a}

        result = _find_terminal_result(topology, task_records, [])

        assert result is not None
        assert result.get("summary") == "result A"

    def test_no_topology_falls_back_to_most_recent_primary_row(self) -> None:
        """Without topology, the most recently created primary completed row is returned."""
        from app.services.history_runs import _find_terminal_result

        older = _make_row(task_id="task_1", result={"summary": "older result"}, created_at=_T1)
        newer = _make_row(task_id="task_2", result={"summary": "newer result"}, created_at=_T2)
        task_records = {"task_1": [older], "task_2": [newer]}

        result = _find_terminal_result([], task_records, [])

        assert result is not None
        assert result.get("summary") == "newer result"

    def test_falls_back_to_lifecycle_failure_payload(self) -> None:
        """When no task result exists, the latest lifecycle failure payload is returned."""
        from app.services.history_runs import _find_terminal_result

        failure_row = _make_row(
            task_id="pipeline_failed_abc",
            result={"status": "planner-failed", "error": "cannot connect"},
            created_at=_T0,
        )
        result = _find_terminal_result([], {}, [failure_row])

        assert result is not None
        assert result.get("status") == "planner-failed"

    def test_no_rows_returns_none(self) -> None:
        from app.services.history_runs import _find_terminal_result

        assert _find_terminal_result([], {}, []) is None


# ---------------------------------------------------------------------------
# TestBuildDisplayTasks — topology present + absent, debate grouping
# ---------------------------------------------------------------------------

class TestBuildDisplayTasks:
    """_build_display_tasks constructs the ordered Display Task list correctly."""

    def test_topology_present_tasks_follow_topology_order(self) -> None:
        """Display Tasks are emitted in the same order as the topology list."""
        from app.services.history_runs import _build_display_tasks

        topology = [
            {"task_id": "task_1", "task_type": "Standard", "role": "Researcher",
             "parent_ids": [], "dynamic_params": {}},
            {"task_id": "task_2", "task_type": "Standard", "role": "Analyst",
             "parent_ids": ["task_1"], "dynamic_params": {}},
        ]
        rows_t1 = [_make_row(task_id="task_1", result={"summary": "research done"})]
        rows_t2 = [_make_row(task_id="task_2", result={"summary": "analysis done"})]
        task_records = {"task_1": rows_t1, "task_2": rows_t2}

        tasks = _build_display_tasks(topology, task_records)

        assert [t.task_id for t in tasks] == ["task_1", "task_2"]

    def test_planner_row_absent_from_display_task_list(self) -> None:
        """_bucket_rows must exclude the Planner row; _build_display_tasks never sees it."""
        from app.services.history_runs import _bucket_rows, _build_display_tasks

        planner = _make_row(task_id="planner_run_abc", role="Planner",
                            result={"tasks": [
                                {"task_id": "task_1", "task_type": "Standard",
                                 "role": "A", "parent_ids": [], "dynamic_params": {}},
                            ]})
        agent = _make_row(task_id="task_1", role="A", result={"summary": "ok"})

        planner_row, _, task_records = _bucket_rows([planner, agent])

        topology = planner_row.result.get("tasks", [])
        tasks = _build_display_tasks(topology, task_records)

        task_ids = [t.task_id for t in tasks]
        assert "planner_run_abc" not in task_ids
        assert "task_1" in task_ids

    def test_debate_sub_records_grouped_under_parent(self) -> None:
        """Debate round rows appear in sub_records of the parent Display Task."""
        from app.services.history_runs import _build_display_tasks
        from app.schemas import TaskStatus

        topology = [
            {"task_id": "debate_1", "task_type": "Debate",
             "participants": ["Advocate", "Disrupter"], "mediator": "Mediator",
             "parent_ids": [], "dynamic_params": {}},
        ]
        primary_row = _make_row(
            task_id="debate_1", role="Debate",
            result={"conclusion": "agreed"}, created_at=_T2,
        )
        round_row_1 = _make_row(
            task_id="debate_1:round1:Advocate", role="Advocate",
            result={"argument": "support"}, progress={"parent_task_id": "debate_1"},
            created_at=_T0,
        )
        round_row_2 = _make_row(
            task_id="debate_1:round1:Disrupter", role="Disrupter",
            result={"argument": "oppose"}, progress={"parent_task_id": "debate_1"},
            created_at=_T1,
        )
        # task_records received by _build_display_tasks are pre-bucketed by _bucket_rows.
        # debate_1 bucket contains the primary summary row and both round rows.
        task_records = {"debate_1": [primary_row, round_row_1, round_row_2]}

        tasks = _build_display_tasks(topology, task_records)

        assert len(tasks) == 1
        dt = tasks[0]
        assert dt.task_id == "debate_1"
        assert dt.task_type == "Debate"
        assert dt.status == TaskStatus.completed
        assert len(dt.sub_records) == 2

    def test_no_topology_debate_inferred_from_round_rows(self) -> None:
        """Without topology, a bucket containing only round rows is inferred as Debate."""
        from app.services.history_runs import _build_display_tasks

        round_row = _make_row(
            task_id="debate_x:round1:Advocate", role="Advocate",
            result={"argument": "test"}, progress={"parent_task_id": "debate_x"},
            created_at=_T1,
        )
        task_records = {"debate_x": [round_row]}

        tasks = _build_display_tasks([], task_records)

        assert len(tasks) == 1
        assert tasks[0].task_type == "Debate"
        assert len(tasks[0].sub_records) == 1

    def test_no_topology_standard_task_has_no_sub_records(self) -> None:
        """Without topology, a flat task bucket produces a Standard Display Task."""
        from app.services.history_runs import _build_display_tasks

        row = _make_row(task_id="task_plain", role="Agent", result={"summary": "done"})
        task_records = {"task_plain": [row]}

        tasks = _build_display_tasks([], task_records)

        assert len(tasks) == 1
        assert tasks[0].task_type == "Standard"
        assert tasks[0].sub_records == []


# ---------------------------------------------------------------------------
# TestAggregateRuns — one summary per run_id
# ---------------------------------------------------------------------------

class TestAggregateRuns:
    """aggregate_runs produces one RunSummary per distinct run_id."""

    def test_one_summary_per_run_id(self) -> None:
        """Multiple rows sharing a run_id collapse into a single RunSummary."""
        from app.services.history_runs import aggregate_runs

        rows = [
            _make_row(run_id="run_1", task_id="task_a",
                      result={"summary": "done"}, created_at=_T0),
            _make_row(run_id="run_1", task_id="task_b",
                      result={"summary": "done"}, created_at=_T1),
            _make_row(run_id="run_2", task_id="task_a",
                      result={"summary": "done"}, created_at=_T2),
        ]
        summaries = aggregate_runs(rows)

        assert {s.run_id for s in summaries} == {"run_1", "run_2"}
        assert len(summaries) == 2

    def test_rows_without_run_id_skipped(self) -> None:
        """Rows with run_id=None are silently ignored."""
        from app.services.history_runs import aggregate_runs

        row = _make_row(run_id=None, task_id="orphan")
        assert aggregate_runs([row]) == []

    def test_summaries_ordered_newest_created_at_first(self) -> None:
        """RunSummary list is ordered by newest run created_at first."""
        from app.services.history_runs import aggregate_runs

        rows = [
            _make_row(run_id="run_old", task_id="t",
                      result={"summary": "old"}, created_at=_T1),
            _make_row(run_id="run_new", task_id="t",
                      result={"summary": "new"}, created_at=_T3),
        ]
        summaries = aggregate_runs(rows)

        assert summaries[0].run_id == "run_new"
        assert summaries[1].run_id == "run_old"

    def test_planner_topology_row_not_counted_in_task_count(self) -> None:
        """task_count is derived from the DAG topology, not from raw row count."""
        from app.services.history_runs import aggregate_runs

        topology_row = _make_row(
            run_id="run_x",
            task_id="planner_run_run_x",
            role="Planner",
            result={"tasks": [
                {"task_id": "task_1", "task_type": "Standard",
                 "role": "A", "parent_ids": [], "dynamic_params": {}},
                {"task_id": "task_2", "task_type": "Standard",
                 "role": "B", "parent_ids": ["task_1"], "dynamic_params": {}},
            ]},
        )
        task_row = _make_row(
            run_id="run_x", task_id="task_1", result={"summary": "ok"},
        )
        summaries = aggregate_runs([topology_row, task_row])

        assert len(summaries) == 1
        # topology has 2 tasks; raw non-planner row count is 1
        assert summaries[0].task_count == 2

    def test_empty_input_returns_empty_list(self) -> None:
        from app.services.history_runs import aggregate_runs

        assert aggregate_runs([]) == []


# ---------------------------------------------------------------------------
# DB-backed tests: GET /history/runs and GET /history/runs/{run_id}
# ---------------------------------------------------------------------------

class TestRunsApiEndpoints:
    """Run-summary and run-detail HTTP endpoints return correct shapes.

    Automatically skipped when DATABASE_URL is not set (via conftest.py).
    """

    def test_runs_list_returns_200_with_array(self, client: object) -> None:
        resp = client.get("/history/runs")
        assert resp.status_code == 200, f"Expected 200; got {resp.status_code}"
        assert isinstance(resp.json(), list)

    def test_runs_detail_returns_404_for_unknown_run_id(self, client: object) -> None:
        resp = client.get("/history/runs/totally_unknown_run_xyzzy_99999")
        assert resp.status_code == 404, f"Expected 404; got {resp.status_code}"

    def test_runs_list_one_summary_per_run_after_insert(self, client: object) -> None:
        """After inserting two rows for the same run_id, exactly one RunSummary appears."""
        from app.database import SessionLocal
        from app.models import History

        run_id = uuid.uuid4().hex
        db = SessionLocal()
        try:
            db.add(History(
                run_id=run_id,
                task_id=f"bootstrap_{run_id}",
                role="System",
                result={"status": "queued"},
            ))
            db.add(History(
                run_id=run_id,
                task_id="task_1",
                role="Agent",
                result={"summary": "unit test result"},
            ))
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        try:
            resp = client.get("/history/runs")
            assert resp.status_code == 200
            matching = [s for s in resp.json() if s["run_id"] == run_id]
            assert len(matching) == 1, (
                f"Expected exactly one RunSummary for run_id={run_id!r}; "
                f"got {len(matching)}"
            )
        finally:
            _cleanup_run(run_id)

    def test_runs_detail_returns_valid_run_detail(self, client: object) -> None:
        """GET /history/runs/{run_id} returns a complete RunDetail payload."""
        from app.database import SessionLocal
        from app.models import History

        run_id = uuid.uuid4().hex
        db = SessionLocal()
        try:
            db.add(History(
                run_id=run_id,
                task_id=f"bootstrap_{run_id}",
                role="System",
                result={"status": "queued"},
            ))
            db.add(History(
                run_id=run_id,
                task_id="task_1",
                role="Researcher",
                result={"summary": "research done"},
            ))
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        try:
            resp = client.get(f"/history/runs/{run_id}")
            assert resp.status_code == 200
            body = resp.json()
            assert body["run_id"] == run_id
            assert "status" in body
            assert "tasks" in body
            assert isinstance(body["tasks"], list)
            # Planner topology row must not surface in the Display Task list
            assert not any("planner" in t["task_id"] for t in body["tasks"]), (
                "Planner topology row must be excluded from the Display Task list."
            )
        finally:
            _cleanup_run(run_id)

    def test_runs_detail_failed_run_status(self, client: object) -> None:
        """A run with a pipeline_failed lifecycle row is reported as status=failed."""
        from app.database import SessionLocal
        from app.models import History

        run_id = uuid.uuid4().hex
        db = SessionLocal()
        try:
            db.add(History(
                run_id=run_id,
                task_id=f"bootstrap_{run_id}",
                role="System",
                result={"status": "queued"},
            ))
            db.add(History(
                run_id=run_id,
                task_id=f"pipeline_failed_{run_id}",
                role="System",
                result={"status": "planner-failed", "error": "inference unreachable"},
            ))
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        try:
            resp = client.get(f"/history/runs/{run_id}")
            assert resp.status_code == 200
            assert resp.json()["status"] == "failed"
        finally:
            _cleanup_run(run_id)

    def test_runs_detail_completed_run_status(self, client: object) -> None:
        """A run whose task row carries a real agent result is reported as status=completed
        through the public GET /history/runs/{run_id} HTTP endpoint."""
        from app.database import SessionLocal
        from app.models import History

        run_id = uuid.uuid4().hex
        db = SessionLocal()
        try:
            db.add(History(
                run_id=run_id,
                task_id=f"bootstrap_{run_id}",
                role="System",
                result={"status": "queued"},
            ))
            db.add(History(
                run_id=run_id,
                task_id="report_task",
                role="ReportSynthesizer",
                # A real agent result has no lifecycle-status field — only content keys.
                result={"summary": "run completed successfully", "details": []},
            ))
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        try:
            resp = client.get(f"/history/runs/{run_id}")
            assert resp.status_code == 200, (
                f"GET /history/runs/{run_id} returned {resp.status_code}"
            )
            assert resp.json()["status"] == "completed", (
                f"Expected status=completed; got {resp.json()['status']!r}. "
                "A run with a real agent result and no failure rows should be completed."
            )
        finally:
            _cleanup_run(run_id)

    def test_runs_summary_running_status(self, client: object) -> None:
        """A run with only a planner_started lifecycle row is reported as status=running
        through the public GET /history/runs HTTP endpoint."""
        from app.database import SessionLocal
        from app.models import History

        run_id = uuid.uuid4().hex
        db = SessionLocal()
        try:
            db.add(History(
                run_id=run_id,
                task_id=f"bootstrap_{run_id}",
                role="System",
                result={"status": "queued"},
            ))
            db.add(History(
                run_id=run_id,
                task_id=f"planner_started_{run_id}",
                role="System",
                result={"status": "planner-started"},
            ))
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        try:
            resp = client.get("/history/runs")
            assert resp.status_code == 200
            matching = [s for s in resp.json() if s["run_id"] == run_id]
            assert len(matching) == 1, (
                f"Expected one RunSummary for run_id={run_id!r}; got {len(matching)}"
            )
            assert matching[0]["status"] == "running", (
                f"Expected status=running for a planner_started run; "
                f"got {matching[0]['status']!r}."
            )
        finally:
            _cleanup_run(run_id)


# ---------------------------------------------------------------------------
# DB-backed tests: raw history endpoints remain backward-compatible
# ---------------------------------------------------------------------------

class TestRawHistoryCompatibility:
    """GET /history and POST /history still work after the additive run-endpoint changes."""

    def test_get_history_returns_200_with_array(self, client: object) -> None:
        resp = client.get("/history")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_post_history_creates_row(self, client: object) -> None:
        run_id = uuid.uuid4().hex
        try:
            resp = client.post("/history", json={
                "run_id": run_id,
                "task_id": "compat_test_task",
                "role": "CompatAgent",
                "result": {"summary": "compatibility check"},
            })
            assert resp.status_code == 201, (
                f"POST /history returned {resp.status_code}"
            )
            body = resp.json()
            assert body["run_id"] == run_id
            assert body["task_id"] == "compat_test_task"
        finally:
            _cleanup_run(run_id)

    def test_get_history_filter_by_run_id_still_works(self, client: object) -> None:
        """GET /history?run_id= returns raw task rows for the specified run."""
        from app.database import SessionLocal
        from app.models import History

        run_id = uuid.uuid4().hex
        db = SessionLocal()
        try:
            db.add(History(
                run_id=run_id,
                task_id="raw_compat_task",
                role="RawConsumer",
                result={"status": "queued"},
            ))
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        try:
            resp = client.get(f"/history?run_id={run_id}")
            assert resp.status_code == 200
            rows = resp.json()
            assert len(rows) >= 1, (
                f"GET /history?run_id={run_id!r} returned no rows for a known run_id"
            )
            assert all(r["run_id"] == run_id for r in rows)
        finally:
            _cleanup_run(run_id)


# ---------------------------------------------------------------------------
# Frontend source-code verification (no server or JS framework required)
# ---------------------------------------------------------------------------

_FRONTEND_SRC = Path(__file__).parent.parent.parent / "frontend" / "src"


class TestFrontendSourceVerification:
    """Static source-code checks for frontend UI behaviour contracts.

    Parses TypeScript/TSX source files to confirm that:

    - The dashboard uses the run-summary API (not raw task rows).
    - Dashboard run items link to the detail screen by run_id.
    - Task detail panels default to collapsed (useState(false)).
    - The detail screen fetches from the run-detail endpoint.

    No running server or JavaScript test framework is required.
    """

    def test_dashboard_uses_run_summary_api(self) -> None:
        """page.tsx must fetch from /api/history/runs, not /api/history directly."""
        page_src = (_FRONTEND_SRC / "app" / "page.tsx").read_text(encoding="utf-8")
        assert "/api/history/runs" in page_src, (
            "Dashboard must call the run-summary endpoint /api/history/runs. "
            "Verify frontend/src/app/page.tsx."
        )

    def test_dashboard_swr_hook_targets_run_summaries(self) -> None:
        """The SWR hook for the history list in page.tsx must use RunSummary[]."""
        page_src = (_FRONTEND_SRC / "app" / "page.tsx").read_text(encoding="utf-8")
        assert "RunSummary" in page_src, (
            "Dashboard SWR data fetch must type the response as RunSummary[]. "
            "Verify frontend/src/app/page.tsx."
        )

    def test_dashboard_links_to_detail_screen_by_run_id(self) -> None:
        """The history-list run items must navigate to /history/{run.run_id}, not just
        any /history/ template literal (the post-submit success banner is a separate link).
        """
        page_src = (_FRONTEND_SRC / "app" / "page.tsx").read_text(encoding="utf-8")
        # The history-list link uses `run.run_id` while the submit-success banner uses
        # `submittedRunId`.  Both contain "/history/${", so we must assert the history-
        # list–specific identifier to avoid a false positive.
        assert "/history/${run.run_id}" in page_src, (
            "The history-list row link must use run.run_id in its href "
            "(href={`/history/${run.run_id}`}). "
            "Check the Link href inside data.map() in frontend/src/app/page.tsx."
        )

    def test_post_submit_links_to_detail_screen(self) -> None:
        """After submission, the success area must offer a link to the detail screen."""
        page_src = (_FRONTEND_SRC / "app" / "page.tsx").read_text(encoding="utf-8")
        # The post-submit success block links to /history/${submittedRunId}
        assert "submittedRunId" in page_src, (
            "Dashboard must track the submitted run_id to link to the detail screen. "
            "Verify frontend/src/app/page.tsx."
        )

    def test_task_detail_panels_default_collapsed(self) -> None:
        """TaskCard must initialise its open state with useState(false).

        This test checks the TaskCard function body specifically, not just any
        component in the file, to guard against a DebateRoundRow occurrence
        masking a regression where TaskCard starts open.
        """
        import re

        detail_src = (
            _FRONTEND_SRC / "app" / "history" / "[run_id]" / "page.tsx"
        ).read_text(encoding="utf-8")

        # Locate the TaskCard function and extract its body up to the next
        # top-level function declaration so we operate on TaskCard only.
        m = re.search(r"function TaskCard\b", detail_src)
        assert m is not None, (
            "TaskCard component not found in "
            "frontend/src/app/history/[run_id]/page.tsx."
        )
        task_card_text = detail_src[m.start():]
        # Stop at the next top-level 'function ' that starts on a new line
        # so we don't accidentally read the next component's state.
        next_fn = re.search(r"\nfunction [A-Za-z]", task_card_text[1:])
        if next_fn:
            task_card_text = task_card_text[: next_fn.start() + 1]

        assert "useState(false)" in task_card_text, (
            "TaskCard must use useState(false) so task detail panels start "
            "collapsed on first render. "
            "Check the TaskCard body in frontend/src/app/history/[run_id]/page.tsx."
        )

    def test_task_cards_toggle_independently(self) -> None:
        """Each TaskCard must toggle its own open state independently.

        Independent expand/collapse is guaranteed when the toggle handler
        calls setOpen with a callback (v) => !v bound to the local state
        variable rather than a shared flag.
        """
        import re

        detail_src = (
            _FRONTEND_SRC / "app" / "history" / "[run_id]" / "page.tsx"
        ).read_text(encoding="utf-8")

        m = re.search(r"function TaskCard\b", detail_src)
        assert m is not None, "TaskCard component not found."
        task_card_text = detail_src[m.start():]
        next_fn = re.search(r"\nfunction [A-Za-z]", task_card_text[1:])
        if next_fn:
            task_card_text = task_card_text[: next_fn.start() + 1]

        # The toggle must use a functional update so each card's open state is
        # independent of all other cards on the page.
        assert "setOpen((v)" in task_card_text or "setOpen((v) =>" in task_card_text, (
            "TaskCard must toggle its state via a functional update such as "
            "setOpen((v) => !v) so each card opens and closes independently. "
            "Check the onClick handler in frontend/src/app/history/[run_id]/page.tsx."
        )

    def test_detail_screen_fetches_run_detail_endpoint(self) -> None:
        """Detail page must fetch from /api/history/runs/{run_id}."""
        detail_src = (
            _FRONTEND_SRC / "app" / "history" / "[run_id]" / "page.tsx"
        ).read_text(encoding="utf-8")
        assert "history/runs/" in detail_src, (
            "Detail screen must fetch from /api/history/runs/{run_id}. "
            "Check frontend/src/app/history/[run_id]/page.tsx."
        )

    def test_detail_screen_route_file_exists(self) -> None:
        """The detail screen route file must exist at the expected path."""
        detail_page = _FRONTEND_SRC / "app" / "history" / "[run_id]" / "page.tsx"
        assert detail_page.exists(), (
            f"Detail screen route file not found at {detail_page}. "
            "Step 4 must create frontend/src/app/history/[run_id]/page.tsx."
        )

    def test_detail_screen_handles_not_found_state(self) -> None:
        """Detail page must include a not-found / 404 handling branch."""
        detail_src = (
            _FRONTEND_SRC / "app" / "history" / "[run_id]" / "page.tsx"
        ).read_text(encoding="utf-8")
        assert "not_found" in detail_src or "404" in detail_src, (
            "Detail screen must handle the not-found state (404 from backend). "
            "Check frontend/src/app/history/[run_id]/page.tsx."
        )


# ---------------------------------------------------------------------------
# Integration tests (require full stack at localhost)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestFrontendIntegration:
    """End-to-end checks against the running frontend (port 3000) and backend (port 8001).

    Run explicitly::

        pytest tests/ -v -m integration
    """

    def test_dashboard_page_loads(self) -> None:
        """GET http://localhost:3000/ returns 200 with HTML."""
        import httpx

        resp = httpx.get("http://localhost:3000/", follow_redirects=True, timeout=10.0)
        assert resp.status_code == 200, f"Dashboard returned {resp.status_code}"
        ct = resp.headers.get("content-type", "")
        assert "html" in ct.lower() or resp.text.strip().startswith("<"), (
            f"Response from / does not look like HTML. Content-Type: {ct!r}"
        )

    def test_history_detail_route_reachable_for_any_run_id(self) -> None:
        """GET /history/{run_id} renders a Next.js page (200) even for non-existent runs."""
        import httpx

        resp = httpx.get(
            "http://localhost:3000/history/nonexistent_run_id_for_integration_test",
            follow_redirects=True,
            timeout=10.0,
        )
        assert resp.status_code == 200, (
            f"Detail route returned {resp.status_code}. "
            "Next.js should render a not-found state, not a hard HTTP 404."
        )

    def test_runs_summary_api_via_frontend_proxy(self) -> None:
        """GET /api/history/runs via the frontend proxy returns a JSON array."""
        import httpx

        resp = httpx.get("http://localhost:3000/api/history/runs", timeout=10.0)
        assert resp.status_code == 200, (
            f"/api/history/runs returned {resp.status_code}"
        )
        data = resp.json()
        assert isinstance(data, list), f"Expected list; got {type(data).__name__}"

    def test_run_detail_api_returns_404_for_unknown_run(self) -> None:
        """GET /api/history/runs/{run_id} returns 404 for an unknown run_id."""
        import httpx

        resp = httpx.get(
            "http://localhost:3000/api/history/runs/totally_unknown_run_id_xyzzy",
            timeout=10.0,
        )
        assert resp.status_code == 404, (
            f"Expected 404 for unknown run_id; got {resp.status_code}"
        )

    def test_backend_runs_summary_endpoint_direct(self) -> None:
        """GET http://localhost:8001/history/runs returns a JSON array directly."""
        import httpx

        resp = httpx.get("http://localhost:8001/history/runs", timeout=10.0)
        assert resp.status_code == 200, (
            f"Backend /history/runs returned {resp.status_code}"
        )
        assert isinstance(resp.json(), list)
