# ADK Healthcare Scheduling Agent

An AI-powered, autonomous healthcare scheduling agent built using the **Google Agent Development Kit (ADK)** in Python. This project was developed as a Capstone submission for the **AI in 5 Days Assessment (Enterprise / Healthcare Track)**.

## 🎯 Purpose of the Project

The purpose of this project is to automate the patient appointment booking workflow. Scheduling medical appointments often involves multiple turns of checking availability, confirming patient details, and verifying backend system state. 

This agent uses a **Hill Climbing Orchestration Pattern** (Evaluator-Optimizer loop) to ensure that a booking transaction is 100% complete and verified before terminating the conversation. If the booking is incomplete, a "Critic" agent forces the "Worker" agent to try again, ensuring robust, fault-tolerant enterprise automation.

---

## 🏗️ Architecture & Modular Design

This project is built using Object-Oriented Design (OOD) principles, ensuring separation of concerns, dependency injection, and high extensibility.

*   `main.py`: The application entry point. Initializes the session, injects dependencies, and runs the workflow.
*   `workflow.py`: Contains the Orchestration logic (Sequential and Loop Agents).
*   `agents.py`: LLM configurations and prompt instructions for the Worker and Critic agents.
*   `tools.py`: Backend enterprise capabilities (API mocks) exposed to the ADK.
*   `observability.py`: Custom logging and telemetry callbacks.

---

## 🧠 Core ADK Concepts Demonstrated (Assessment Rubric)

### 1. Orchestration & Logic: Where is the Evaluation?
**Location:** `workflow.py` and `agents.py`
Instead of a simple ReAct loop, this system uses an advanced **Multi-Agent Hill Climbing** architecture:
*   **The Worker (`Healthcare_Scheduler`):** Attempts to find availability and book the appointment using tools.
*   **The Critic (`Booking_Critic`):** Uses a deterministic verification tool to check if the transaction was committed to the session state.
*   **The Loop (`Hill_Climbing_Orchestrator`):** A `LoopAgent` wraps a `SequentialAgent`. The loop only breaks when the Critic explicitly outputs `VERDICT: PASSED`. If it fails, the workflow loops back to the Scheduler to fix the error.

### 2. Context & Memory
**Location:** `main.py` and `tools.py`
We use the ADK `Session` object to maintain state across agent turns. Patient data (like `patient_id`) is pre-injected into `session.state`. Tools read from this state and write transaction confirmations back into it, simulating a persistent backend memory bank.

### 3. Tool & Interface Design
**Location:** `tools.py`
Python functions are wrapped in ADK `FunctionTool` objects. These tools abstract the backend logic (checking doctor availability, committing a booking) and use type hints and docstrings so the Gemini model understands exactly when and how to invoke them.

### 4. Observability & Tracing
**Location:** `observability.py`
A custom `TracingObservabilityCallback` is implemented to hook into the ADK lifecycle (`before_agent_run`, `after_agent_run`, `before_tool_run`). This streams deep execution traces to the console, making it easy to debug and monitor in a production environment like Google Cloud Logging.

---

## 🚀 How to Run the Project

### Prerequisites
*   A gLinux/Debian environment (like Jetski or Cloudtop).
*   Python 3.13 installed (with the `python3.13-venv` package).
*   A Google Cloud Project (e.g., Argolis) with the **Vertex AI API** enabled.

### 1. Set Up the Environment
Clone the repository and navigate into the project folder. Then, create and activate a virtual environment:

```bash
# Create the virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate

# Install the Google Agent Development Kit and dependencies
pip install -r requirements.txt
```

### 2. Configure Vertex AI Environment Variables
Create a `.env` file in the root directory with your Google Cloud project settings:

```env
GOOGLE_GENAI_USE_VERTEXAI="TRUE"
GOOGLE_CLOUD_PROJECT="<YOUR_PROJECT_ID>"
GOOGLE_CLOUD_LOCATION="global"
```

### 3. Execute the Application
Run the main entry point:

```bash
python main.py
```
