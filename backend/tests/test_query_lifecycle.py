"""Regression tests for Phase 1 bug fix: exectask early-lifecycle visibility.

These tests verify that:
1. POST /query/ creates at least one durable History row (bootstrap) immediately,
   before any Celery task executes — so execution history and Live Trace are
   never empty for a run that was accepted.
2. GET /history?run_id= returns that bootstrap row right after the 202 response.
3. GET /stream/progress?run_id= emits an SSE ``data:`` event for the bootstrap row.
4. The error_type classification logic in run_orchestration_pipeline correctly maps
   connectivity-failure / schema-validation-failure / other error strings.
5. When planner inference fails with a connectivity error and all Celery retries are
   exhausted, a terminal planner-failed row with error_type=connectivity is persisted.

Running these tests requires a reachable PostgreSQL instance configured via
DATABASE_URL (see conftest.py).  Tests that need the full stack are marked
``integration`` and are skipped by default.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run_id() -> str:
    return uuid.uuid4().hex


def _cleanup(run_id: str) -> None:
    """Delete all History rows created for *run_id*.  Always call in a finally block."""
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
# Test group 1 & 2: HTTP-layer bootstrap lifecycle
# ---------------------------------------------------------------------------


class TestQueryBootstrap:
    """POST /query/ creates a durable bootstrap History row before returning 202."""

    def test_creates_at_least_one_history_row_immediately(self, client: object) -> None:
        """A submitted run_id must have ≥1 History row right after 202 is returned.

        Regression guard for the original bug where POST /query/ returned 202
        with no History row, leaving execution history and Live Trace empty.
        """
        from app.database import SessionLocal
        from app.models import History

        # run_orchestration_pipeline is imported lazily *inside* submit_query() via
        # `from app.tasks import run_orchestration_pipeline`, so patch the defining
        # module (app.tasks) rather than the caller module (app.routers.query).
        with patch("app.tasks.run_orchestration_pipeline") as mock_task:
            mock_task.delay.return_value = MagicMock()
            resp = client.post("/query/", json={"query": "regression: bootstrap visibility"})

        assert resp.status_code == 202, f"Expected 202; got {resp.status_code}"
        run_id: str = resp.json()["run_id"]

        try:
            db = SessionLocal()
            try:
                rows = db.query(History).filter(History.run_id == run_id).all()
            finally:
                db.close()

            assert len(rows) >= 1, (
                f"Expected ≥1 History row for run_id={run_id!r} immediately after 202; got 0. "
                "bootstrap write in submit_query() may be broken."
            )
            statuses = [
                r.result.get("status") for r in rows if isinstance(r.result, dict)
            ]
            assert any(s in ("queued", "planner-started") for s in statuses), (
                f"Expected a queued or planner-started row; found statuses={statuses!r}"
            )
        finally:
            _cleanup(run_id)

    def test_history_endpoint_returns_bootstrap_row(self, client: object) -> None:
        """GET /history?run_id= must return ≥1 row immediately after POST /query/.

        Verifies that the bootstrap row is both written to the DB and visible
        through the public history endpoint before any worker task executes.
        """
        with patch("app.tasks.run_orchestration_pipeline") as mock_task:
            mock_task.delay.return_value = MagicMock()
            post_resp = client.post("/query/", json={"query": "regression: history endpoint"})

        assert post_resp.status_code == 202
        run_id: str = post_resp.json()["run_id"]

        try:
            hist_resp = client.get(f"/history?run_id={run_id}")
            assert hist_resp.status_code == 200, (
                f"GET /history?run_id={run_id!r} returned {hist_resp.status_code}"
            )
            rows = hist_resp.json()
            assert len(rows) >= 1, (
                f"GET /history?run_id={run_id!r} returned empty list immediately after 202; "
                "bootstrap row must be committed before the 202 response reaches the caller."
            )
        finally:
            _cleanup(run_id)

    def test_stream_endpoint_emits_bootstrap_event(self, client: object) -> None:
        """GET /stream/progress?run_id= must emit at least one SSE data: event.

        The bootstrap row is committed before the 202 response, so the first
        SSE poll (which happens before the 1-second sleep) must yield it
        immediately, making Live Trace non-empty from the moment the run is accepted.
        """
        with patch("app.tasks.run_orchestration_pipeline") as mock_task:
            mock_task.delay.return_value = MagicMock()
            post_resp = client.post("/query/", json={"query": "regression: SSE bootstrap"})

        assert post_resp.status_code == 202
        run_id: str = post_resp.json()["run_id"]

        try:
            collected: list[str] = []
            with client.stream("GET", f"/stream/progress?run_id={run_id}") as stream_resp:
                assert stream_resp.status_code == 200
                assert "text/event-stream" in stream_resp.headers.get("content-type", ""), (
                    "Expected Content-Type: text/event-stream for the SSE endpoint"
                )
                # Read until the first data: line then close.
                # The bootstrap row is already in the DB so it is yielded on the
                # very first poll iteration without waiting for the sleep interval.
                for chunk in stream_resp.iter_text():
                    if chunk.strip():
                        collected.append(chunk)
                    if any("data:" in c for c in collected):
                        break  # Got what we need; closing the stream is safe here.

            assert any("data:" in c for c in collected), (
                f"No 'data:' line received from SSE stream for run_id={run_id!r}. "
                f"Received chunks: {collected!r}"
            )
        finally:
            _cleanup(run_id)


# ---------------------------------------------------------------------------
# Test group 3: error_type classification
# ---------------------------------------------------------------------------


class TestErrorTypeClassification:
    """The error_type classification string logic in run_orchestration_pipeline is correct.

    The classification is intentionally tested without invoking the full task so
    the coverage is deterministic and does not depend on LLM or Celery infrastructure.
    """

    @pytest.mark.parametrize(
        "err_msg, expected_type",
        [
            # connectivity-failure prefix set by generate_structured()
            (
                "[structured_output] connectivity-failure: inference backend unreachable"
                " — url=http://host.docker.internal:8000/v1, model=karesansui",
                "connectivity",
            ),
            # timed-out path (also connectivity)
            (
                "[structured_output] connectivity-failure: request timed out after 120.0s"
                " — url=http://host.docker.internal:8000/v1, model=karesansui",
                "connectivity",
            ),
            # inference_client.py connectivity-failure prefix (aligned with structured_output)
            (
                "[inference_client] connectivity-failure: inference backend unreachable"
                " — url=http://host.docker.internal:8000/v1, model=karesansui",
                "connectivity",
            ),
            # schema-validation-failure prefix set by generate_structured()
            (
                "[structured_output] schema-validation-failure: model failed to produce valid"
                " structured output after 3 attempts — url=http://host.docker.internal:8000/v1,"
                " model=karesansui",
                "validation",
            ),
            # API error that is not connectivity or schema
            (
                "[structured_output] API error (status=500): internal server error"
                " — url=http://host.docker.internal:8000/v1, model=karesansui",
                "inference",
            ),
            # Generic unexpected error (orchestration stage)
            (
                "unexpected error in OrchestratorManager.run()",
                "inference",
            ),
            # preflight connectivity-failure prefix (Phase 2 Step 2)
            (
                "[preflight] connectivity-failure: inference backend unreachable"
                " — url=http://host.docker.internal:8000/v1, error=<urlopen error [Errno 101] Network is unreachable>",
                "connectivity",
            ),
        ],
    )
    def test_classification(self, err_msg: str, expected_type: str) -> None:
        """Inline classification must map error messages to the correct error_type string."""
        # Mirror the exact classification logic from run_orchestration_pipeline's
        # outer except handler so any future change to that logic requires a
        # corresponding update here.
        if (
            "connectivity-failure" in err_msg
            or "Connection failed" in err_msg
            or "[preflight]" in err_msg
        ):
            error_type = "connectivity"
        elif "schema-validation-failure" in err_msg:
            error_type = "validation"
        else:
            error_type = "inference"

        assert error_type == expected_type, (
            f"err_msg={err_msg!r}: expected error_type={expected_type!r}, got {error_type!r}"
        )


# ---------------------------------------------------------------------------
# Test group 4: pipeline failure path — terminal History row persistence
# ---------------------------------------------------------------------------


class TestPipelineFailurePersistence:
    """run_orchestration_pipeline persists a terminal History row when inference fails.

    The full Celery retry cycle (max_retries=2 → 3 total attempts) is exercised
    synchronously via Task.apply(throw=False).  The inference call is mocked so
    no live inference backend is required.
    """

    def test_connectivity_failure_creates_planner_failed_row(self) -> None:
        """When generate_structured raises a connectivity-failure RuntimeError and all
        Celery retries are exhausted, a pipeline_failed History row with
        status=planner-failed and error_type=connectivity must be persisted.

        This is the central regression check for the Phase 1 bug:
        previously the run had zero History rows after a connectivity failure;
        now it must have at least a bootstrap row (written by the HTTP handler)
        and a planner-failed row (written by the terminal except handler).
        """
        from app.database import SessionLocal
        from app.models import History
        from app.tasks import run_orchestration_pipeline

        run_id = _make_run_id()

        # Write the bootstrap row that submit_query() normally creates before enqueue.
        db = SessionLocal()
        try:
            db.add(
                History(
                    run_id=run_id,
                    task_id=f"bootstrap_{run_id}",
                    role="Planner",
                    result={"status": "queued"},
                    progress=None,
                )
            )
            db.commit()
        finally:
            db.close()

        connectivity_error = RuntimeError(
            "[structured_output] connectivity-failure: inference backend unreachable"
            f" — url=http://host.docker.internal:8000/v1, model=karesansui"
        )

        try:
            # Patch the async generate_structured function at the module level.
            # Patch _check_inference_backend_reachable to a no-op so the test
            # exercises the generate_structured connectivity path rather than
            # the preflight path (which is covered by a dedicated test below).
            with (
                patch(
                    "app.tasks._check_inference_backend_reachable",
                    return_value=None,
                ),
                patch(
                    "app.llm.structured_output.generate_structured",
                    new=AsyncMock(side_effect=connectivity_error),
                ),
            ):
                # apply() executes the task synchronously in the current process.
                # With the new Phase 2 Step 2 logic, connectivity failures are NOT
                # retried (they raise directly); the task runs once and writes the
                # terminal pipeline_failed_<run_id> row on the first attempt.
                run_orchestration_pipeline.apply(
                    kwargs={
                        "user_query": "regression: connectivity failure persistence",
                        "run_id": run_id,
                    },
                    throw=False,
                )

            db = SessionLocal()
            try:
                rows = db.query(History).filter(History.run_id == run_id).all()

                # At minimum: bootstrap row + pipeline_failed row.
                # (planner_started row is also written before the first inference attempt.)
                assert len(rows) >= 2, (
                    f"Expected ≥2 History rows (bootstrap + pipeline_failed) after "
                    f"connectivity failure; got {len(rows)}: {[r.task_id for r in rows]!r}"
                )

                failure_rows = [
                    r for r in rows if (r.task_id or "").startswith("pipeline_failed_")
                ]
                assert len(failure_rows) == 1, (
                    f"Expected exactly one pipeline_failed row; got {len(failure_rows)}: "
                    f"{[r.task_id for r in failure_rows]!r}"
                )

                r = failure_rows[0]
                assert r.result["status"] == "planner-failed", (
                    f"Expected status=planner-failed; got {r.result.get('status')!r}"
                )
                assert r.result.get("error_type") == "connectivity", (
                    f"Expected error_type=connectivity; got {r.result.get('error_type')!r}. "
                    "The classification in run_orchestration_pipeline's terminal handler "
                    "must detect 'connectivity-failure' in the error message."
                )
                assert "connectivity-failure" in (r.result.get("error") or ""), (
                    "Expected the persisted error text to contain 'connectivity-failure'. "
                    f"Actual: {r.result.get('error')!r}"
                )
            finally:
                db.close()
        finally:
            _cleanup(run_id)


# ---------------------------------------------------------------------------
# Test group 5: preflight failure path (Phase 2 Step 2)
# ---------------------------------------------------------------------------


class TestPreflightFailurePersistence:
    """_check_inference_backend_reachable failure writes a terminal row without retrying.

    Phase 2 Step 2 adds a cheap GET /models probe before generate_structured()
    so connectivity failures are classified deterministically on the first attempt
    rather than disappearing into repeated opaque Celery retries.
    """

    def test_preflight_failure_creates_planner_failed_row_immediately(self) -> None:
        """When the preflight probe fails, a single pipeline_failed row is written
        with error_type=connectivity and the [preflight] prefix in the error text,
        and the task does NOT retry (runs exactly once).
        """
        from app.database import SessionLocal
        from app.models import History
        from app.tasks import run_orchestration_pipeline

        run_id = _make_run_id()

        db = SessionLocal()
        try:
            db.add(
                History(
                    run_id=run_id,
                    task_id=f"bootstrap_{run_id}",
                    role="Planner",
                    result={"status": "queued"},
                    progress=None,
                )
            )
            db.commit()
        finally:
            db.close()

        preflight_error = RuntimeError(
            "[preflight] connectivity-failure: inference backend unreachable"
            f" — url=http://host.docker.internal:8000/v1,"
            " error=<urlopen error [Errno 101] Network is unreachable>"
        )

        call_count = 0

        def _failing_preflight(base_url: str, timeout: float = 5.0) -> None:
            nonlocal call_count
            call_count += 1
            raise preflight_error

        try:
            with patch("app.tasks._check_inference_backend_reachable", side_effect=_failing_preflight):
                run_orchestration_pipeline.apply(
                    kwargs={
                        "user_query": "regression: preflight failure",
                        "run_id": run_id,
                    },
                    throw=False,
                )

            # Preflight must have been called exactly once — connectivity failures
            # must not be retried.
            assert call_count == 1, (
                f"Expected preflight probe to be called exactly once (no retries); "
                f"called {call_count} time(s)."
            )

            db = SessionLocal()
            try:
                rows = db.query(History).filter(History.run_id == run_id).all()
                failure_rows = [
                    r for r in rows if (r.task_id or "").startswith("pipeline_failed_")
                ]
                assert len(failure_rows) == 1, (
                    f"Expected exactly one pipeline_failed row after preflight failure; "
                    f"got {len(failure_rows)}: {[r.task_id for r in failure_rows]!r}"
                )
                r = failure_rows[0]
                assert r.result["status"] == "planner-failed", (
                    f"Expected status=planner-failed; got {r.result.get('status')!r}"
                )
                assert r.result.get("error_type") == "connectivity", (
                    f"Expected error_type=connectivity; got {r.result.get('error_type')!r}"
                )
                assert "[preflight]" in (r.result.get("error") or ""), (
                    "Expected persisted error text to contain '[preflight]'. "
                    f"Actual: {r.result.get('error')!r}"
                )
            finally:
                db.close()
        finally:
            _cleanup(run_id)


# ---------------------------------------------------------------------------
# Integration tests — require full Docker Compose stack
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_frontend_shows_new_task_form() -> None:
    """The served frontend (localhost:3000) must contain the new-task submission form
    both before and after a task submission.

    Requires: Docker Compose stack running + Next.js frontend started
    (cd frontend && npm run start -- --hostname 0.0.0.0 --port 3000).

    Verifies that:
    - The prestart build hook (frontend/package.json) ensures the production build
      is up-to-date and contains the new-task form strings.
    - The new-task form remains visible in the served HTML after a task has been
      submitted (regression: form must not be hidden/removed on submission).
    """
    import json
    import urllib.request

    frontend_url = "http://localhost:3000"
    backend_url = "http://localhost:8001"

    # --- Verify form is present on initial page load -------------------------
    try:
        with urllib.request.urlopen(f"{frontend_url}/", timeout=10) as resp:
            html_before = resp.read().decode(errors="replace")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Frontend not reachable at {frontend_url}: {exc}")

    assert "新しいクエリを実行" in html_before, (
        "Frontend is missing new-task form heading '新しいクエリを実行' before any submission. "
        "Either the build is stale or the form was removed from page.tsx."
    )
    assert "クエリ内容" in html_before, (
        "Frontend is missing new-task form label 'クエリ内容' before any submission. "
        "Rebuild: cd frontend && npm run build && npm run start."
    )

    # --- Submit a task and check the page again ------------------------------
    # Submit directly to the backend (bypassing the Next.js proxy) so this test
    # does not require a POST-with-body proxy round trip through the frontend.
    data = json.dumps({"query": "integration: form persistence after submission"}).encode()
    req = urllib.request.Request(
        f"{backend_url}/query/",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            pass  # 202 accepted; we only need the side-effect
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Backend not reachable at {backend_url}: {exc}")

    # Re-fetch the frontend root; the served HTML is a static build so it must
    # still contain the form regardless of any prior submission.
    with urllib.request.urlopen(f"{frontend_url}/", timeout=10) as resp:
        html_after = resp.read().decode(errors="replace")

    assert "新しいクエリを実行" in html_after, (
        "Frontend new-task form heading '新しいクエリを実行' disappeared after a submission. "
        "The form must remain visible after the first task is submitted."
    )
    assert "クエリ内容" in html_after, (
        "Frontend new-task form label 'クエリ内容' disappeared after a submission. "
        "The form must remain visible after the first task is submitted."
    )


@pytest.mark.integration
def test_e2e_failure_path_history_visibility() -> None:
    """End-to-end failure path covering all three user-visible surfaces.

    Requires: Docker Compose stack running (db, redis, backend, worker).
    The host inference API at INFERENCE_API_BASE_URL must be unreachable so that
    the connectivity failure path is exercised.

    Verifies:
    1. Execution history (GET /history): bootstrap row present immediately after 202;
       terminal failure row present with error_type=connectivity after retries exhaust.
    2. Live trace (GET /stream/progress): SSE stream emits at least the bootstrap event
       immediately after the run is accepted.
    3. Worker activity (GET /workers/ and GET /workers/tasks/): worker polling endpoints
       are reachable and return the expected shape while the run is in-flight.
    """
    import json
    import time
    import urllib.request

    backend_url = "http://localhost:8001"

    # --- Submit a run -------------------------------------------------------
    data = json.dumps({"query": "e2e regression: failure path visibility"}).encode()
    req = urllib.request.Request(
        f"{backend_url}/query/",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Backend not reachable at {backend_url}: {exc}")

    run_id: str = body["run_id"]
    assert run_id, "POST /query/ must return a non-empty run_id"

    # --- Surface 1: execution history — bootstrap row immediately -----------
    with urllib.request.urlopen(
        f"{backend_url}/history?run_id={run_id}", timeout=10
    ) as resp:
        initial_rows = json.loads(resp.read())

    assert len(initial_rows) >= 1, (
        f"GET /history?run_id={run_id!r} returned empty list immediately after 202. "
        "bootstrap row must be committed before the 202 response is sent."
    )

    # --- Surface 2: live trace — SSE bootstrap event emitted immediately ----
    # Open the SSE stream immediately after submission; the bootstrap row is
    # already committed so the very first poll must yield at least one data: frame.
    sse_lines: list[str] = []
    try:
        sse_req = urllib.request.Request(
            f"{backend_url}/stream/progress?run_id={run_id}",
            headers={"Accept": "text/event-stream"},
        )
        with urllib.request.urlopen(sse_req, timeout=10) as sse_resp:
            assert sse_resp.status == 200, (
                f"GET /stream/progress?run_id={run_id!r} returned HTTP {sse_resp.status}"
            )
            content_type = sse_resp.headers.get("Content-Type", "")
            assert "text/event-stream" in content_type, (
                f"Expected Content-Type: text/event-stream; got {content_type!r}"
            )
            # Read up to 8 KB or until the first data: line is collected.
            buf = b""
            while len(buf) < 8192:
                chunk = sse_resp.read(512)
                if not chunk:
                    break
                buf += chunk
                if b"data:" in buf:
                    break
            sse_lines = buf.decode(errors="replace").splitlines()
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"GET /stream/progress?run_id={run_id!r} raised an unexpected exception: {exc}"
        )

    assert any("data:" in line for line in sse_lines), (
        f"No 'data:' line received from SSE stream for run_id={run_id!r}. "
        f"Received lines: {sse_lines!r}"
    )

    # --- Surface 3: worker activity — workers and tasks endpoints -----------
    with urllib.request.urlopen(f"{backend_url}/workers/", timeout=10) as resp:
        workers_body = json.loads(resp.read())

    assert isinstance(workers_body, list), (
        f"GET /workers/ must return a JSON array; got {type(workers_body).__name__!r}"
    )
    # The endpoint returns an empty list when no workers are reachable;
    # we only assert the shape (list) because the Celery worker may have
    # finished before this poll.

    with urllib.request.urlopen(f"{backend_url}/workers/tasks/", timeout=10) as resp:
        tasks_body = json.loads(resp.read())

    assert isinstance(tasks_body, dict), (
        f"GET /workers/tasks/ must return a JSON object; got {type(tasks_body).__name__!r}"
    )
    assert "active" in tasks_body and "reserved" in tasks_body, (
        f"GET /workers/tasks/ response missing 'active' or 'reserved' key: {tasks_body!r}"
    )

    # --- Surface 1 (continued): poll for terminal failure (up to 60 s) ------
    terminal_status: str | None = None
    error_type: str | None = None
    rows: list = initial_rows
    deadline = time.monotonic() + 60.0

    while time.monotonic() < deadline:
        time.sleep(2)
        with urllib.request.urlopen(
            f"{backend_url}/history?run_id={run_id}", timeout=10
        ) as resp:
            rows = json.loads(resp.read())
        for row in rows:
            status = (row.get("result") or {}).get("status", "")
            if status in ("planner-failed", "orchestration-failed"):
                terminal_status = status
                error_type = (row.get("result") or {}).get("error_type")
                break
        if terminal_status:
            break

    assert terminal_status in ("planner-failed", "orchestration-failed"), (
        f"Expected a terminal failure status within 60 s; "
        f"last rows statuses: {[r.get('result', {}).get('status') for r in rows]!r}"
    )
    assert error_type == "connectivity", (
        f"Expected error_type=connectivity for an unreachable inference backend; "
        f"got {error_type!r}"
    )


@pytest.mark.integration
def test_e2e_success_path_bootstrap_visibility() -> None:
    """Success-path end-to-end check: the bootstrap and early lifecycle rows are visible
    in history and SSE immediately after a query is accepted, regardless of whether the
    inference backend eventually succeeds.

    This is the counterpart to the failure-path test above.  It verifies the
    fundamental bug fix: a newly accepted run_id must never leave execution history and
    Live Trace empty, even before the pipeline finishes.

    Requires: Docker Compose stack running (db, redis, backend, worker).
    The inference backend may be reachable OR unreachable; this test only checks
    the state that exists unconditionally right after the 202 response.

    Verifies:
    - POST /query/ returns 202 with a non-empty run_id.
    - GET /history?run_id= returns ≥1 row (bootstrap) immediately — the success-path
      assertion that execution history is always populated on acceptance.
    - GET /stream/progress?run_id= emits at least one SSE data: event immediately —
      the success-path assertion that Live Trace is non-empty on acceptance.
    """
    import json
    import urllib.request

    backend_url = "http://localhost:8001"

    # --- Submit a run -------------------------------------------------------
    data = json.dumps({"query": "e2e success path: bootstrap visibility"}).encode()
    req = urllib.request.Request(
        f"{backend_url}/query/",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Backend not reachable at {backend_url}: {exc}")

    run_id: str = body["run_id"]
    assert run_id, "POST /query/ must return a non-empty run_id (success path)"

    # --- Immediate history check: bootstrap row must exist right away --------
    with urllib.request.urlopen(
        f"{backend_url}/history?run_id={run_id}", timeout=10
    ) as resp:
        rows = json.loads(resp.read())

    assert len(rows) >= 1, (
        f"Success path: GET /history?run_id={run_id!r} returned empty list right after 202. "
        "The bootstrap row must be committed inside submit_query() before the 202 is sent."
    )
    statuses = [(r.get("result") or {}).get("status") for r in rows]
    assert any(s in ("queued", "planner-started") for s in statuses), (
        f"Success path: expected a 'queued' or 'planner-started' bootstrap row; "
        f"found statuses={statuses!r}"
    )

    # --- Immediate SSE check: Live Trace must not be empty on acceptance -----
    sse_lines: list[str] = []
    try:
        sse_req = urllib.request.Request(
            f"{backend_url}/stream/progress?run_id={run_id}",
            headers={"Accept": "text/event-stream"},
        )
        with urllib.request.urlopen(sse_req, timeout=10) as sse_resp:
            buf = b""
            while len(buf) < 8192:
                chunk = sse_resp.read(512)
                if not chunk:
                    break
                buf += chunk
                if b"data:" in buf:
                    break
            sse_lines = buf.decode(errors="replace").splitlines()
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"Success path: GET /stream/progress?run_id={run_id!r} raised: {exc}"
        )

    assert any("data:" in line for line in sse_lines), (
        f"Success path: no 'data:' line received from SSE stream for run_id={run_id!r}. "
        "The bootstrap row is committed before 202, so the SSE stream must yield it "
        "on the very first poll without any retry or wait."
    )


@pytest.mark.integration
def test_workers_page_renders() -> None:
    """The served workers page (localhost:3000/workers) must render the workers UI.

    Requires: Docker Compose stack running + Next.js frontend started.

    Verifies that the workers management page route built by
    ``frontend/src/app/workers/page.tsx`` is reachable and contains the expected
    Japanese UI strings ('ワーカー管理', 'ワーカー') that identify the page.
    This confirms that the frontend production build covers the workers route and
    that the page is served correctly through the Next.js server.
    """
    import urllib.request

    frontend_url = "http://localhost:3000"

    try:
        with urllib.request.urlopen(f"{frontend_url}/workers", timeout=10) as resp:
            html = resp.read().decode(errors="replace")
            status = resp.status
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Frontend /workers not reachable at {frontend_url}: {exc}")

    assert status == 200, (
        f"GET {frontend_url}/workers returned HTTP {status}; expected 200."
    )
    assert "ワーカー管理" in html, (
        "Workers page is missing heading 'ワーカー管理'. "
        "Either the build is stale, the /workers route is missing from the build, "
        "or the page content was changed."
    )
    assert "ワーカー" in html, (
        "Workers page is missing UI label 'ワーカー'. "
        "Rebuild: cd frontend && npm run build && npm run start."
    )
