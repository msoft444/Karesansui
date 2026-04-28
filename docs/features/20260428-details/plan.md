# Feature Implementation Plan — 2026-04-28 Query Result Details

When receiving a feature execution command, interpret each Step below as a strict prompt and implement only that Step.

## Step 1: Define a run-oriented read model and deterministic aggregation rules

### Target
- `backend/app/schemas.py`
- new read-model helper such as `backend/app/services/history_runs.py`

### Req
- Define explicit response models for a run-oriented history summary and a run-oriented history detail payload.
- Define a deterministic aggregation layer that converts raw `History` rows into user-visible Query Runs keyed by `run_id`.
- Derive the following values from persisted history data without relying on frontend timing assumptions:
  - run status
  - final query result preview
  - final query result payload
  - ordered Display Task list
- Use the Planner DAG topology as the primary source of task ordering and task membership when it is available.
- Exclude the Planner topology row itself from the user-visible task list while still using it to reconstruct the DAG and task order.
- Group internal raw rows that belong to the same Display Task under the owning Planner `task_id`.
- For Debate tasks, group per-round raw rows under the same top-level Display Task by using persisted metadata such as `progress.parent_task_id`, and fall back to deterministic `task_id` parsing only when required.

### Constrain
- Prefer an additive read-model layer over changes to the existing orchestration write path.
- Do not add a schema migration or a new table unless the current persisted `History` payloads are proven insufficient for deterministic aggregation.
- Preserve compatibility for existing raw history consumers that still depend on task-level rows.

## Step 2: Expose additive run-summary and run-detail APIs without breaking raw history APIs

### Target
- `backend/app/routers/history.py`
- `backend/app/main.py` if router registration changes are required

### Req
- Add a run-summary endpoint for the execution history list, such as `GET /history/runs`, that returns one item per Query Run.
- Add a run-detail endpoint, such as `GET /history/runs/{run_id}`, that returns the full detail payload for one Query Run.
- Ensure the run-detail payload includes at minimum:
  - `run_id`
  - run status
  - final query result payload
  - final result preview or summary
  - ordered Display Task list
  - DAG topology for the same run
- Ensure the backend returns stable not-found, empty, running, completed, and failed states for the detail screen.
- Keep the existing raw history endpoints available for current consumers such as Live Trace and any screens that still operate on raw task rows.

### Constrain
- Do not replace or silently repurpose `GET /history` if that would break existing task-level consumers.
- Keep the new endpoints additive and backward-compatible from the perspective of the current frontend.
- Do not move run aggregation responsibility into the frontend.

## Step 3: Redesign the dashboard history list around Query Runs

### Target
- `frontend/src/app/page.tsx`

### Req
- Replace the current raw task history list on the dashboard with a run-oriented history list backed by the new run-summary API.
- Show one top-level history item per Query Run instead of one row per raw task execution record.
- Display at minimum the following summary fields for each run:
  - `run_id`
  - execution timestamp
  - run status
  - final result preview
- Make each run item clickable and route the user to the dedicated query result detail screen for the selected `run_id`.
- Update the post-submission success area so the primary navigation path leads to the new detail screen for the submitted `run_id`.
- Preserve the existing query submission form and diagnostics banner behavior.

### Constrain
- Keep all UI text in Japanese.
- Do not regress the current query submission flow or remove access to live tracing; the detail screen should become the primary inspection path, not a replacement for all existing routes.
- Keep the dashboard readable when a run is queued, still running, completed, or failed.

## Step 4: Build the dedicated query result detail screen with final result, task drill-down, and DAG

### Target
- new `frontend/src/app/history/[run_id]/page.tsx`
- new supporting UI components if needed for result panels or task drill-down
- `frontend/src/components/DagVisualizer.tsx` if extension is required for reuse in the detail screen

### Req
- Create a dedicated detail screen addressed by `run_id`.
- Fetch the run-detail payload from the new backend endpoint and render three sections on the same screen:
  - final query result
  - executed task list
  - DAG
- Render the final query result as the canonical user-facing output for the run instead of a raw row dump.
- Render the executed task list using the Display Task collection produced by the backend aggregation layer.
- Ensure every task detail panel is collapsed on the initial render.
- Allow the user to independently expand and collapse each task.
- In each expanded task, display task metadata, planner-assigned parameters when available, execution status, runtime metadata when available, and execution result payload.
- For Debate tasks, show the aggregated top-level debate result as the main task result and keep any internal per-round rows inside that same task detail area.
- Render the DAG from the same run-detail payload so the task list and graph reflect the same run and the same task set.

### Constrain
- Reuse the existing DAG visualization logic where practical instead of creating a second DAG rendering path.
- Keep the Planner topology row hidden from the user-visible task list.
- Define clear loading, empty, not-found, and error states, and keep the layout usable on smaller viewports.

## Step 5: Add focused regression coverage and verification for run summaries and detail drill-down

### Target
- focused backend tests for run aggregation and history endpoints
- focused frontend verification for dashboard-to-detail navigation and task expand/collapse behavior

### Req
- Add backend regression coverage for the run-oriented aggregation rules, including:
  - one summary item per `run_id`
  - deterministic final result selection
  - Planner topology row exclusion from the Display Task list
  - Debate internal-row grouping under the owning top-level task
- Add focused verification that the dashboard renders run summaries rather than raw task rows.
- Add focused verification that clicking a run opens the detail screen for the same `run_id`.
- Add focused verification that all task details are closed initially and can be expanded individually.
- Verify completed, running, and failed run states so the new read model works across the existing lifecycle states already stored in history.

### Constrain
- Prefer narrow regression tests and targeted UI checks over broad end-to-end suites that require a live inference backend.
- Preserve compatibility checks for existing raw history consumers where the new feature reuses the same stored data.
- Do not broaden this Step into unrelated orchestration changes, live-trace redesign work, or general dashboard restyling.