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

# Plan phase 2: Fix Planner connectivity failure (2026-04-25)

## Step 1: Establish a single runtime contract for the host inference backend

### Target
- `docker-compose.yml`
- `backend/app/llm/structured_output.py`
- `backend/app/llm/inference_client.py`
- `README.md`

### Req
- Define one authoritative runtime contract for the host-side inference backend used by both `backend` and `worker`, including the expected base URL, health-check path, and the exact local startup procedure supported by this repository.
- Remove drift between structured and non-structured inference entry points so both code paths classify connectivity, timeout, and API-status failures using the same rules and the same URL source.
- Document the operator-facing startup and verification flow in `README.md`, including the exact host command to start the inference server and the exact host-side and container-side commands to verify reachability before submitting a task.
- Ensure the persisted error text and log text remain stable enough for history consumers, regression tests, and UI status classification to distinguish connectivity failures from schema or orchestration failures.

### Constrain
- Preserve environment-variable-based configuration and keep `http://host.docker.internal:8000/v1` as the documented default local address unless the user explicitly overrides it.
- Do not hardcode machine-specific fallback addresses, hostnames, or secrets into the application code.
- Keep host-inference setup instructions in `README.md` and runtime diagnostics in the backend, rather than scattering setup assumptions across unrelated files.

## Step 2: Detect backend unavailability at the Planner boundary and persist a deterministic failure lifecycle

### Target
- `backend/app/tasks.py`
- `backend/app/routers/query.py`
- Any shared helper introduced for inference-backend readiness checks

### Req
- Add a cheap, deterministic readiness check or equivalent first-failure classification at the Planner boundary so a run does not disappear into repeated opaque retries when the inference backend is unavailable from the worker container.
- Preserve the existing lifecycle sequence for accepted runs: `bootstrap_<run_id>` must remain the submission anchor, `planner_started_<run_id>` must still show that Planner execution began, and a single terminal `pipeline_failed_<run_id>` row must be written when Planner connectivity fails.
- Ensure the terminal Planner failure payload clearly states whether the failure happened during a preflight reachability check or during the first structured Planner request, while keeping the same `run_id` and role semantics already used by history consumers.
- Prevent duplicate terminal failure rows when Celery retries the same Planner task, and keep the success path unchanged when the inference backend is reachable.

### Constrain
- Do not block the HTTP submission endpoint on full Planner completion or downstream orchestration completion.
- Do not introduce a schema migration or a new table if the current `History.result` payload can represent the required Planner lifecycle states.
- Do not treat infrastructure failures as successful submissions, and do not silently drop the final failure state after retries are exhausted.

## Step 3: Surface inference-backend readiness and Planner connectivity failures in the management UI

### Target
- `backend/app/routers/workers.py` or a new backend diagnostics surface if required
- `frontend/src/app/page.tsx`
- `frontend/src/app/workers/page.tsx`
- `frontend/src/components/LiveTrace.tsx`

### Req
- Expose enough backend-side diagnostic state for the frontend to show whether the inference backend is currently reachable from the containerized runtime, without requiring the browser to probe the host inference server directly.
- Render a clear Japanese UI status on the dashboard and/or workers page when task execution is blocked by inference-backend unavailability, so the user can distinguish infrastructure failure from an idle worker or an empty history list.
- Ensure Live Trace and execution-history views show the persisted Planner lifecycle rows in a way that makes `planner-failed` / `connectivity` actionable instead of looking like a blank or stalled run.
- Keep the successful-run presentation intact so the added diagnostics do not drown out normal task progress when the backend is healthy.

### Constrain
- Preserve existing user-facing routes unless an additive API endpoint is strictly necessary for diagnostics.
- Keep all UI strings in Japanese and keep browser behavior compatible with the current polling/SSE model.
- Do not make the frontend depend on direct browser-to-host-network access, because the failure is specifically about container-to-host reachability.

## Step 4: Make the supported local startup path verifiable before task submission

### Target
- `README.md`
- Any local startup helper or task definition already used to boot the frontend/backend stack
- Relevant runtime documentation under `docs/bugfix/20260425-exectask/`

### Req
- Add an explicit pre-submission verification procedure for the supported local environment: start the host inference server, confirm the host-side `/v1/models` endpoint, confirm container-side reachability to `host.docker.internal`, and only then submit a task.
- Document the exact failure signatures observed when the host server is down versus when the container cannot reach the host, so operators can tell whether they are dealing with a missing process, a network-routing problem, or an application-layer error.
- Align the documented startup order with the actual runtime dependency chain: host inference backend first, then Docker services, then frontend submission flow.
- Keep the documentation synchronized with the runtime assumptions used by `docker-compose.yml` and the backend inference clients.

### Constrain
- Do not move host-inference setup into Dockerfiles, container entrypoints, or application boot logic; the host-side service must remain an explicit external prerequisite per the project requirements.
- Do not require manual patching of source files to switch between local machines; the documented flow must rely on environment variables and supported startup commands.
- Keep the procedure concise enough to be used as an operational checklist during `dc` verification.

## Step 5: Add focused regression coverage for Planner connectivity failure and recovery

### Target
- `backend/tests/test_query_lifecycle.py`
- Any narrow backend test module added for inference-backend readiness helpers
- Focused manual verification steps for `POST /query/`, `GET /history`, `GET /workers/`, and Live Trace

### Req
- Add regression coverage proving that an unreachable inference backend produces the expected visible lifecycle for one run: `bootstrap`, `planner_started`, and one terminal `pipeline_failed` row with `status=planner-failed` and `error_type=connectivity`.
- Add a focused check proving that the same code path does not create duplicate terminal failure rows across retries and does not regress the success path when the readiness check passes.
- Add a manual verification sequence that starts from the supported local runtime contract and validates both failure and recovery: first reproduce the Planner connectivity failure, then restore backend reachability and confirm that a new task proceeds beyond Planner.
- Ensure verification explicitly covers the three user-visible surfaces affected by this bug: execution history, Live Trace, and worker/diagnostic visibility.

### Constrain
- Prefer deterministic mocks or narrow integration tests over a broad suite that depends on a real external inference engine.
- Keep manual verification reproducible on the current macOS + Docker setup and scoped to the Planner connectivity scenario.
- Do not broaden the regression plan into unrelated DAG features, knowledge-base ingestion flows, or generic frontend polish.
