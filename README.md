# ADK Healthcare Scheduling Agent

An AI-powered, autonomous healthcare scheduling agent built using the **Google Agent Development Kit (ADK)** in Python and powered by **Gemini 3.6 Flash** on Vertex AI. This project was developed as a Capstone submission for the **AI in 5 Days Assessment (Enterprise / Healthcare Track)**.

## 🎯 Purpose of the Project

The purpose of this project is to automate the patient appointment booking workflow. Scheduling medical appointments often involves multiple turns of checking availability, confirming patient details, and verifying backend system state. 

This agent uses a **Hill Climbing Orchestration Pattern** (Evaluator-Optimizer loop) to ensure that a booking transaction is 100% complete and verified before terminating the conversation. If the booking is incomplete or encounters a validation/backend issue, a "Critic" agent forces the "Worker" agent to try again, ensuring robust, fault-tolerant enterprise automation.

---

## 🏗️ Architecture & Modular Design

This project is built using Object-Oriented Design (OOD) principles, ensuring separation of concerns, dependency injection, and high extensibility.

*   `main.py`: The application entry point. Initializes OpenTelemetry distributed tracing, wires the ADK `App` with native `EventsCompactionConfig` into `InMemoryRunner`, hydrates/consolidates state with Google Cloud Firestore, and wraps execution in `tenacity` exponential backoff retries (`safe_process_request`).
*   `server.py`: FastAPI HTTP service exposing `/health` and `/schedule` endpoints for Google Cloud Run deployment.
*   `workflow.py`: Contains the Orchestration logic (`SequentialAgent` and `LoopAgent`), out-of-the-box ADK Context Compaction configuration (`create_compacting_healthcare_app` using `EventsCompactionConfig` and `LlmEventSummarizer`), and asynchronous state consolidation triggers.
*   `agents.py`: LLM configurations (`Gemini` with `HttpRetryOptions`), tool lifecycle callbacks, and prompt instructions for the Worker and Critic agents.
*   `tools.py`: Backend enterprise capabilities exposed as ADK `FunctionTool` objects, backed by strict Pydantic input schemas (`CheckAvailabilityInput`, `BookAppointmentInput`), Firestore async persistence (`background_save_state`), and graceful `try/except` error recovery.
*   `observability.py`: Structured JSON logging (`python-json-logger`), PII/PHI redaction (`redact_pii`), Intent vs. Outcome tracking, and OpenTelemetry span callbacks (`TracingObservabilityCallback`).
*   `Dockerfile`: Non-root production container image (`python:3.13-slim`) serving `server:app` via Uvicorn on port `8080`.
*   `terraform/`: Declarative Infrastructure as Code (IaC) definitions for Cloud Run v2, Firestore Native DB, Artifact Registry, least-privilege IAM Service Account, and Workload Identity Federation (WIF).
*   `scripts/setup_wif.sh`: Automated `gcloud` bootstrap script for Workload Identity Federation (keyless OIDC authentication from GitHub Actions).
*   `.github/workflows/deploy.yml`: Automated CI/CD pipeline running unit tests, Terraform validation, and `gcloud` cloud provisioning + Cloud Run deployment via WIF.
*   `tests/test_agent.py`: Automated unit test suite validating tool JSON schemas, error recovery, PII redaction, Firestore async persistence, and ADK compaction/retry settings.

---

## 🧠 Core ADK Concepts & Enterprise Readiness Demonstrated (Assessment Rubric)

### 1. Orchestration & Resiliency: Hill Climbing + 503 Retry Backoff
**Location:** `workflow.py`, `agents.py`, and `main.py`
Instead of a simple single-pass ReAct loop, this system uses a fault-tolerant **Multi-Agent Hill Climbing** architecture:
*   **The Worker (`Healthcare_Scheduler`):** Attempts to find availability and book the appointment using tools, and is instructed to self-correct when a tool returns a `TOOL ERROR`.
*   **The Critic (`Booking_Critic`):** Uses a deterministic verification tool (`verify_booking`) to confirm that the transaction was committed to the session state.
*   **The Loop (`Hill_Climbing_Orchestrator`):** A `LoopAgent` wraps a `SequentialAgent`. The loop only breaks when the Critic explicitly outputs `VERDICT: PASSED`. If it fails, the workflow loops back to the Scheduler to fix the error.
*   **503 / Transient Failure Resiliency:**
    *   **Model-Level Retries (`agents.py`):** Both agents configure `Gemini(model="gemini-3.6-flash")` with `HttpRetryOptions(attempts=5, initial_delay=2.0, max_delay=10.0, exp_base=2.0, http_status_codes=[408, 429, 500, 502, 503, 504])`.
    *   **Orchestrator-Level Retries (`main.py`):** Execution is wrapped with `tenacity` `@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=10))` via `_execute_runner_with_retry` and `safe_process_request`, with graceful fallback handling if upstream services remain unavailable.

