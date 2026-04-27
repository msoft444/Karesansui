# Requirement Specification: Karesansui (Ternary Bonsai Multi-Agent System) - v1.4.1

## 1. System Overview
- System Name: Karesansui
- Core Model: Ternary Bonsai (e.g., 1.58-bit highly efficient model / Apple Silicon compatible)
- Inference Backend: Host-native Custom OpenAI-compatible API Server (e.g., Ternary-supported llama.cpp or MLX server running natively on Mac)
- Architecture: Asynchronous worker pool multi-agent system utilizing a message broker
- Overview: A local AI environment where multiple specialized agents autonomously collaborate and debate to execute tasks, communicating from inside Docker containers to the host-side Metal GPU environment.

## 2. System Objectives & Scope
- **First Objective (Current Development Scope):** Parse user inputs, execute investigation/analysis or multi-perspective debates via appropriate agent groups, and generate a final report. Provide a RAG feature to build and query a dedicated knowledge base. Establish a portable foundation by containerizing the entire backend system using Docker.
- **Second Objective (Future Expansion Scope):** Utilizing the foundation established in the First Objective, create and modify large-scale systems (millions of lines, thousands of files). Furthermore, achieve "Self-Evolution" where Karesansui Alpha can provision a Karesansui Beta environment via DooD (Docker outside of Docker, mounting `/var/run/docker.sock`) and autonomously perform its own system updates. The design must be portable, allowing multiple ecosystems to run concurrently on the same terminal without port or network conflicts.
- **Architectural Constraint:** While anticipating the Second Objective, the current scope focuses on the First Objective. To prevent architectural failure during future large-scale data processing, massive data must not be included in the model's context. The design must assume processing via external storage, RAG, and Tool Use (Function Calling) from the stage of the First Objective.

## 3. Basic Concept of Agents
- In this system, an "Agent" is not an autonomous physical process, but a logical execution unit combining the "Ternary Bonsai base model", a "Role Definition (System Prompt)", an "Executable Toolset", and an "Independent KV Cache".
- **Role Templates and Dynamic Parameters:** Agent roles are selected from predefined "Role Templates" in the system. The Planner can inject "Dynamic Parameters (variables)" to specify particular standpoints or tones when assigning templates.

## 4. Agent Definitions
- **Planner (Plan Executor):** Analyzes user input, defines required task division and dependencies as a Directed Acyclic Graph (DAG), and assigns the optimal role template and dynamic parameters to each task.
  - **DAG Schema Requirement:** The Planner's output must distinguish task types (`Standard` or `Debate`) and strictly follow a JSON Schema containing "Task ID, Assigned Role (for Debate, participant list and mediator), List of dependent parent Task IDs, and Dynamic parameters".

### Role Template Collection
**A. Fact-Based (Objective investigation & analysis)**
  - `Data_Gatherer`: Specializes in collecting objective facts/data using tools (RAG, MCP, Web Search, etc.). Does not interject personal opinions.
  - `Logical_Analyst`: Builds logical interpretations and structures based on collected data.
  - `Critical_Reviewer`: Points out logical leaps or lack of evidence in deliverables and requests reconsideration.
  - `Report_Synthesizer`: Objectively integrates verified information and creates the final report.

**B. Debate/Roleplay-Based (Subjective discussion & diversity)**
  - `Advocate`: Strongly asserts the legitimacy and merits of a specific "Standpoint" designated by the Planner.
  - `Disrupter`: Forcibly introduces a specified "different concept" into existing discussions to enforce multi-dimensional perspectives.
  - `Mediator`: Exclusive to Debate nodes. Integrates opinions of other agents and aims for consensus. Outputs a "Termination Flag and Final Conclusion" upon reaching agreement.
  - `Persona_Writer`: Creates a final report summarizing discussion results according to a specified "Tone & Manner".

**C. System Utility**
  - `Translator`: Specializes in bidirectional English-Japanese translation. Does not perform logical inference, maintains format and nuance only.

## 5. Inter-Agent Communication & Control Flow
- Basic Communication Protocol: All internal communication and inference between agents must be conducted in "English" to optimize tokens.
- **Flow Control (Task Queue & Worker Pool Pattern):**
  - **Orchestrator (Process Manager):** Parses the DAG output by the Planner, enqueues tasks into the task queue, and dynamically manages worker processes.
  - **Debate Node Control:** When the Orchestrator executes a `Debate` type task, it controls the sequential loop (round-robin) between participating agents and the Mediator.
    - Input for each agent: `result` of the pre-debate task and `result`s of agents currently in the debate.
    - Exits the loop when the Mediator issues a consensus judgment (termination flag), passing the Mediator's final `result` to the next task.
    - **Infinite Loop Prevention (Fail-Safe):** If the system's "Max Debate Rounds" limit is reached, the Orchestrator forcibly terminates the loop, forces the Mediator to output a summary, and proceeds to the next task.
  - **Agent Service (Worker Pool):** Establish multiple independent execution environments (workers) separated from the DAG control function. Tasks are pooled in an asynchronous queue, and available environments fetch and process executable tasks based on their capacity. Each worker process executes inference via HTTP requests to the host-side custom OpenAI-compatible API server.

