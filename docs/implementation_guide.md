# Implementation Guide & AI Ground Rules (IMPLEMENTATION_GUIDE.md) - v1.4.1

## 1. AI Assistant Ground Rules (Context Loss Prevention)
The AI Assistant MUST strictly adhere to the following rules:

1. **Strict Context Maintenance:** Never omit, truncate, or delete sections from agreed-upon documents without explicit user permission.
2. **Step-by-Step Principle:** Focus ONLY on the instructed "Phase Step". Do not generate massive files all at once.
3. **Security First (Strictly Enforced):** In `Step 1`, you MUST configure `.gitignore` to exclude `.env`, `*.key`, `*.pem`, `secrets.json`, and the `.history/` folder. Never hardcode credentials into the source code at any implementation step.
4. **Host Inference Engine Priority:** Inference is handled by a custom host-side OpenAI-compatible API service (e.g., MLX) accessed via `host.docker.internal` from the containers. Setup instructions for this host environment must be written in the `README.md`, not within the codebase itself.
5. **Language Boundary:** UI in Japanese, Code comments/commits in English, Chat in Japanese.
6. **No Git Operations:** Never execute Git state-altering commands unless instructed.

## 2. Implementation Master Plan & Command Execution Scope
When receiving `do phase [N] step [M]`, interpret the below as a **Strict Prompt to generate the final code instantly**, applying files directly without waiting for user confirmation.

- **Phase 1: Infrastructure Foundation & Skeleton**
  - **Step 1: Directory Design, Security Setup & Dependencies**
    - [Target]: `.gitignore`, `.dockerignore`, `backend/requirements.txt`, `frontend/package.json`, `README.md`
    - [Req]: 
      - `.gitignore` MUST include `.env`, `*.pem`, `.history/`, `__pycache__/`, `node_modules/`. 
      - Python `requirements.txt` includes FastAPI, SQLAlchemy, alembic, psycopg2-binary, pgvector, celery, redis, openai, outlines, markitdown, pygithub, pdfplumber. 
      - Node `package.json` includes Next.js, Tailwind, React Flow. 
      - Create `README.md` to document the deployment guide, explicitly detailing the exact setup commands for the host-side inference engine (e.g., `pip install mlx-lm` and `python3 -m mlx_lm server --model prism-ml/Ternary-Bonsai-8B-mlx-2bit --port 8000`), and how to boot Karesansui containers.
  - **Step 2: `docker-compose.yml` (DooD & Backend)**
    - [Target]: `docker-compose.yml`, `.env.example`, `backend/Dockerfile`
    - [Req]: 
      - Define `PORT_PREFIX=80` and `INFERENCE_API_BASE_URL=http://host.docker.internal:8000/v1` in `.env.example`.
      - Create `backend/Dockerfile` using Python 3.11-slim for the FastAPI backend.
      - Define DB (pgvector), Redis, and Backend in `docker-compose.yml`. Backend must use `build: ./backend`, volume mount `/var/run/docker.sock`, and inject `extra_hosts: - "host.docker.internal:host-gateway"`.

- **Phase 2: Data Models & Global Settings API**
  - **Step 1: PostgreSQL schema definition**
    - [Target]: `backend/app/database.py`, `backend/app/models.py`
    - [Req]: 
      - Configure SQLAlchemy engine and load the `pgvector` extension in `database.py`.
      - Define `History` table (Columns: `id` [UUID], `task_id`, `role`, `result` [JSONB], `progress` [JSONB], `created_at`).
      - Define `GlobalSettings` table (Columns: `key` [PK], `value` [JSONB], `updated_at`).
  - **Step 2: Alembic & Pydantic schemas**
    - [Target]: `alembic/env.py`, `backend/app/schemas.py`
    - [Req]: 
      - Configure `env.py` to import `Base.metadata` for auto-generating migrations.
      - Create precise Pydantic v2 `BaseModel` classes (`HistoryCreate`, `HistoryResponse`, `SettingUpdate`, etc.) in `schemas.py`.
  - **Step 3: FastAPI CRUD endpoints**
    - [Target]: `backend/app/routers/history.py`, `backend/app/routers/settings.py`, `backend/app/main.py`
    - [Req]: 
      - Implement `GET`, `POST`, `PUT` routes using `APIRouter` with DB session dependency injection.
      - Initialize `FastAPI()` in `main.py`, configure CORS, and include the routers.

