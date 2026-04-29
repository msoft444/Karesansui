# Plan: Fix detailedquery issue (2026-04-28) — Revised (7 steps)

## Step 1: Enforce RoleTemplate as the authoritative source and resolve at runtime

### Target
- `backend/app/orchestrator/manager.py`
- `backend/app/orchestrator/debate_controller.py`
- new helper such as `backend/app/services/role_templates.py`

### Req
- Treat `RoleTemplate` records in the database as the authoritative source-of-truth for role prompts, default tools, and default params.
- Resolve and merge the runtime prompt from `system_prompt`, `default_params`, and Planner-provided `dynamic_params` before any inference call.
- When the Planner references an unknown template, fail loudly and record the error in the run `progress` metadata instead of silently falling back to a generic prompt.
- Persist enough runtime metadata so the run history shows which template and which parameter set were used for each task.

### Constrain
- Avoid changing the Planner DAG schema unless an additive runtime field is strictly necessary.
- Do not duplicate prompt text in orchestrator code; assemble prompts from the authoritative template model only.

## Step 2: Introduce a single runtime tool-dispatch contract and layer

### Target
- new helper such as `backend/app/services/tool_dispatch.py`
- `backend/app/orchestrator/manager.py`
- `backend/app/orchestrator/debate_controller.py`

### Req
- Convert a template's `tools` declaration into runtime behavior via a single dispatch layer that centralizes: capability discovery, invocation, output normalization, error classification, and retry/backoff.
- The dispatch layer must provide a stable `ToolResult` shape that is safe to serialize, insert into prompts, and persist for history inspection.
- Record which tools were eligible, executed, skipped, or failed; include diagnostics (timeout, provider error, empty results) in the run trace.
- If a template declares a tool the runtime cannot supply, the dispatch layer must return a clear, auditable failure rather than silently ignoring it.

### Constrain
- Do not spread tool-specific logic across multiple orchestrator call sites; use the shared dispatch helper.
- Keep tool outputs size-bounded and deterministic where possible to avoid prompt window bloat.

## Step 3: Implement `web_search` backed by DuckDuckGo (only public-web provider for this fix)

### Target
- `backend/app/services/web_search.py`
- optionally update `backend/requirements.txt` for a small HTTP helper if needed
- hook into the tool-dispatch layer from Step 2

### Req
- Provide a deterministic, compact normalization for DuckDuckGo results suitable for injection into prompts and for lightweight persistence in history rows.
- Support entity-disambiguation queries so ambiguous names are researched before synthesis.
- Add diagnostics distinguishing provider-unreachable, zero-results, and malformed responses.
- Implement timeouts, page/entry limits and size caps so enrichment remains bounded.

### Constrain
- Do not introduce browser automation or other public search providers as part of this fix.
- Design for deterministic mocks/fixtures for automated tests.

## Step 4: Strengthen Planner decomposition for detailed-report requests

### Target
- `backend/app/tasks.py`
- planner prompt configuration / seed that owns default Planner behavior

### Req
- Tune the Planner prompt so that when the user requests a "detailed report" the Planner prefers a multi-stage DAG: discovery (research), analysis, optional review, and final synthesis.
- Require the Planner to include an explicit research task when web-grounding or disambiguation is appropriate.
- Only assign tool-dependent research roles if Steps 1–3 guarantee those tools are available at runtime.

### Constrain
- Preserve the existing DAG JSON contract and role names unless an additive compatibility field is required.
- Do not make every query produce large DAGs — activate decomposition only for detail/evidence requests.

## Step 5: Provide a richer output contract and per-task response-model strategy

### Target
- `backend/app/schemas.py`
- `backend/app/tasks.py`
- `backend/app/services/history_runs.py`
- `frontend/src/app/history/[run_id]/page.tsx` (if rendering richer payloads is required)

### Req
- Introduce richer response models (e.g. `DetailedReportResponse`) that can include multi-section content, findings, evidence notes, citations, and declared uncertainty.
- Allow per-task `response_model_class_path` selection so research and synthesis steps can opt into richer schemas while keeping simple tasks lightweight.
- Provide a migration/compatibility rule: when a per-task schema is absent, fall back to the run-level `GlobalSettings.response_model_class_path` if present; otherwise, fall back to the legacy `ReportSynthesizerResponse`.
- Preserve evidence from research tasks so synthesizers can cite or summarize it rather than flattening everything into a short bullet list.

### Constrain
- Prefer additive schema evolution stored inside existing JSONB columns to avoid a disruptive DB migration.
- Keep backward compatibility for existing history rows using the legacy `summary/details` shaped payload.

## Step 6: Add regression coverage and focused verification for grounding & depth

### Target
- `backend/tests/` (focused unit/integration tests)
- minimal frontend checks for run-detail rendering compatibility
- curated manual verification flows (e.g. ambiguous queries)

### Req
- Regression tests proving `RoleTemplate` resolution at runtime (no silent fallback to generic prompt).
- Tests proving unsupported declared tools fail audibly through the dispatch layer.
- Tests proving `web_search` calls the DuckDuckGo integration and injects normalized evidence into task context (use deterministic mocks).
- Focused manual verification for ambiguous queries (e.g. `Takenoko no Sato`) ensuring grounding in the intended target.

### Constrain
- Use deterministic mocks/fixtures instead of live DuckDuckGo in CI.
- Keep the scope focused: grounding, tool wiring, template resolution, and report depth.

## Step 7: Migration, rollout, and monitoring guidance

### Target
- small data-migration or audit scripts (`scripts/` or an alembic revision)
- runtime warnings/metrics in `backend/app/services/tool_dispatch.py` and `backend/app/services/role_templates.py`
- docs for operators describing a staged rollout plan

### Req
- Provide an audit script that flags seeded `RoleTemplate` records that declare tools not currently implemented; do not auto-modify templates without operator review.
- Add safe runtime warnings and a feature-flag controlled opt-in for the new dispatch behavior so teams can roll out incrementally.
- Add monitoring metrics: tool invocation counts, tool failure classification, percent of tasks using per-task richer schemas, and a dashboardable signal for runs that failed due to missing templates.
- Provide an operator checklist for rollout: run audit, enable feature-flag in a small percentage of runs, monitor errors/metrics, then expand rollout.

### Constrain
- Prefer non-destructive data changes; avoid automatic destructive migrations to seeded templates.
- Make the rollout reversible and observable; do not flip the default for all runs without evidence from the staged rollout.

---

Once this plan is accepted, implementers can proceed in the order above. Steps 1–3 are prerequisites for safely enabling per-task richer schemas (Step 5) and for the Planner to reliably assign research roles (Step 4). Step 7 ensures the change is rolled out safely and auditable.