### 2. Context & Memory: Firestore Persistence, Async Consolidation & ADK Native Compaction
**Location:** `main.py`, `workflow.py`, and `tools.py`
*   **Google Cloud Firestore (`google.cloud.firestore.AsyncClient`):** Session state is hydrated from and persisted to the `patient_sessions` Firestore collection rather than relying purely on ephemeral process memory.
*   **Asynchronous Memory Consolidation (`background_save_state`):** State updates are persisted via `asyncio.create_task(background_save_state(session_id, state_data))` (fire-and-forget) so database writes never block the user's conversation.
*   **ADK Out-of-the-Box Context Compaction (`EventsCompactionConfig` & `LlmEventSummarizer`):** Configures an ADK `App` with `EventsCompactionConfig(token_threshold=4000, event_retention_size=5, compaction_interval=3, overlap_size=1, summarizer=LlmEventSummarizer(...))` and registers it with `InMemoryRunner(app=self.adk_app)` so ADK's built-in `CompactionRequestProcessor` automatically compresses older session events using both token-based and sliding-window strategies.

### 3. Tool & Interface Design (Strict Schemas & Graceful Error Recovery)
**Location:** `tools.py`
*   **Strict Pydantic Input Validation:** `CheckAvailabilityInput` and `BookAppointmentInput` validate required fields and enforce `YYYY-MM-DD` date formatting via `@field_validator`.
*   **Explicit JSON Schema Descriptions:** Function parameters are annotated with `Annotated[str, Field(description=...)]` alongside detailed Google-style `Args:` and `Returns:` docstrings so ADK generates complete JSON Schema parameter descriptions for the LLM.
*   **Non-Crashing Error Recovery:** Every tool wraps its logic in a `try...except Exception as e:` block (checking domain rules such as rejecting past dates `< 2026-10-06`) and returns an actionable `"TOOL ERROR: ..."` string to the agent instead of raising unhandled exceptions.

### 4. Observability & Tracing (Structured JSON, PII Redaction, Intent/Outcome & OpenTelemetry)
**Location:** `observability.py` and `main.py`
*   **Structured JSON Logging (`python-json-logger`):** All console `print()` calls have been replaced with a structured `JsonFormatter` logger (`adk_healthcare_agent`) ready for ingestion by Google Cloud Logging.
*   **PHI/PII Redaction (`redact_pii` & `redact_pii_data`):** Automatically masks Patient IDs (`P-\d{5}` -> `P-XXXXX`), patient names (`[REDACTED_NAME]`), email addresses, and SSNs before emitting log entries.
*   **Intent vs. Outcome Telemetry:** Every tool execution logs an `"Agent Tool Invocation Intent"` event (`intent`, `target_tool`, `session_id`) prior to invocation and an `"Agent Tool Invocation Outcome"` event (`outcome: "success" | "failure"`, `result_summary`, `session_id`) upon completion.
*   **OpenTelemetry Distributed Tracing:** Configures `TracerProvider` and `SimpleSpanProcessor(ConsoleSpanExporter())` (`adk.healthcare.tracer`), creating spans around request processing, Firestore operations, agent execution, and tool calls.

### 5. Infrastructure as Code (Terraform) & Keyless CI/CD (Workload Identity Federation + GitHub Actions)
**Location:** `terraform/`, `scripts/setup_wif.sh`, `Dockerfile`, and `.github/workflows/deploy.yml`
*   **Keyless Authentication (WIF):** Uses Workload Identity Federation (`google-github-actions/auth@v2`) so GitHub Actions authenticates to Google Cloud via OIDC without storing long-lived service account JSON keys.
*   **Automated Cloud Provisioning & Deployment:** On push to `main`, GitHub Actions runs unit tests, validates Terraform scripts, enables required GCP APIs, ensures Firestore and Artifact Registry exist, builds and pushes the non-root Docker image, and deploys the service to Google Cloud Run.

---

## 🚀 How to Run Locally

```bash
# 1. Create and activate the virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run unit tests
python -m unittest discover -s tests -v

# 4. Run the agent workflow
python main.py
```

---

## ☁️ How to Deploy with Workload Identity Federation & GitHub Actions

### Step 1: Bootstrap Workload Identity Federation (One-Time Setup)
From a terminal authenticated with `gcloud` (`gcloud auth login`), run:

```bash
./scripts/setup_wif.sh
```

This script enables the required APIs, creates the least-privilege service account (`adk-healthcare-agent-sa`), creates the Workload Identity Pool & GitHub OIDC Provider scoped to `phanisagiraju-byte/adk-healthcare-agent`, and prints two values:
*   `WIF_PROVIDER`
*   `WIF_SERVICE_ACCOUNT`

### Step 2: Add GitHub Repository Secrets
In your GitHub repository (`Settings` -> `Secrets and variables` -> `Actions` -> `New repository secret`), add:
*   `WIF_PROVIDER`: The full provider resource path output by `setup_wif.sh`
*   `WIF_SERVICE_ACCOUNT`: `adk-healthcare-agent-sa@agenticsetup-510220.iam.gserviceaccount.com`

### Step 3: Push to `main`
Push your changes to trigger the `.github/workflows/deploy.yml` pipeline:

```bash
git add .
git commit -m "Phase 3: Add Terraform IaC, Dockerfile, WIF setup, and GitHub Actions CI/CD"
git push origin main
```
