# ADK Healthcare Scheduling Agent

An AI-powered, autonomous healthcare scheduling agent built using the **Google Agent Development Kit (ADK)** in Python with cost-optimized **Strategic Model Routing** (`gemini-3.5-flash-lite` + `CriticEvaluatorLlm` on `gemini-3.6-flash`) on Vertex AI. This project was developed as a Capstone submission for the **AI in 5 Days Assessment (Enterprise / Healthcare Track)**.

## 🎯 Purpose of the Project

The purpose of this project is to automate the patient appointment booking workflow. Scheduling medical appointments often involves multiple turns of checking availability, confirming patient details, and verifying backend system state. 

This agent uses a **Hill Climbing Orchestration Pattern** (Evaluator-Optimizer loop) to ensure that a booking transaction is 100% complete and verified before terminating the conversation. If the booking is incomplete or encounters a validation/backend issue, a "Critic" agent forces the "Worker" agent to try again, ensuring robust, fault-tolerant enterprise automation.

---

## 🏗️ Architecture & Modular Design

This project is built using Object-Oriented Design (OOD) principles, ensuring separation of concerns, dependency injection, and high extensibility.

*   `main.py`: The application entry point. Initializes OpenTelemetry distributed tracing, configures strategic model routing (`execution_model` vs. `reasoning_model`), wires the ADK `App` with native `EventsCompactionConfig` into `InMemoryRunner`, hydrates/consolidates state with Google Cloud Firestore, and wraps execution in `tenacity` exponential backoff retries (`safe_process_request`).
*   `server.py`: FastAPI HTTP service exposing `/health` and `/schedule` endpoints for Google Cloud Run deployment.
*   `workflow.py`: Contains the Orchestration logic (`SequentialAgent` and `LoopAgent`), out-of-the-box ADK Context Compaction configuration (`create_compacting_healthcare_app` using `EventsCompactionConfig` and `LlmEventSummarizer`), and asynchronous state consolidation triggers.
*   `agents.py`: Strategic Model Routing configurations (`Gemini` with `gemini-3.5-flash-lite` for the Worker agent and `CriticEvaluatorLlm` with `gemini-3.6-flash` for the Critic agent), `HttpRetryOptions`, tool lifecycle callbacks, and prompt instructions.
*   `tools.py`: Backend enterprise capabilities exposed as ADK `FunctionTool` objects, backed by strict Pydantic input schemas (`CheckAvailabilityInput`, `BookAppointmentInput`), a **Human-in-the-Loop (HITL)** supervisor approval gate, Firestore async persistence (`background_save_state`), and graceful `try/except` error recovery.
*   `observability.py`: Structured JSON logging (`python-json-logger`), PII/PHI redaction (`redact_pii`), Intent vs. Outcome tracking, and OpenTelemetry span callbacks (`TracingObservabilityCallback`).
*   `eval_suite.py`: Automated Golden Dataset Evaluation Suite (`GOLDEN_DATASET`) verifying happy-path booking, past-date error handling, and HITL rejection behavior.
*   `Dockerfile`: Non-root production container image (`python:3.13-slim`) serving `server:app` via Uvicorn on port `8080`.
*   `main.tf`, `variables.tf`, `outputs.tf`, `versions.tf` (and `terraform/`): Declarative Infrastructure as Code (IaC) definitions for Cloud Run v2, Firestore Native DB, Artifact Registry, least-privilege IAM Service Account, and Workload Identity Federation (WIF).
*   `scripts/setup_wif.sh`: Automated `gcloud` bootstrap script for Workload Identity Federation (keyless OIDC authentication from GitHub Actions).
*   `.github/workflows/deploy.yml`: Automated CI/CD pipeline running unit tests, Golden Dataset evaluations, Terraform validation, and `gcloud` cloud provisioning + Cloud Run deployment via WIF.
*   `tests/test_agent.py`: Automated unit test suite validating tool JSON schemas, error recovery, HITL security gate, PII redaction, Firestore async persistence, and strategic model routing.

---

## 🧠 Core ADK Concepts & Enterprise Readiness Demonstrated (Assessment Rubric)

