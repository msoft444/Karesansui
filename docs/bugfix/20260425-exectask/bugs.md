# Bug Report: exectask (2026-04-25)

## Symptom
- Submitting a new task from the execution history screen returns a `run_id`, but no entry ever appears in execution history and the Live Trace stream stays empty.
- After the first submission, the currently served frontend no longer exposes a usable "new execution" input area, so the user cannot start a second task from the same screen.
- The user-facing Worker Management page can stay empty even while the backend worker is actually processing the orchestration task.

## How to reproduce
1. Start the current stack from `docker-compose.yml` so that `db`, `redis`, `backend`, and `worker` are running, but leave the host inference API at `http://host.docker.internal:8000/v1` unreachable.
2. Open `http://localhost:3000/` with the currently served Next.js production build.
3. Submit a new task. The backend accepts the request with `202 Accepted` and returns a `run_id`.
4. Immediately check the backend APIs for that `run_id`: `GET /history?run_id=<run_id>` returns `[]`, and `GET /stream/progress?run_id=<run_id>` yields no events because no `History` row exists yet.
5. Inspect the worker/backend runtime: `GET /workers/` shows the orchestration task as active, while worker logs contain `InstructorRetryException(APIConnectionError('Connection error.'))` and the backend container cannot reach `http://host.docker.internal:8000/v1/models` (`URLError: [Errno 101] Network is unreachable`).
6. Compare the running frontend with the checked-out source: `frontend/src/app/page.tsx` contains the form strings `新しいクエリを実行` and `クエリ内容`, but the HTML served from `http://localhost:3000/` does not. `frontend/.next/BUILD_ID` is older than `frontend/src/app/page.tsx`, so `next start` is serving a stale build.

## Expected behavior
- A newly submitted run should create at least one durable `History` record immediately (queued, planner-started, or error state), so execution history and Live Trace show that the run has started even if downstream inference fails.
- The Worker Management UI should reflect the active orchestration task through the existing polling endpoints.
- The new-task form should remain visible after submission so another task can be started without rebuilding or reloading stale frontend assets.

## Actual behavior
- `POST /query/` only enqueues the Celery job and returns `run_id`. `run_orchestration_pipeline` performs the planner structured inference before any `History` write occurs. When the inference endpoint is unreachable, the planner fails and retries first, so the run has a valid `run_id` but zero persisted history rows.
- Dynamic analysis confirmed the runtime failure path: `GET /workers/` showed the worker online and the orchestration task active immediately after submission, but `GET /history?run_id=<run_id>` still returned `[]`. Worker logs showed repeated `InstructorRetryException(APIConnectionError('Connection error.'))`, and a direct connectivity test from the backend container to `http://host.docker.internal:8000/v1/models` failed with `URLError: [Errno 101] Network is unreachable`.
- The missing input UI is caused by the currently served frontend build being older than the checked-out source. The source file `frontend/src/app/page.tsx` unconditionally contains the new-task form, but the HTML currently served at `http://localhost:3000/` contains only the older execution-history view (`実行履歴`, `読み込み中...`) and not the form labels (`新しいクエリを実行`, `クエリ内容`). This stale build also explains why the browser can show no worker activity even though the backend `/workers/` endpoint reports an active task.

## Affected files
- `backend/app/routers/query.py` — accepts the request and returns `run_id` before any durable history is written.
- `backend/app/tasks.py` — `run_orchestration_pipeline` calls the planner LLM before emitting the first `History` record.
- `backend/app/orchestrator/manager.py` — the first history persistence (`_persist_planner_dag`) happens only after planner generation succeeds, so early failures are invisible to execution history and Live Trace.
- `backend/app/llm/structured_output.py` and `backend/app/llm/inference_client.py` — orchestration depends on the host inference API and fails hard when that endpoint is unreachable.
- `docker-compose.yml` — `backend` and `worker` default to `INFERENCE_API_BASE_URL=http://host.docker.internal:8000/v1`.
- `frontend/src/app/page.tsx` — current source keeps the new-task form visible, which does not match the page currently served in production mode.
- `frontend/package.json` and `frontend/.next/BUILD_ID` — `next start` serves the existing `.next` output, and the current build is older than the checked-out source.