## 6. Data, State & Knowledge Management
- Model Management: Ternary Bonsai model weights are managed directly on the host OS environment, completely outside of the containers.
- Context Management: Achieved by holding and switching individually assigned system prompts and independent KV Caches.
- **External Information Retrieval & Management (Tool Execution Boundary):**
  - In the current scope, safe API call tools like "Web Search" and "Communication with MCP servers" are implemented and executed directly as Python functions within the worker process.
- **Knowledge Base Pipeline (for RAG/MCP):**
  - Pre-conversion files (PDFs, etc.) uploaded by users are stored in a shared temporary storage (local directory).
  - **Preprocessing & Hierarchization (Integrated TOC & Layout Analysis):** Without relying on LLM, a program extracts the Table of Contents (TOC) information from the PDF to physically split it by chapters and sections first. During this process, layout analysis is performed to detect visual elements like tables or figures that span across page boundaries, dynamically adjusting the splitting process (extraction boundaries) to ensure they are integrated intact into the correct section's file without being severed. Then, it creates a physical folder hierarchy based on the chapter/section structure.
  - **Markdown Conversion:** Each physically split file within the hierarchy is converted into Markdown format using Microsoft's `MarkItDown` tool.
  - Converted files are saved to a private GitHub repository maintaining the hierarchy, simultaneously vectorized using a local Embedding model, and indexed in a Vector DB (`pgvector`).
- **Storage & Data Passing (Shared Workspace):**
  - Agents save outputs to a shared workspace in JSON format separated into Conclusion (`result`) and Thought Process/Grounds (`progress`).
  - To save tokens, subsequent agents receive only structured English `result`s of their dependencies (all ancestors), except for Debate nodes which pass discussion history.
- **Log Management & Asynchronous Translation:**
  - The Orchestrator records English `result` and `progress` to the DB upon task completion.
  - Afterwards, it asynchronously enqueues a translation task, storing the Japanese translation in the same record upon completion.

## 7. Interface Requirements: Management Web Console
Provides a browser-based UI for system-wide control and visualization.
- **Language Boundary:** The management console, error messages, and final reports viewed by the user must be entirely in "Japanese". This is strictly distinguished from the "English" used for internal inter-agent communication.
- **Tech Stack:** TypeScript, Next.js (React), Tailwind CSS
- **Dashboard & Query & DAG Manager:**
  - Worker status display. Submission of new queries.
  - Graphical display of the Planner's DAG, and display of current task progress (Live Trace).
- **Knowledge Base Manager:**
  - Management of document upload, hierarchical splitting, `MarkItDown` conversion, vectorization, and GitHub saving status.
- **History & Logs & Global Settings:**
  - Verification of past query results and `result`/`progress` logs (both EN/JP).
  - Dynamic configuration of inference, RAG, and DAG control settings (Top-K, max debate rounds, etc.).

## 8. Security Requirements (Strictly Enforced)
- **Secret Exclusion:** No security-related tokens, passwords, IDs, or API keys shall be hardcoded in the codebase. All secrets must be injected via environment variables (`.env`).
- **Version Control Exclusion:** Files containing secrets (e.g., `.env`) and the `.history` folder must be completely excluded from version control at the system level via `.gitignore`.

## 9. Non-Functional Requirements
- **Tech Stack (Backend & Middleware):**
  - Orchestrator & Backend: Python (FastAPI, Celery)
  - Task Queue: Celery or RQ (Redis)
  - DB: PostgreSQL (using `pgvector`)
- **Execution Environment Boundary:**
  - As a rule, all components **EXCEPT** the inference engine (e.g., backend, UI, DB) must be containerized. DooD mounting of `/var/run/docker.sock` is permitted for meta-development Docker operations.
  - **GPU Access:** Containers access the inference engine via `host.docker.internal`. The inference engine is a custom OpenAI-compatible API server (like a Ternary-supported llama.cpp or MLX) running natively on the Mac host OS to leverage Metal API acceleration directly.
  - **Installation & Setup Requirements:** Setup and startup instructions for the host-side inference API server (e.g., Ternary engine) must not be included in the system code (e.g., Dockerfile), but rather explicitly separated and documented as an installation guide within a `README.md` file located at the repository root.
- **Error Handling & Self-Healing:**
  - Apply JSON Schema constraints via structured output libraries (e.g., `instructor`) to guarantee LLM output structure. When the configured inference backend implements `response_format.json_schema` (e.g., OpenAI API, vLLM with `--guided-json`), constraints are enforced at the logits level. When the backend does not implement logits-level schema enforcement (e.g., mlx_lm), `instructor.Mode.JSON` with automatic Pydantic-schema validation and retries at the application layer is the approved fallback — both modes use the same structured output library contract. If an error occurs, feedback is provided within the worker, and automatic retries are performed up to a specified limit.