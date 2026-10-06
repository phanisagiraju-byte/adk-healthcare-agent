# main.py
import asyncio
import os
import warnings
from typing import Any, Dict
from dotenv import load_dotenv
from google.adk.apps.app import App, EventsCompactionConfig
from google.adk.runners import InMemoryRunner
from google.genai import types
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from tenacity import retry, stop_after_attempt, wait_exponential

from agents import (
    CriticEvaluatorLlm,
    create_evaluator_agent,
    create_execution_model,
    create_reasoning_model,
    create_scheduler_agent,
)
from observability import (
    TracingObservabilityCallback,
    logger,
    redact_pii,
    redact_pii_data,
)
from tools import background_save_state, get_firestore_client
from workflow import create_compacting_healthcare_app

warnings.filterwarnings("ignore", category=UserWarning, module="google.adk")
load_dotenv(override=True)

if os.path.exists("key.json") and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.abspath("key.json")

# Initialize OpenTelemetry Tracing
if not isinstance(trace.get_tracer_provider(), TracerProvider):
    provider = TracerProvider()
    processor = SimpleSpanProcessor(ConsoleSpanExporter())
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
tracer = trace.get_tracer("adk.healthcare.tracer")

# Strategic Model Routing:
# 1. Fast, ultra-low-cost Flash-Lite model for high-frequency tool calling & routing
execution_model = create_execution_model()
# 2. Dedicated CriticEvaluatorLlm model class for high-accuracy Critic verification
reasoning_model: CriticEvaluatorLlm = create_reasoning_model()


