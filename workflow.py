# workflow.py
import asyncio
import warnings
from google.adk.agents import LoopAgent, SequentialAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps.app import App, EventsCompactionConfig
from google.adk.apps.llm_event_summarizer import LlmEventSummarizer
from agents import (
    _create_resilient_model,
    create_evaluator_agent,
    create_scheduler_agent,
)
from observability import logger, redact_pii
from tools import background_save_state

warnings.filterwarnings("ignore", category=DeprecationWarning, module="google.adk")
warnings.filterwarnings("ignore", message=r".*\[EXPERIMENTAL\].*", category=UserWarning)


def create_hill_climbing_workflow(callbacks: list) -> LoopAgent:
    """Constructs the evaluator-optimizer loop with async Firestore state persistence."""

    # 1. Instantiate the agents
    scheduler = create_scheduler_agent(callbacks)
    evaluator = create_evaluator_agent(callbacks)

    # Break condition for the Hill Climbing loop
    break_condition = (
        lambda context, last_result: "VERDICT: PASSED" in str(last_result)
    )

    def evaluate_break_condition(callback_context: CallbackContext):
        """Checks the latest output, persists state asynchronously, and escalates when passed."""
        session_id = getattr(callback_context.session, "id", "default_session")
        try:
            last_result = ""
            for event in reversed(callback_context.session.events):
                if event.content and event.content.parts:
                    texts = [
                        part.text for part in event.content.parts if part.text
                    ]
                    if texts:
                        last_result = "\n".join(texts).strip()
                        break

            if break_condition(callback_context, last_result):
                callback_context._event_actions.escalate = True
                callback_context.state["verdict"] = "PASSED"

            # Fire-and-forget asynchronous state consolidation to Firestore
            asyncio.create_task(
                background_save_state(
                    session_id, callback_context.state.to_dict()
                )
            )
        except Exception as e:
            logger.warning(
                redact_pii(f"Break condition evaluation warning: {str(e)}"),
                extra={
                    "intent": "evaluate_loop_break_condition",
                    "outcome": "failure",
                    "session_id": session_id,
                },
            )

    # 2. Sequence them
    scheduling_sequence = SequentialAgent(
        name="Scheduling_And_Critique_Sequence",
        sub_agents=[scheduler, evaluator],
        after_agent_callback=[evaluate_break_condition],
    )

    # 3. Wrap in a conditional loop
    return LoopAgent(
        name="Hill_Climbing_Orchestrator",
        sub_agents=[scheduling_sequence],
        max_iterations=3,
        before_agent_callback=[cb.before_agent_run for cb in callbacks],
        after_agent_callback=[cb.after_agent_run for cb in callbacks],
    )


def create_compacting_healthcare_app(
    callbacks: list, app_name: str = "adk_healthcare_app"
) -> App:
    """Factory that wraps the Hill Climbing workflow in an ADK App with out-of-the-box Context Compaction."""
    root_agent = create_hill_climbing_workflow(callbacks)

    summarization_llm = _create_resilient_model("gemini-3.5-flash-lite")
    summarizer = LlmEventSummarizer(llm=summarization_llm)

    compaction_config = EventsCompactionConfig(
        token_threshold=4000,
        event_retention_size=5,
        compaction_interval=3,
        overlap_size=1,
        summarizer=summarizer,
    )

    return App(
        name=app_name,
        root_agent=root_agent,
        events_compaction_config=compaction_config,
    )
