# Bug Report — 2026-04-19 Overall

---

## Bug 1: Incorrect Page Title and Branding

### Symptom
When opening the web console, the browser tab title displays **"Karesansui"** (romanized) and the sidebar branding also shows **"Karesansui"** with the sub-label **"Multi-Agent Console"**. The system version is shown only in the sidebar footer as a hardcoded `v0.1.0`.

### Expected Behavior
- The browser tab `<title>` must display **"枯山水"** (Japanese kanji) and include the system version (e.g., `枯山水 v1.4.1`).
- The sidebar branding header must display **"枯山水"** instead of "Karesansui".
- All user-facing occurrences of the system name within web page content should use **"枯山水"** (per the Language Boundary rule: UI must be in Japanese).
- The version displayed in the sidebar footer should reflect the actual system version defined in `requirement_specification.md`.

### How to Reproduce
1. Start the application using `docker compose up`.
2. Open `http://localhost:<PORT_PREFIX>03` in a browser.
3. Observe the browser tab title — it reads "Karesansui".
4. Observe the sidebar header — it reads "Karesansui" / "Multi-Agent Console".
5. Observe the sidebar footer — it reads "v0.1.0".

### Affected Files
- `frontend/src/app/layout.tsx` (metadata title, sidebar branding header, sidebar footer version)

---

## Bug 2: Missing Role Template Management UI

### Symptom
The requirement specification (§4 — Agent Definitions) defines a comprehensive collection of **Role Templates** (e.g., `Data_Gatherer`, `Logical_Analyst`, `Advocate`, `Mediator`, etc.) along with the concept of **Dynamic Parameters**. However, the web console provides no management interface to **add, edit, or delete** these role templates. The Settings page (`/settings`) only manages `GlobalSettings` key-value pairs and has no dedicated section for role template CRUD operations.

### Expected Behavior
The management web console should provide a UI where administrators can:
- **View** all registered role templates with their names, descriptions, and default dynamic parameters.
- **Add** new role templates.
- **Edit** existing role templates (name, system prompt, available tools, default parameters).
- **Delete** role templates that are no longer needed.

This is required by the requirement specification §7 (Interface Requirements) which mandates a browser-based UI for "system-wide control", and §4 which defines role templates as a core system concept that the Planner selects from.

### How to Reproduce
1. Start the application and navigate to the web console.
2. Browse all available pages: Dashboard (`/`), DAG Visualizer (`/dag`), Live Trace (`/live`), Settings (`/settings`).
3. Confirm that no page provides role template management functionality.

### Affected Files
- No existing file covers this feature — new frontend page/components and backend endpoints are required.
- Backend: new model, schema, router for role templates.
- Frontend: new page under `/settings` or a dedicated `/templates` route.

---

## Bug 3: Missing Knowledge Base Manager in Web Console

### Symptom
The requirement specification §6 (Data, State & Knowledge Management) defines a complete **Knowledge Base Pipeline** for RAG/MCP that includes: PDF upload → TOC-based hierarchical splitting → MarkItDown conversion → vectorization via Sentence-Transformers → storage in pgvector → GitHub repository sync. The requirement specification §7 (Interface Requirements) explicitly mandates a **"Knowledge Base Manager"** section providing:
> "Management of document upload, hierarchical splitting, MarkItDown conversion, vectorization, and GitHub saving status."

The backend services for this pipeline are already implemented (`document_parser.py`, `vector_store.py`, `github_sync.py`), but:
- **No upload UI** — there is no web console page or form for users to upload PDF files for processing.
- **No pipeline status view** — there is no UI showing the progress of splitting, conversion, vectorization, or GitHub sync.
- **No library management** — there is no interface to browse, search, or delete documents/chunks already registered in the knowledge base or the GitHub repository.
- **No API endpoints** — there are no REST endpoints to trigger the pipeline or manage uploaded documents from the frontend.