class HealthcareAgentApp:
    """Main Application class for the Healthcare Agent using ADK's native App and EventsCompactionConfig."""

    def __init__(self):
        # Initialize dependencies (Callbacks)
        self.callbacks = [TracingObservabilityCallback()]
        self.app_name = "adk_healthcare_app"

        # Expose strategically routed models and agents
        self.execution_model = execution_model
        self.reasoning_model = reasoning_model
        self.scheduler_agent = create_scheduler_agent(self.callbacks)
        self.critic_agent = create_evaluator_agent(self.callbacks)

        # Build the ADK App with out-of-the-box EventsCompactionConfig and LlmEventSummarizer
        self.adk_app: App = create_compacting_healthcare_app(
            callbacks=self.callbacks,
            app_name=self.app_name,
        )
        self.workflow = self.adk_app.root_agent
        self.compaction_config: EventsCompactionConfig = (
            self.adk_app.events_compaction_config
        )
        self.runner = InMemoryRunner(app=self.adk_app)

    async def _load_firestore_state(self, session_id: str) -> Dict[str, Any]:
        """Attempts to load persisted session state from Firestore if available."""
        with tracer.start_as_current_span("firestore.load_state") as span:
            span.set_attribute("session.id", session_id)
            try:
                db = get_firestore_client()
                doc_snapshot = (
                    await db.collection("patient_sessions")
                    .document(session_id)
                    .get()
                )
                if doc_snapshot.exists:
                    data = doc_snapshot.to_dict() or {}
                    logger.info(
                        "Loaded persisted session state from Firestore",
                        extra={
                            "intent": "load_session_memory",
                            "outcome": "success",
                            "session_id": session_id,
                            "state_summary": redact_pii_data(data),
                        },
                    )
                    return data
            except Exception as e:
                logger.warning(
                    redact_pii(
                        f"Firestore state lookup skipped or unavailable: {str(e)}"
                    ),
                    extra={
                        "intent": "load_session_memory",
                        "outcome": "fallback_in_memory",
                        "session_id": session_id,
                    },
                )
            return {}

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def _execute_runner_with_retry(
        self, user_id: str, session_id: str, user_message: types.Content
    ) -> str:
        """Executes the ADK workflow with exponential backoff retry for transient 503/network failures."""
        with tracer.start_as_current_span("runner.execute_workflow") as span:
            span.set_attribute("session.id", session_id)
            final_result = ""
            async for event in self.runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=user_message,
            ):
                if event.content and event.content.parts:
                    texts = [
                        part.text for part in event.content.parts if part.text
                    ]
                    if texts:
                        final_result = "\n".join(texts).strip()
            return final_result

    async def process_patient_request(
        self, session_id: str, patient_data: Dict[str, str], prompt: str
    ):
        """Executes a request for a given patient session with ADK native compaction, tracing, and Firestore persistence."""
        with tracer.start_as_current_span("process_patient_request") as span:
            span.set_attribute("session.id", session_id)

            logger.info(
                redact_pii(f"Starting ADK Session: {session_id}"),
                extra={
                    "event_type": "session_start",
                    "session_id": session_id,
                    "patient_data": redact_pii_data(patient_data),
                },
            )

            user_id = patient_data.get("patient_id", "default_user")

            # 1. Hydrate from Firestore & merge with incoming patient context
            persisted_state = await self._load_firestore_state(session_id)
            initial_state: Dict[str, Any] = {**persisted_state, **dict(patient_data)}

            # 2. Initialize or update ADK Session
            existing_session = await self.runner.session_service.get_session(
                app_name=self.app_name,
                user_id=user_id,
                session_id=session_id,
            )
            if existing_session is None:
                session = await self.runner.session_service.create_session(
                    app_name=self.app_name,
                    user_id=user_id,
                    session_id=session_id,
                    state=initial_state,
                )
            else:
                session = existing_session
                session.state.update(initial_state)

            # Fire-and-forget asynchronous state save to Firestore
            asyncio.create_task(background_save_state(session_id, initial_state))

            logger.info(
                redact_pii(f"User prompt received: {prompt}"),
                extra={
                    "event_type": "user_prompt",
                    "session_id": session_id,
                    "prompt": redact_pii(prompt),
                },
            )

            # 3. Execute Workflow via ADK Runner (with built-in EventsCompactionConfig & retry protection)
            user_message = types.Content(
                role="user",
                parts=[types.Part.from_text(text=prompt)],
            )

            try:
                final_result = await self._execute_runner_with_retry(
                    user_id=user_id,
                    session_id=session.id,
                    user_message=user_message,
                )
            except Exception as e:
                final_result = (
                    f"ORCHESTRATION ERROR: Service temporarily unavailable after retries ({str(e)}). "
                    "Please try your request again shortly."
                )
                logger.error(
                    redact_pii(final_result),
                    extra={
                        "intent": "execute_hill_climbing_workflow",
                        "outcome": "failure",
                        "session_id": session_id,
                    },
                )

            updated_session = await self.runner.session_service.get_session(
                app_name=self.app_name,
                user_id=user_id,
                session_id=session.id,
            )
            final_state = (
                dict(updated_session.state)
                if updated_session
                else dict(session.state)
            )

            # Consolidate final session state to Firestore asynchronously
            asyncio.create_task(background_save_state(session_id, final_state))

            logger.info(
                "Final Workflow Result",
                extra={
                    "intent": "complete_patient_scheduling_workflow",
                    "outcome": (
                        "success"
                        if "ORCHESTRATION ERROR" not in final_result
                        else "failure"
                    ),
                    "session_id": session_id,
                    "final_result": redact_pii(final_result),
                    "final_session_state": redact_pii_data(final_state),
                },
            )
            return final_result


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
async def safe_process_request(
    app: HealthcareAgentApp,
    session_id: str,
    patient_data: Dict[str, str],
    prompt: str,
):
    """Retry-wrapped entry point for processing a patient request."""
    return await app.process_patient_request(
        session_id=session_id,
        patient_data=patient_data,
        prompt=prompt,
    )


async def main():
    # Setup App
    app = HealthcareAgentApp()

    # Setup mock patient data
    patient_data = {
        "patient_id": "P-98765",
        "patient_name": "Phani Sagiraju",
    }
    prompt = "I need an appointment with Dr. Smith on 2026-10-10 at 4:00 PM."

    # Run the App with retry protection
    await safe_process_request(
        app=app,
        session_id="patient_123_session",
        patient_data=patient_data,
        prompt=prompt,
    )


if __name__ == "__main__":
    asyncio.run(main())
