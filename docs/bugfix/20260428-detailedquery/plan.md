# Plan: Fix detailedquery issue (2026-04-28)

## Step 1: Resolve and apply role templates at runtime

### Target
- `backend/app/orchestrator/manager.py`
- `backend/app/orchestrator/debate_controller.py`
- new helper such as `backend/app/services/role_templates.py`

### Req
- Load the referenced `RoleTemplate` record for every Standard role, Debate participant, and Mediator before inference starts.
- Build the actual system prompt from `system_prompt` plus merged `default_params` and Planner-supplied `dynamic_params`.
- Enforce a visible failure when the Planner references an unknown template instead of silently falling back to a generic prompt.
- Preserve enough task metadata in `progress` or adjacent runtime structures so history can show which template and parameters were actually used.

### Constrain
- Keep the Planner DAG schema unchanged unless a concrete runtime gap makes an additive field necessary.
- Do not bypass the existing template CRUD data model or hardcode duplicate prompt text in the orchestrator.
- Keep internal agent communication in English and user-facing UI in Japanese.

## Step 2: Introduce an explicit runtime tool-dispatch contract

### Target
- new helper such as `backend/app/services/tool_dispatch.py`
- `backend/app/orchestrator/manager.py`
- `backend/app/orchestrator/debate_controller.py`
- `backend/app/models.py` only if additive runtime metadata fields are truly required

### Req
- Translate each template's declared `tools` list into actual runtime behavior rather than prompt-only declarations.
- Centralize tool selection, invocation, output normalization, and error handling in one dispatch layer shared by Standard and Debate execution paths.
- Record which tools were eligible, which were actually executed, and which failed or were skipped, so the run history can prove whether research happened.
- Fail explicitly when a template declares a tool that the runtime does not support, instead of silently ignoring the mismatch.

### Constrain
- Do not scatter role-specific tool logic across multiple orchestration call sites.
- Keep tool outputs bounded, serializable, and safe to inject into prompt context.
- Avoid changing the role-template CRUD contract unless the current `tools` data shape is proven insufficient.

## Step 3: Implement DuckDuckGo Search as the `web_search` provider

### Target
- new service/helper such as `backend/app/services/web_search.py`
- `backend/requirements.txt` if an additional search library is needed
- the shared tool-dispatch layer introduced in Step 2

### Req
- Implement a real `web_search` runtime tool backed by DuckDuckGo Search as the only public-web search provider for this bugfix.
- Normalize search results into a deterministic, compact structure that can be injected into agent context and, when useful, persisted for inspection.
- Support entity disambiguation queries so ambiguous nouns such as brands, products, companies, or places are researched before synthesis rather than guessed from model priors.
- Expose enough diagnostic detail so failures can be distinguished between provider unavailability, empty results, and prompt-side misuse.

### Constrain
- Keep timeouts, result counts, and payload size bounded so search enrichment does not overwhelm the prompt window.
- Do not introduce direct browser automation, scraping-heavy flows, or unrelated search providers in this fix.
- Keep the implementation compatible with deterministic mocks in automated tests.

## Step 4: Strengthen Planner decomposition for detailed-report requests

### Target
- `backend/app/tasks.py`
- any planner-setting seed or configuration surface that owns the default planner prompt

### Req
- Update the default Planner prompt so detailed-report requests prefer a multi-stage DAG that includes evidence gathering, analysis, review when needed, and final synthesis.
- Instruct the Planner to allocate at least one research-oriented task before final synthesis when the user requests a detailed report or current facts from the web.
- Instruct the Planner to treat entity disambiguation as mandatory when a query could refer to multiple real-world subjects.
- Require the Planner to assign tool-capable research roles only when the runtime contract from Steps 1-3 can actually support those tools.

### Constrain
- Preserve the existing DAG JSON contract and compatible role names.
- Avoid forcing large DAGs for every simple request; the stronger decomposition should activate when the user asks for detail, evidence, or web-grounded research.
- Keep Planner output deterministic enough for the existing structured-output validation path.

## Step 5: Expand the output contract for research tasks and final reports

### Target
- `backend/app/schemas.py`
- `backend/app/tasks.py`
- `backend/app/services/history_runs.py`
- `frontend/src/app/history/[run_id]/page.tsx` if rendering changes are needed for the richer payload

### Req
- Introduce output models that can represent a real detailed report, including multi-section body content, key findings, supporting evidence or source notes, and explicit uncertainty where applicable.
- Stop using the same minimal `ReportSynthesizerResponse(summary, details[])` contract for every Standard task when the final deliverable is expected to be a detailed report.
- Preserve useful evidence from research steps so the final synthesizer can cite or summarize it instead of collapsing everything into a few bullets.
- Keep run-summary preview generation deterministic and keep the run-detail screen compatible with both the old and new payload shapes.

### Constrain
- Keep backward compatibility for existing history rows that still use the old `summary/details` structure.
- Do not require a schema migration if the richer payload can remain inside the current JSONB columns.
- Avoid frontend-only formatting workarounds that leave the backend result contract too weak to represent the requested report depth.

## Step 6: Add regression coverage and focused verification for report depth and web grounding

### Target
- focused backend tests under `backend/tests/`
- any narrow frontend verification needed for run detail rendering
- focused manual verification procedure for a known ambiguous query such as `Takenoko no Sato`

### Req
- Add regression coverage proving that runtime execution resolves `RoleTemplate` records instead of falling back to the generic prompt.
- Add regression coverage proving that unsupported declared tools fail explicitly through the new dispatch layer rather than being silently ignored.
- Add regression coverage proving that a task with `web_search` available calls the DuckDuckGo Search integration and feeds normalized search evidence into the task context.
- Add a focused verification case for an ambiguous query such as `Takenoko no Sato`, ensuring the pipeline grounds the answer in the confection product rather than hallucinating a different subject.
- Add a regression check proving that a detailed-report request produces a richer final-result shape than the current short summary-plus-bullets contract.

### Constrain
- Prefer deterministic mocks or recorded tool responses instead of a live DuckDuckGo dependency in automated tests.
- Keep verification scoped to this bug: report depth, evidence gathering, role-template execution, runtime tool wiring, and web-search grounding.
- Do not broaden the regression plan into unrelated history UI redesign or general orchestration refactors beyond what this fix requires.