### Expected Behavior
The management web console should provide a **Knowledge Base Manager** page where users can:
- **Upload** PDF files via a drag-and-drop or file picker interface.
- **View pipeline status** — track each uploaded document through the stages: splitting → conversion → vectorization → GitHub sync (with success/failure indicators).
- **Browse** the knowledge base library: list all processed documents with their hierarchical structure (chapters/sections).
- **Delete** individual documents or sections from the knowledge base (removing vectors from pgvector and files from the GitHub repository).
- **Search** the knowledge base by keyword or semantic query to preview retrieved chunks.

### How to Reproduce
1. Start the application and navigate to the web console.
2. Browse all available pages: Dashboard (`/`), DAG Visualizer (`/dag`), Live Trace (`/live`), Settings (`/settings`).
3. Attempt to find any page for uploading PDFs, viewing pipeline status, or managing knowledge base documents.
4. Confirm that no such feature exists on any page.

### Affected Files
- Backend: new router (`backend/app/routers/knowledge.py`) with endpoints for upload, list, delete, and search; wiring to existing `document_parser.py`, `vector_store.py`, and `github_sync.py` services.
- Frontend: new `/knowledge` page with upload form, pipeline status display, document library browser, and delete controls.
- `frontend/src/app/layout.tsx`: add navigation item for the new page.

---

## Bug 4: Missing Agent Service Control and Worker Status Management in Web Console

### Symptom
The requirement specification §5 (Inter-Agent Communication & Control Flow) defines an **Agent Service (Worker Pool)** that establishes multiple independent execution environments (workers) managed by the Orchestrator. The requirement specification §7 (Interface Requirements) explicitly mandates **"Worker status display"** in the Dashboard. However, the web console provides:
- **No worker status display** — there is no UI showing which Celery workers are online, their current load, or health.
- **No task control** — there is no mechanism to **stop, cancel, or revoke** a running or queued task from the web console.
- **No execution monitoring** — there is no real-time view of which tasks are currently being processed by which workers.

### Expected Behavior
The management web console should provide:
- A **worker status panel** displaying all active Celery workers, their state (online/offline), and the number of tasks currently being processed.
- A **task control interface** allowing users to:
  - View currently running and queued tasks.
  - Send a **stop/revoke** command to cancel a specific running or pending task.
  - View task state transitions (pending → running → completed/failed/revoked).
- Integration with the existing Dashboard or a dedicated `/workers` page.

This is required by §5 which defines the Worker Pool architecture and §7 which mandates worker status display.

### How to Reproduce
1. Start the application and navigate to the web console.
2. Trigger tasks via API or other means.
3. Attempt to find any UI element showing worker status or providing task stop/cancel controls.
4. Confirm that no such feature exists on any page.

### Affected Files
- Backend: new API endpoints to query Celery worker status (`celery.app.control.inspect()`) and revoke tasks (`celery_app.control.revoke()`).
- Frontend: new worker status panel component and task control UI (on Dashboard or dedicated page).

---

## Bug 5: Missing Task Execution Feature from Web Console

### Symptom
The web console does not provide any mechanism for users to **submit new queries or tasks** for execution. The Dashboard (`/`) only displays execution history. The DAG Visualizer (`/dag`) only renders previously completed DAG runs. The Live Trace (`/live`) requires a pre-existing `run_id` to connect. There is no entry point for a user to initiate a new task.

### Expected Behavior
The requirement specification §7 (Dashboard & Query & DAG Manager) explicitly states:
> "Worker status display. **Submission of new queries.**"

The web console should provide a form or interface where users can:
- Input a new query/task description.
- Submit it to the backend for orchestration (triggering the Planner → DAG → Worker pipeline).
- Receive a `run_id` for subsequent tracking via the DAG Visualizer and Live Trace.

### How to Reproduce
1. Start the application and navigate to the web console.
2. Attempt to find any input field or button to submit a new task/query.
3. Confirm that no such feature exists on any page.

### Affected Files
- Frontend: new query submission UI component (likely on the Dashboard page `/` or a dedicated route).
- Backend: new or extended API endpoint to accept a query and trigger orchestration.