- **Phase 3: Knowledge Base Pipeline (RAG Foundation)**
  - **Step 1: PDF Splitting via TOC/Layout Analysis & MarkItDown Integration**
    - [Target]: `backend/app/services/document_parser.py`
    - [Req]: 
      - Implement logic using `pdfplumber` to extract TOC and iterate pages.
      - Detect tables/figures crossing page boundaries using bounding boxes, and dynamically adjust split boundaries to prevent severing visual elements.
      - Save split PDFs into physical directory hierarchies (e.g., `chapter_1/section_1.pdf`) and convert them to Markdown via a subprocess calling `markitdown`.
  - **Step 2: Vectorization and `pgvector` storage**
    - [Target]: `backend/app/services/vector_store.py`
    - [Req]: 
      - Generate embeddings using a lightweight local `Sentence-Transformers` model.
      - Implement functions to `INSERT` vectors into the `pgvector` column and `SELECT` chunks using cosine similarity logic.
  - **Step 3: GitHub repository integration**
    - [Target]: `backend/app/services/github_sync.py`
    - [Req]: 
      - Use `PyGithub` and `GITHUB_TOKEN` from environment variables.
      - Implement a function to commit/push the converted Markdown files to a private repository while strictly maintaining the generated physical directory structure.

- **Phase 4: Inference Workers & Core LLM Features**
  - **Step 1: Inference client (OpenAI API compatible)**
    - [Target]: `backend/app/llm/inference_client.py`
    - [Req]: 
      - Instantiate `openai.AsyncClient` pointing to `base_url=INFERENCE_API_BASE_URL` (`host.docker.internal`).
      - Implement `async def generate_response` to send HTTP requests, complete with connection timeout and API error exception handling.
  - **Step 2: JSON Schema enforcement**
    - [Target]: `backend/app/llm/structured_output.py`
    - [Req]: 
      - Wrap the OpenAI client using `instructor` or `outlines` libraries.
      - Force the model to output 100% compliant JSON matching specific Pydantic schemas passed as arguments.
  - **Step 3: Celery worker integration and auto-retry**
    - [Target]: `backend/app/worker.py`, `backend/app/tasks.py`
    - [Req]: 
      - Initialize the Celery app instance connected to Redis.
      - Define `@celery.task(bind=True, max_retries=3)` to execute the structured LLM inference.
      - Implement exponential backoff retry logic for JSON parsing or connection failures.

- **Phase 5: Orchestrator & DAG Control Mechanism**
  - **Step 1: DAG parsing logic**
    - [Target]: `backend/app/orchestrator/dag_parser.py`
    - [Req]: 
      - Create a class to parse the JSON DAG payload.
      - Check for circular dependencies and implement a topological sort algorithm to return a list of executable tasks in the correct order.
  - **Step 2: Task enqueueing and I/O**
    - [Target]: `backend/app/orchestrator/manager.py`
    - [Req]: 
      - Enqueue resolved tasks to the Celery broker.
      - Upon task completion, extract ONLY the `result` field (ignoring `progress`) from parent tasks and merge it into the input prompt for subsequent child tasks to save tokens.
  - **Step 3: Debate node control flow**
    - [Target]: `backend/app/orchestrator/debate_controller.py`
    - [Req]: 
      - Implement round-robin loop logic for `Advocate` and `Disrupter` agents.
      - Have the `Mediator` agent evaluate consensus after each round returning a Boolean flag.
      - Implement a forced-exit summary mechanism if the loop hits the system's "Max Debate Rounds" limit.

- **Phase 6: Management Web Console (UI)**
  - **Step 1: Dashboard and settings panel**
    - [Target]: `frontend/src/app/page.tsx`, `frontend/src/app/settings/page.tsx`
    - [Req]: 
      - Build a modern Next.js interface utilizing Tailwind CSS.
      - Use SWR or React Query to fetch history/settings from FastAPI, rendering data tables and configuration forms.
  - **Step 2: DAG visualizer**
    - [Target]: `frontend/src/components/DagVisualizer.tsx`
    - [Req]: 
      - Import `reactflow` to map DAG JSON into nodes and edges graphically.
      - Implement custom nodes that dynamically change colors based on execution status (e.g., pending, running, completed).
  - **Step 3: Live Trace (WebSocket/SSE)**
    - [Target]: `backend/app/routers/stream.py`, `frontend/src/components/LiveTrace.tsx`
    - [Req]: 
      - Backend: Implement FastAPI `StreamingResponse` endpoint yielding `data: {json}\n\n` for Server-Sent Events (SSE).
      - Frontend: Implement a terminal-style UI component (black background, green text) utilizing the `EventSource` API to stream and auto-scroll live agent thoughts (`progress`).