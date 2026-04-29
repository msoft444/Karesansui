# Bug Report: detailedquery (2026-04-28)

## Symptom
- Requesting a detailed report still produces only a short summary and a few bullet points rather than a substantive report.
- Research-oriented roles do not appear to perform sufficient public-web investigation, so the output remains thin and can hallucinate the subject.
- Example: asking for a report about "Takenoko no Sato" can produce content about a traditional Kansai sweet instead of the Meiji chocolate snack product.
- The system currently provides no evidence that `Data_Gatherer` or other roles used DuckDuckGo Search before producing the result.

## How to reproduce
1. Start the current stack with the backend, worker, database, and frontend.
2. Submit a query such as: `Create a detailed report about Meiji's "Takenoko no Sato". Use web search and include concrete findings, supporting evidence, and a structured final report.`
3. Wait for the run to finish and open the run detail screen or inspect the raw `History` rows for the same `run_id`.
4. Observe that the final result is typically a short `summary` plus a few `details` items, not a multi-section report with evidence, citations, or clear source-grounded findings.
5. Inspect the orchestration runtime path:
   - `RoleTemplate` records declare `tools=["rag_search", "web_search", "mcp_call"]`, but runtime task execution does not load or apply those templates.
   - Searching the backend runtime shows no implementation of `web_search`, `rag_search`, `mcp_call`, or DuckDuckGo Search.
6. Observe that the system therefore answers mainly from model priors, which makes product-name disambiguation fragile and leads to hallucinations.

## Expected behavior
- A query that explicitly asks for a detailed report should produce a substantive, multi-section final report rather than a compressed short summary.
- Roles such as `Data_Gatherer` must actually execute public-web research when the task requires external facts, and the required web search provider for this bugfix is DuckDuckGo Search.
- The report should be grounded in collected evidence and should disambiguate ambiguous entities such as brand or product names before synthesis.
- The Planner should decompose detailed-report requests into a research-oriented DAG with explicit evidence gathering, analysis, and synthesis stages.

## Actual behavior
- The runtime does not use the stored role-template definitions during task execution. `RoleTemplate.system_prompt`, `RoleTemplate.tools`, and `RoleTemplate.default_params` are persisted and editable through CRUD APIs, but the execution path sends only a generic prompt such as `You are a {role} agent.` plus the user query and parent context.
- There is no runtime tool implementation for `web_search`, `rag_search`, or `mcp_call` in the backend application code, and there is no DuckDuckGo Search integration. The seed data advertises tools that the worker cannot actually execute.
- The default Planner prompt in `backend/app/tasks.py` mainly constrains DAG JSON structure and allowed roles. It does not require deeper task decomposition for detailed-report requests, source collection, entity disambiguation, or evidence-backed synthesis.
- The default structured output model for Standard tasks is `ReportSynthesizerResponse`, which only allows `summary: str` and `details: list[str]`. That contract compresses both intermediate research outputs and the final report into a terse summary-and-bullets shape, even when the user explicitly asks for a detailed report.
- The run-detail UI can already show the raw stored payload, so the short result is not primarily a frontend truncation problem. The stored task results themselves are already shallow.

## Affected files
- `backend/alembic/versions/20260419_add_role_templates.py` — seeds role templates that declare `web_search`, `rag_search`, and `mcp_call`, but only as data.
- `backend/app/models.py` — defines the `RoleTemplate` model whose prompt, tools, and default params are not consumed by the orchestration runtime.
- `backend/app/routers/templates.py` — exposes CRUD for role templates, but template data is not wired into execution.
- `backend/app/tasks.py` — defines the default Planner system prompt and defaults all Standard-task structured output to `ReportSynthesizerResponse`.
- `backend/app/orchestrator/manager.py` — builds Standard-task prompts from the generic `You are a {role} agent.` template and does not execute declared tools.
- `backend/app/orchestrator/debate_controller.py` — builds Debate participant and mediator prompts from the same generic template and does not execute declared tools.
- `backend/app/schemas.py` — constrains Standard-task outputs to `summary` and `details`, which is too narrow for a true detailed report.
- `docs/requirement_specification.md` — defines Web Search as a worker-side tool boundary and describes role templates as executable runtime components, which the current implementation does not satisfy.