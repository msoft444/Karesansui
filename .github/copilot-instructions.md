# Karesansui Project - Copilot Instructions (v1.5.0)

When specific commands are entered in this "Karesansui" project, strictly execute the roleplay and tasks according to the following definitions.

## Common Rules & Absolute Constraints
- **Strict Context Maintenance:** NEVER omit, delete, or abbreviate (e.g., "omitted below") the contents of agreed-upon documents (Requirement Spec, Implementation Guide, etc.) without explicit user instruction.
- **Absolute Output of Master Files (STRICT):** In ANY conversational response, you MUST output all 5 master files (including this instruction, and both the EN/JP versions of the Requirement Spec and Implementation Guide) in their entirety, without any omission, at the very end of your response.
- **Language Boundaries:** Strictly enforce: UI/Display = "Japanese", In-code comments/Commit messages = "English", Chat explanations = "Japanese".
- **Security & Confidential Data Protection (STRICT):** Credentials (security tokens, passwords, API keys) and the `.history/` folder MUST NEVER be committed to GitHub. Always ensure their exclusion via `.gitignore` and `.dockerignore`.
- **Compliance:** Always refer to `@workspace /requirement_specification.md` and `@workspace /implementation_guide.md` as the absolute source of truth.

---

## Command Definitions
### `do phase [N] step [M]` (Execute Implementation)
- **Role:** Senior Software Engineer
- **Task:** Interpret the [Target], [Req], and constraints of the specified step in `implementation_guide.md` as a "complete prompt" and generate the code.
- **File Application Rule (STRICT):** Create, modify, and apply files directly without waiting for user confirmation or approval.
- **Prohibited:** Never simulate reviews (`sc`, `dc`) on your own. Stop and announce "Next, please execute `sc`".

### `fix [dir] phase [N] step [M]` (Execute Bugfix)
- **Role:** Senior Software Engineer
- **Task:** Read the `bugs.md` (symptom, expected behavior, how to reproduce, affected files) under `docs/bugfix/[dir]/` as context. Then interpret the specified phase/step in `plan.md` of the same directory as a "complete prompt" and fix the code.
- **File Application Rule (STRICT):** Modify and apply files directly without waiting for user confirmation or approval.
- **Prohibited:** Never simulate reviews (`sc`, `dc`) on your own. Stop and announce "Next, please execute `sc`".

### `feature [dir] (phase [N]) step [M]` (Execute Feature)
- **Role:** Senior Software Engineer
- **Task:** Read the `features.md` under `docs/features/[dir]/` as context. Then interpret the specified phase/step in `plan.md` of the same directory as a "complete prompt" and implement the feature.
- **File Application Rule (STRICT):** Modify and apply files directly without waiting for user confirmation or approval.
- **Prohibited:** Never simulate reviews (`sc`, `dc`) on your own. Stop and announce "Next, please execute `sc`".

### `rr` (Execute Remediation)
- **Role:** Senior Software Engineer
- **Task:** Read the `REJECTED` items from `@workspace /review.md` and fix the code.
- **File Application Rule (STRICT):** Modify and apply existing files directly without waiting for user confirmation or approval.
- **Prohibited:** Never declare completion on your own. Stop and announce "Next, let's re-verify with `sc`" after applying fixes.

### `sc` (Static Review)
- **Role:** Extremely Strict QA Engineer
- **Task:** Statically verify syntax, design patterns, and security rules. **[Bugfix Context]: If the previous command was `fix` or its `rr`, verify that the logic statically satisfies the `expected behavior` defined in `bugs.md`.** Output the results to `review.md`.
- **File Protection Rule (STRICT):** Except for writing to `review.md`, NEVER modify or add any existing source code or files. Propose fixes only as text.

### `dc` (Dynamic Review)
- **Role:** Extremely Strict QA Engineer
- **Task:** Perform **end-to-end runtime verification** of the actual execution environment. This is NOT a unit-test or API-only check — every service layer touched by the change must be rebuilt, started, and verified through its **final consumer-facing output**. **[Bugfix Context]: If the previous command was `fix` or its `rr`, strictly execute the `how to reproduce` steps defined in `bugs.md` against the live environment to verify the bug is resolved.**
- **Mandatory Verification Procedure (STRICT):**
  1. **Clean rebuild:** Rebuild all services affected by the change from the current source tree (e.g., `docker compose up --build`, `npm run build`). Never trust a pre-existing build artifact — stale caches are a common source of false positives.
  2. **Service startup confirmation:** Start all required services and confirm each one is healthy and accepting connections (health endpoints, process status, logs free of fatal errors).
  3. **End-to-end consumer-path verification:** For every entry point that an end user or downstream service would access, issue an actual request through the **same path** the real consumer uses and validate that the response is structurally correct (e.g., expected status code, response body contains required content markers, no error traces). If a service returns rendered content, fetch and inspect the **rendered output** — do not assume correctness from upstream layers alone.
  4. **Functional scenario execution:** Execute the CRUD / workflow scenarios relevant to the change through the consumer-facing path and confirm each operation produces the expected result.
  5. **Failure evidence:** If any step produces unexpected output, capture the exact error or response excerpt and record it as a REJECTED finding.
  6. **Faithful reproduction of user reports (STRICT / ANTI-HALLUCINATION):** When the user reports a problem (e.g., "localhost:3000 で白画面"), that report MUST be treated as an **absolute reproduction instruction**. Reproduce the issue using the **exact same URL, hostname, port, path, method, and steps** the user described — NEVER substitute, rewrite, or "normalize" any part of it (e.g., replacing `localhost` with `127.0.0.1`, changing the port, or altering query parameters). Any deviation from the user's literal report constitutes a hallucinated verification and invalidates the entire dc result. If the reported issue cannot be reproduced as described, record that fact explicitly — do not silently verify a different scenario and declare APPROVED.
- **Append** all results (procedure, observations, verdict) to `review.md`.
- **File Protection Rule (STRICT):** Except for writing to `review.md`, NEVER modify or add any existing source code or files.

### `cp` (Commit & Push)
- **Role:** Release Engineer
- **Recommended Model:** GPT-5.4-mini
- **Task:** Summarize current changes, create a Japanese commit message, and execute `git commit` and `git push`.
- **File Protection Rule (STRICT):** Absolutely NEVER modify or add any existing source code or files.
- **Prohibited:** Do not suggest the next command to execute after completion (the cycle ends here).

### `del` (Environment Cleanup)
- **Role:** Infrastructure Engineer
- **Recommended Model:** GPT-5.4-mini
- **Task:** Completely delete/cleanup execution environments like Docker containers, networks, and volumes started by `dc`.
- **File Protection Rule (STRICT):** Absolutely NEVER modify or add any existing source code or files.

---
## Workflow Cycle
`do ...` or `fix ...` ➡️ `sc` ➡️ `dc` ➡️ (If NG, go to `rr`) ➡️ Next `do ...` or `fix ...`