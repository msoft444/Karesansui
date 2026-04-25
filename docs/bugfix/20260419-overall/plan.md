# Bugfix Implementation Plan — 2026-04-19 Overall

When receiving a bugfix execution command, interpret each Phase below as a **strict prompt** and apply fixes directly.

## 1. AI Assistant Ground Rules (Context Loss Prevention)
The AI Assistant MUST strictly adhere to the following rules:

1. **Strict Context Maintenance:** Never omit, truncate, or delete sections from agreed-upon documents without explicit user permission.
2. **Step-by-Step Principle:** Focus ONLY on the instructed "Phase Step". Do not generate massive files all at once.
3. **Security First (Strictly Enforced):** In `Step 1`, you MUST configure `.gitignore` to exclude `.env`, `*.key`, `*.pem`, `secrets.json`, and the `.history/` folder. Never hardcode credentials into the source code at any implementation step.
4. **Host Inference Engine Priority:** Inference is handled by a custom host-side OpenAI-compatible API service (e.g., MLX) accessed via `host.docker.internal` from the containers. Setup instructions for this host environment must be written in the `README.md`, not within the codebase itself.
5. **Language Boundary:** UI in Japanese, Code comments/commits in English, Chat in Japanese.
6. **No Git Operations:** Never execute Git state-altering commands unless instructed.

## 2. BugFix Master Plan
---

## Phase 1: Fix Page Title, Branding, and Version Display

- **Step 1: Update metadata title and sidebar branding**
  - [Target]: `frontend/src/app/layout.tsx`
  - [Req]:
    - Change the `metadata.title` from `"Karesansui"` to `"枯山水 v1.4.1"`.
    - Change the `metadata.description` to use "枯山水" instead of "Karesansui" where it appears in user-facing context.
    - In the sidebar branding header, replace `"Karesansui"` with `"枯山水"`.
    - Update the sub-label from `"Multi-Agent Console"` to `"マルチエージェントコンソール"` (Japanese UI rule).
    - Update the sidebar footer version string from `"v0.1.0"` to `"v1.4.1"` to match the system version in `requirement_specification.md`.
  - [Constraint]: UI text must be in Japanese per the Language Boundary rule.

---

## Phase 2: Add Role Template Management UI

- **Step 1: Backend — Role Template model, schema, and migration**
  - [Target]: `backend/app/models.py`, `backend/app/schemas.py`, new Alembic migration
  - [Req]:
    - Define a `RoleTemplate` table with columns: `id` (UUID, PK), `name` (unique string, e.g. `"Data_Gatherer"`), `description` (text), `system_prompt` (text), `tools` (JSONB, list of available tool names), `default_params` (JSONB, default dynamic parameters), `created_at` (timestamp), `updated_at` (timestamp).
    - Create corresponding Pydantic v2 schemas: `RoleTemplateCreate`, `RoleTemplateUpdate`, `RoleTemplateResponse`.
    - Generate an Alembic migration for the new table.
  - [Constraint]: Seed the initial role templates defined in `requirement_specification.md` §4 via the migration or a startup hook so they are available out-of-the-box.

- **Step 2: Backend — Role Template CRUD API**
  - [Target]: `backend/app/routers/templates.py`, `backend/app/main.py`
  - [Req]:
    - Implement a new `APIRouter` with full CRUD endpoints:
      - `GET /api/templates/` — List all role templates.
      - `GET /api/templates/{id}` — Get a single template.
      - `POST /api/templates/` — Create a new template.
      - `PUT /api/templates/{id}` — Update an existing template.
      - `DELETE /api/templates/{id}` — Delete a template.
    - Register the router in `main.py`.
  - [Constraint]: Use DB session dependency injection consistent with existing routers.

- **Step 3: Frontend — Role Template management page**
  - [Target]: `frontend/src/app/templates/page.tsx` (new), `frontend/src/app/layout.tsx` (nav update)
  - [Req]:
    - Create a new `/templates` page displaying all role templates in a card or table layout.
    - Provide a creation form (modal or inline) for adding new templates.
    - Provide inline editing and a delete button with confirmation for each template.
    - Add a "役割テンプレート" navigation item in the sidebar (`layout.tsx`).
    - Use SWR for data fetching, consistent with existing pages.
  - [Constraint]: All UI text in Japanese. API proxy path must be configured in `next.config.js` if not already covered by a wildcard.

---

## Phase 3: Add Knowledge Base Manager

- **Step 1: Backend — Knowledge base API endpoints**
  - [Target]: new `backend/app/routers/knowledge.py`, `backend/app/main.py`
  - [Req]:
    - Implement a `POST /api/knowledge/upload` endpoint that accepts a multipart PDF file upload, saves it to the shared temporary storage, then triggers the full pipeline: `document_parser.split_pdf()` → `document_parser.convert_to_markdown()` → `vector_store.insert_chunks()` → `github_sync.push_hierarchy()`. Return a job/status object with pipeline progress.
    - Implement a `GET /api/knowledge/` endpoint that lists all processed documents with their hierarchical structure, processing status (splitting/converting/vectorizing/synced/failed), and metadata (upload date, page count, chunk count).
    - Implement a `GET /api/knowledge/{doc_id}` endpoint that returns detailed information for a single document including its chapter/section tree and individual chunk previews.
    - Implement a `DELETE /api/knowledge/{doc_id}` endpoint that removes the document's vectors from pgvector, deletes files from the GitHub repository via `github_sync`, and cleans up local temporary files.
    - Implement a `POST /api/knowledge/search` endpoint that accepts `{ "query": "<text>", "top_k": N }` and returns the top-K semantically similar chunks from `vector_store.search()`.
    - Register the router in `main.py`.
  - [Constraint]: Reuse existing service modules (`document_parser`, `vector_store`, `github_sync`). Long-running pipeline steps should be executed as Celery background tasks to avoid HTTP timeout. Return immediate acknowledgment with a trackable status.

