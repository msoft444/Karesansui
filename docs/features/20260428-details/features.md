# Feature Requirements: Query Result Details and Task Drill-Down

Date: 2026-04-28
Status: Draft

## 1. Background

- The current history view exposes raw task-level execution records instead of presenting one coherent result per query run.
- Users cannot inspect the final execution result of a query after the orchestration finishes.
- When a query is decomposed into multiple DAG tasks, users cannot inspect each task's execution result from the management console.
- The current DAG page and live trace page provide partial execution visibility, but there is no single detail screen that combines the final query result, task-level drill-down, and DAG for the same run.

## 2. Goal

- Provide a run-oriented history experience where each query execution is treated as one user-visible record.
- Provide a dedicated query result detail screen for each run.
- Allow users to inspect the final query result, the list of executed tasks, each task's parameters and result, and the DAG used in that run.

## 3. Definitions

- Query Run: One orchestration execution identified by a shared `run_id`.
- Final Query Result: The canonical user-facing result for a Query Run. The system should prefer the terminal task result intended as the final report. If such a task is not explicitly identifiable, the system must deterministically derive the final result from the terminal DAG task or the terminal failure state.
- Display Task: One user-visible task item keyed by the Planner's DAG `task_id`. Internal raw history rows may be grouped into one Display Task when the backend generates additional rows for the same DAG task.

## 4. Scope

- In scope:
  - History list redesign from task-oriented rows to run-oriented rows.
  - Dedicated query result detail screen keyed by `run_id`.
  - Task-level result drill-down within the detail screen.
  - DAG display within the detail screen.
- Out of scope:
  - Changes to the orchestration logic itself.
  - Changes to agent prompting strategy.
  - Persisting or displaying the original user query text unless separately required.

## 5. Functional Requirements

### 5.1 Run-Oriented History List

- The execution history list must show one top-level item per Query Run.
- The history list must not show raw task-level rows as top-level records.
- Each history item must include at least:
  - `run_id`
  - execution timestamp
  - run status
  - final query result preview
- The history list may include supporting metadata such as role labels or failure markers, but the primary content must represent the Query Run, not individual tasks.
- History items must be ordered by newest execution first.
- Clicking a history item must navigate to the dedicated query result detail screen for that `run_id`.

### 5.2 Run Status Handling in the History List

- The system must support, at minimum, the following run-level statuses:
  - queued
  - running
  - completed
  - failed
- If a Query Run is still executing and the final result is not yet available, the history item must show its current status and the best available result preview or status message.
- If a Query Run failed, the history item must show a failure state and the latest meaningful error summary.

### 5.3 Query Result Detail Screen

- The system must provide a dedicated detail screen for a selected Query Run.
- The detail screen must be addressable by `run_id`.
- The detail screen must show the following sections for the selected Query Run:
  - final query result
  - executed task list
  - DAG
- If the specified `run_id` does not exist, the screen must show a not-found or empty state.
- If the Query Run is still executing, the detail screen must show the latest available data and clearly indicate that execution is still in progress.

### 5.4 Final Query Result Section

- The detail screen must show the final query result for the selected Query Run.
- The final query result section must display the canonical user-facing output, not a raw list of all task records.
- If the result payload is structured JSON, the UI must render it in a readable form suitable for a user-facing detail page.
- If the run failed before a final result was produced, the final result section must show the failure state and the latest relevant error payload.
- If the run is still in progress, the final result section must show a pending or running state until the final result becomes available.

### 5.5 Executed Task List Section

- The detail screen must show the list of all Display Tasks executed for the selected Query Run.
- The task list must use the Planner DAG `task_id` as the primary user-visible task unit.
- The task list must exclude synthetic metadata rows that exist only to store Planner topology and are not actual executable tasks.
- If the backend stores multiple raw rows for one DAG task, the UI must group them under the owning Display Task rather than showing them as separate top-level tasks.
- This grouping rule is especially required for Debate tasks whose internal rounds may be persisted as separate raw records.
- The task list should be ordered by DAG topology when available. If DAG topology is unavailable, the fallback order may be execution timestamp.

### 5.6 Task Expand/Collapse Behavior

- Every task item in the executed task list must be collapsible.
- On the initial screen load, the detail area for every task must be closed.
- Clicking a task item must expand or collapse that task's detail area.
- Expanding one task must not require expanding all tasks.

### 5.7 Task Detail Content

- Each expanded task detail must show, at minimum:
  - `task_id`
  - task type
  - assigned role, or equivalent participant summary for Debate tasks
  - parent task IDs
  - planner-assigned dynamic parameters, when available
  - execution status
  - execution result payload
- When runtime execution parameters are available, the task detail should also display them. Examples include model name, inference parameters, or runtime metadata captured during execution.
- For Debate tasks, the top-level task detail must show the debate task's aggregated result as the main result. Internal per-round records may be shown inside the same expanded detail area, but they must not be promoted to separate top-level task items.

### 5.8 DAG Section

- The detail screen must show the DAG for the selected Query Run.
- The DAG must correspond to the Planner topology stored for the same `run_id`.
- The DAG view must visually indicate task execution status at minimum for:
  - pending
  - running
  - completed
  - failed
- The DAG section must represent the same task set used by the executed task list so users can understand both the structure and the detailed outputs of the same run.

## 6. Data Requirements

- The system must support run-oriented data retrieval keyed by `run_id`.
- The system must support detail retrieval keyed by `run_id`, including:
  - final query result
  - run status
  - task collection for the run
  - DAG topology for the run
- Run-level aggregation must be deterministic and must not depend on UI timing assumptions.
- The primary grouping keys must be `run_id` for a Query Run and Planner `task_id` for a Display Task.
- If raw history rows use compound task IDs for internal execution steps, the system must map them back to the owning Display Task before presenting them in the detail screen.

## 7. UI and UX Requirements

- All user-facing labels and messages must be in Japanese.
- The history list must optimize for quick scanning of query outcomes rather than detailed task inspection.
- The detail screen must optimize for drill-down inspection without overwhelming the user on initial load.
- Loading, empty, and error states must be defined for both the history list and the detail screen.
- The detail screen must remain usable on both desktop and smaller viewport sizes.

## 8. Acceptance Criteria

- The history list no longer shows one row per raw task execution record.
- The history list shows one item per Query Run and each item is clickable.
- Clicking a history item opens a detail screen for the same `run_id`.
- The detail screen shows the final query result for that run.
- The detail screen shows the executed task list for that run.
- All task details are closed on the initial render.
- A user can expand an individual task and inspect its parameters and execution result.
- The detail screen shows the DAG for the same run.
- Debate-task internal rows do not appear as separate top-level tasks in the task list.