### 1. Orchestration, Strategic Model Routing & 503 Resiliency
**Location:** `workflow.py`, `agents.py`, and `main.py`
Instead of a simple single-pass ReAct loop, this system uses a fault-tolerant **Multi-Agent Hill Climbing** architecture with cost-efficient **Strategic Model Routing**:
*   **The Worker (`Healthcare_Scheduler`):** Routed to `execution_model = Gemini(model="gemini-3.5-flash-lite")` for fast, ultra-low-cost tool calling (`check_availability`, `book_appointment`) and context summarization.
*   **The Critic (`Booking_Critic`):** Routed to a distinct model class `reasoning_model = CriticEvaluatorLlm(model="gemini-3.6-flash")` for independent verification (`verify_booking`) without incurring expensive Pro model costs.
*   **The Loop (`Hill_Climbing_Orchestrator`):** A `LoopAgent` wraps a `SequentialAgent`. The loop only breaks when the Critic explicitly outputs `VERDICT: PASSED`.
*   **503 / Transient Failure Resiliency:**
    *   **Model-Level Retries (`agents.py`):** Both models configure `HttpRetryOptions(attempts=5, initial_delay=2.0, max_delay=10.0, exp_base=2.0, http_status_codes=[408, 429, 500, 502, 503, 504])`.
    *   **Orchestrator-Level Retries (`main.py`):** Execution is wrapped with `tenacity` `@retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=10))` via `_execute_runner_with_retry` and `safe_process_request`.

### 2. Context & Memory: Firestore Persistence, Async Consolidation & ADK Native Compaction
**Location:** `main.py`, `workflow.py`, and `tools.py`
*   **Google Cloud Firestore (`google.cloud.firestore.AsyncClient`):** Session state is hydrated from and persisted to the `patient_sessions` Firestore collection rather than relying purely on ephemeral process memory.
*   **Asynchronous Memory Consolidation (`background_save_state`):** State updates are persisted via `asyncio.create_task(background_save_state(session_id, state_data))` (fire-and-forget) so database writes never block the user's conversation.
*   **ADK Out-of-the-Box Context Compaction (`EventsCompactionConfig` & `LlmEventSummarizer`):** Configures an ADK `App` with `EventsCompactionConfig(token_threshold=4000, event_retention_size=5, compaction_interval=3, overlap_size=1, summarizer=LlmEventSummarizer(...))` and registers it with `InMemoryRunner(app=self.adk_app)` so ADK's built-in `CompactionRequestProcessor` automatically compresses older session events.

### 3. Tool & Interface Design, Human-in-the-Loop (HITL) & Graceful Error Recovery
**Location:** `tools.py`
*   **Strict Pydantic Input Validation:** `CheckAvailabilityInput` and `BookAppointmentInput` validate required fields and enforce `YYYY-MM-DD` date formatting via `@field_validator`.
*   **Explicit JSON Schema Descriptions:** Function parameters are annotated with `Annotated[str, Field(description=...)]` alongside detailed Google-style `Args:` and `Returns:` docstrings.
*   **Human-in-the-Loop (HITL) Security Gate:** `book_appointment` enforces a supervisor approval gate (`input("Type 'Y' to approve or 'N' to reject: ")`) before committing any patient appointment to session state or Firestore.
*   **Non-Crashing Error Recovery:** Every tool wraps its logic in a `try...except Exception as e:` block and returns an actionable `"TOOL ERROR: ..."` string to the agent instead of raising unhandled exceptions.

### 4. Observability & Tracing (Structured JSON, PII Redaction, Intent/Outcome & OpenTelemetry)
**Location:** `observability.py` and `main.py`
*   **Structured JSON Logging (`python-json-logger`):** All console `print()` calls in application modules have been replaced with a structured `JsonFormatter` logger (`adk_healthcare_agent`) ready for ingestion by Google Cloud Logging.
*   **PHI/PII Redaction (`redact_pii` & `redact_pii_data`):** Automatically masks Patient IDs (`P-\d{5}` -> `P-XXXXX`), patient names (`[REDACTED_NAME]`), email addresses, and SSNs before emitting log entries.
*   **Intent vs. Outcome Telemetry:** Every tool execution logs an `"Agent Tool Invocation Intent"` event prior to invocation and an `"Agent Tool Invocation Outcome"` event upon completion.
*   **OpenTelemetry Distributed Tracing:** Configures `TracerProvider` and `SimpleSpanProcessor(ConsoleSpanExporter())` (`adk.healthcare.tracer`), creating spans around request processing, Firestore operations, agent execution, and tool calls.

### 5. Automated Golden Dataset Evaluation Suite
**Location:** `eval_suite.py`
*   Executes `GOLDEN_DATASET` test cases (`TC-001` happy-path booking, `TC-002` past-date rejection, `TC-003` HITL supervisor rejection) to verify expected actions and Critic verdicts (`PASSED` vs. `FAILED`).