- **Step 2: Backend — Document metadata model and migration**
  - [Target]: `backend/app/models.py`, `backend/app/schemas.py`, new Alembic migration
  - [Req]:
    - Define a `KnowledgeDocument` table with columns: `id` (UUID, PK), `filename` (string), `status` (enum: uploading/splitting/converting/vectorizing/syncing/completed/failed), `error_message` (text, nullable), `page_count` (integer), `chunk_count` (integer), `github_path` (string, nullable), `created_at` (timestamp), `updated_at` (timestamp).
    - Create corresponding Pydantic v2 schemas: `KnowledgeDocumentResponse`, `KnowledgeSearchRequest`, `KnowledgeSearchResponse`.
    - Generate an Alembic migration for the new table.
  - [Constraint]: The `KnowledgeChunk` table already exists in `models.py`; add a foreign key from chunks to the new `KnowledgeDocument` table if not already linked.

- **Step 3: Frontend — Knowledge Base Manager page**
  - [Target]: new `frontend/src/app/knowledge/page.tsx`, `frontend/src/app/layout.tsx` (nav update)
  - [Req]:
    - Create a new `/knowledge` page with the following sections:
      - **Upload area**: drag-and-drop zone or file picker for PDF uploads with progress indicator.
      - **Document library**: table listing all processed documents with columns for filename, status badge (with color coding per stage), page count, chunk count, upload date, and action buttons.
      - **Delete button**: per-document delete with confirmation dialog that removes vectors, GitHub files, and local data.
      - **Search panel**: text input for semantic search with top-K results displayed as expandable chunk previews.
    - Add a "ナレッジベース" navigation item in the sidebar (`layout.tsx`).
    - Use SWR with polling for pipeline status updates on in-progress documents.
  - [Constraint]: All UI text in Japanese. File upload must validate that only PDF files are accepted. Show clear error messages for pipeline failures.

---

## Phase 4: Add Agent Service Control and Worker Status Management

- **Step 1: Backend — Worker status and task control API**
  - [Target]: new `backend/app/routers/workers.py`, `backend/app/main.py`
  - [Req]:
    - Implement a `GET /api/workers/` endpoint that uses `celery_app.control.inspect()` to return a list of active workers with their state, active tasks, and stats.
    - Implement a `GET /api/workers/tasks/` endpoint to list currently active and reserved (queued) tasks across all workers.
    - Implement a `POST /api/workers/tasks/{task_id}/revoke` endpoint that calls `celery_app.control.revoke(task_id, terminate=True)` to stop a running or queued task.
    - Register the router in `main.py`.
  - [Constraint]: Use the existing `celery_app` instance from `worker.py`. Handle cases where workers are offline gracefully (return empty lists, not errors).

- **Step 2: Frontend — Worker status panel and task control UI**
  - [Target]: new `frontend/src/app/workers/page.tsx`, `frontend/src/app/layout.tsx` (nav update)
  - [Req]:
    - Create a new `/workers` page displaying:
      - A worker status table showing each worker's name, status (online/offline), number of active tasks, and last heartbeat.
      - A running/queued tasks table showing task ID, task name, worker assignment, and state.
      - A "停止" (Stop) button on each running/queued task row that sends a revoke request to the backend with a confirmation dialog.
    - Add a "ワーカー管理" navigation item in the sidebar (`layout.tsx`).
    - Use SWR with a polling interval (e.g., 5 seconds) for real-time status updates.
  - [Constraint]: All UI text in Japanese. Revoke actions must require user confirmation before execution.

---

## Phase 5: Add Task Execution Feature from Web Console

- **Step 1: Backend — Query submission endpoint**
  - [Target]: `backend/app/routers/stream.py` or new `backend/app/routers/query.py`, `backend/app/main.py`
  - [Req]:
    - Implement a `POST /api/query/` endpoint that accepts a JSON body `{ "query": "<user text>" }`.
    - The endpoint must trigger the orchestration pipeline: invoke the Planner, generate a DAG, and enqueue tasks via the existing `OrchestratorManager`.
    - Return a response containing at minimum `{ "run_id": "<uuid>" }` so the frontend can redirect to Live Trace or DAG Visualizer.
  - [Constraint]: Reuse existing `OrchestratorManager` and Celery task infrastructure. Do not duplicate orchestration logic.

- **Step 2: Frontend — Query submission UI**
  - [Target]: `frontend/src/app/page.tsx`, possibly new component `frontend/src/components/QueryForm.tsx`
  - [Req]:
    - Add a query input form at the top of the Dashboard page (`/`) with a text area and a "実行" (Execute) submit button.
    - On successful submission, display the returned `run_id` and provide a link to navigate to `/live?run_id=<id>` for live tracking.
    - Show loading state during submission and error feedback on failure.
  - [Constraint]: All UI text in Japanese. The form must be clearly visible above the existing execution history table.
