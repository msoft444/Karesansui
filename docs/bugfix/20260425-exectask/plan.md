# Plan phase 1: Fix exectask issue (2026-04-25)

## Step 1: Make every accepted run visible immediately

### Target
- `backend/app/routers/query.py`
- `backend/app/tasks.py`
- `backend/app/orchestrator/manager.py`

### Req
- Persist at least one durable `History` record for every accepted `run_id` before planner inference can fail.
- Ensure the initial record clearly represents the run lifecycle entry point, such as queued, planner-started, or bootstrap-failed.
- Record planner and orchestration failures against the same `run_id` even when no downstream DAG task completes successfully.
- Keep the existing `POST /query/` response contract unchanged: the endpoint must still return `202 Accepted` with `run_id` immediately.

### Constrain
- Avoid adding a new schema or migration unless the current `result` and `progress` JSON fields cannot represent the required lifecycle states cleanly.
- Do not block the HTTP request on planner completion, worker completion, or any external inference call.
- Prevent duplicate bootstrap rows when the Celery pipeline retries the same run after an early failure.

## Step 2: Surface early failures in history and live trace

### Target
- `backend/app/routers/history.py`
- `backend/app/routers/stream.py`
- `frontend/src/app/page.tsx`
- `frontend/src/components/LiveTrace.tsx`

### Req
- Ensure `GET /history` and `GET /stream/progress` expose queued, planner-started, planner-failed, and orchestration-failed states for a submitted `run_id`.
- Update the dashboard and live trace rendering so a failed or stalled run is shown as a visible lifecycle event instead of remaining empty forever.
- Keep existing successful task records readable alongside the new bootstrap and failure records.
- Ensure the UI can distinguish between "no run submitted yet" and "run submitted but failed before task execution became visible."

### Constrain
- Preserve existing endpoint paths and basic response compatibility for current frontend consumers.
- Do not require manual refresh beyond the current polling and SSE behavior already used by the UI.
- Keep the rendering logic backward-compatible with older history rows that may not contain the new lifecycle payload shape.

## Step 3: Align the served frontend with the checked-out source

### Target
- `frontend/src/app/page.tsx`
- `frontend/src/app/workers/page.tsx`
- `frontend/package.json`
- Frontend production build and startup flow used by `next start`

### Req
- Ensure the production build actually contains the latest dashboard screen, including the new-task submission form.
- Verify that the new-task input remains visible after a submission in the served application, not only in the source tree.
- Verify that the workers screen reflects the backend polling endpoints after the frontend is rebuilt.
- Remove the stale-build gap between the checked-out source and the `.next` output that `next start` serves.

### Constrain
- Do not implement a UI-only workaround that leaves the production build or startup workflow inconsistent.
- Preserve the current routes and Japanese UI strings already defined in the frontend source.
- Keep the local build and startup flow simple enough for the existing macOS + Docker development setup.

## Step 4: Make inference-backend failures diagnosable instead of silent

### Target
- `docker-compose.yml`
- `backend/app/llm/structured_output.py`
- `backend/app/llm/inference_client.py`
- Any runtime documentation that defines how the inference backend must be started

### Req
- Confirm that both `backend` and `worker` use a reachable `INFERENCE_API_BASE_URL` in the supported local environment.
- When the inference backend is unreachable, convert that failure into a user-visible run-level error record tied to the existing `run_id`.
- Preserve enough diagnostic detail in logs and persisted history to distinguish connectivity failures from planner validation failures and downstream task failures.
- Verify the runtime behavior from inside the containers, because the failure is caused by container-to-host reachability rather than browser-to-backend reachability.

### Constrain
- Do not hardcode machine-specific fallback addresses beyond the documented local setup.
- Preserve environment-variable-based configuration so the stack remains portable across local environments.
- Do not mask infrastructure failures as successful runs or silently swallow the error path.

## Step 5: Add regression coverage and focused verification

### Target
- Focused backend regression tests for query submission and early history visibility
- Focused frontend verification for the dashboard and workers pages
- Minimal end-to-end checks for `POST /query/`, `GET /history`, `GET /stream/progress`, and worker polling

### Req
- Add a regression check proving that a submitted `run_id` creates at least one visible history or stream record even when planner inference fails immediately.
- Add a verification step proving that the rebuilt frontend still shows the new-task form after the first submission.
- Re-run a narrow end-to-end scenario that covers three user-visible surfaces: execution history, live trace, and worker activity.
- Verify both the success path and the early infrastructure-failure path, because the bug report includes a silent failure state rather than only a successful execution path.

### Constrain
- Prefer narrow tests, mocks, or targeted checks instead of broad suites that depend on a live external inference service.
- Keep the verification procedure reproducible on the current local macOS + Docker setup.
- Do not expand the scope into unrelated orchestration features, knowledge-base flows, or general frontend redesign work.