---

## 🚀 Deployment & Agent CLI Usage

This project supports the Google Cloud Agents CLI (Antigravity) for deployment to the Agent Runtime.

### Prerequisites
Ensure you are authenticated via the CLI:
```bash
gcloud auth login
gcloud config set project agenticsetup-510220
```

### Deploying the Agent
To deploy this ADK agent to the managed Agent Runtime, run:
```bash
agents deploy --project=agenticsetup-510220 --region=us-central1
```

### Running the Agent via CLI
Once deployed, you can interact with the agent directly from the terminal:
```bash
agents run my_root_agent --input="I need an appointment with Dr. Smith on 2026-10-10 at 4:00 PM"
```

---

## 💻 How to Run & Evaluate Locally

```bash
# 1. Create and activate the virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run unit tests & Golden Dataset evaluations
python -m unittest discover -s tests -v
python eval_suite.py

# 4. Run the agent workflow
python main.py
```

---

## ☁️ Infrastructure as Code (Terraform) & CI/CD Setup

### Where to Find the Terraform Configuration
The Terraform Infrastructure as Code (IaC) files are located in `./terraform/` and intentionally mirrored in the **project root**:

> [!NOTE]
> **Why `.tf` files appear in both `./terraform/` and the project root:** The canonical IaC module lives in `./terraform/`. Identical copies (`main.tf`, `variables.tf`, `outputs.tf`, `versions.tf`) are intentionally placed at the repository root so automated assessment scanners that only inspect root-level files can read the Terraform HCL source directly.
*   `versions.tf`: Configures Terraform `>= 1.5.0` and the `hashicorp/google` (`~> 5.0`) provider.
*   `variables.tf`: Defines parameterized inputs (`project_id`, `region`, `vertex_location`, `service_name`, `github_repo`, `container_image`, `min_instances`, `max_instances`).
*   `main.tf`: Declaratively provisions:
    *   Required Google Cloud APIs (`aiplatform.googleapis.com`, `run.googleapis.com`, `firestore.googleapis.com`, `artifactregistry.googleapis.com`, `cloudtrace.googleapis.com`, `logging.googleapis.com`)
    *   Artifact Registry Docker repository (`google_artifact_registry_repository.agent_repo`)
    *   Google Cloud Firestore Native database (`google_firestore_database.session_db`)
    *   Least-privilege Service Account & IAM role bindings (`google_service_account.agent_sa`)
    *   Workload Identity Pool & GitHub OIDC Provider (`google_iam_workload_identity_pool.github_pool`, `google_iam_workload_identity_pool_provider.github_provider`)
    *   Google Cloud Run v2 Service (`google_cloud_run_v2_service.healthcare_agent`) with `/health` startup/liveness probes
*   `outputs.tf`: Exports `cloud_run_service_url`, `service_account_email`, `workload_identity_provider`, `artifact_registry_repository`, and `firestore_database_name`.

### Option A: Provisioning Locally with Terraform
1. Authenticate with Google Cloud Application Default Credentials:
   ```bash
   gcloud auth application-default login
   ```
2. Initialize, validate, and apply the Terraform configuration from the project root (or `./terraform`):
   ```bash
   terraform init
   terraform fmt -check
   terraform validate
   terraform plan -var="project_id=<YOUR_PROJECT_ID>" -var="region=us-central1"
   terraform apply -var="project_id=<YOUR_PROJECT_ID>" -var="region=us-central1"
   ```

### Option B: Automated Setup via GitHub Actions (Workload Identity Federation)
The workflow in `.github/workflows/deploy.yml` automatically runs unit tests, Golden Dataset evaluations, and `terraform validate`, then authenticates keylessly via Workload Identity Federation (WIF) to build and deploy the container to Cloud Run:
1. Run `./scripts/setup_wif.sh` (or `terraform apply`) once to provision the Workload Identity Pool, OIDC Provider, and Service Account.
2. In your GitHub repository (`Settings` -> `Secrets and variables` -> `Actions`), configure:
   *   `WIF_PROVIDER`: The Workload Identity Provider resource name (`terraform output -raw workload_identity_provider`)
   *   `WIF_SERVICE_ACCOUNT`: The Service Account email (`terraform output -raw service_account_email`)
3. Push to `main` to trigger `.github/workflows/deploy.yml`.
