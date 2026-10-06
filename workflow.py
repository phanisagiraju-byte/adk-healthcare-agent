# workflow.py
import warnings
from google.adk.agents import LoopAgent, SequentialAgent
from google.adk.agents.callback_context import CallbackContext
from agents import create_evaluator_agent, create_scheduler_agent

warnings.filterwarnings("ignore", category=DeprecationWarning, module="google.adk")


def create_hill_climbing_workflow(callbacks: list) -> LoopAgent:
    """Constructs the evaluator-optimizer loop."""

    # 1. Instantiate the agents
    scheduler = create_scheduler_agent(callbacks)
    evaluator = create_evaluator_agent(callbacks)

    # Break condition for the Hill Climbing loop
    break_condition = (
        lambda context, last_result: "VERDICT: PASSED" in str(last_result)
    )

    def evaluate_break_condition(callback_context: CallbackContext):
        """Checks the latest output and escalates to break the LoopAgent when passed."""
        last_result = ""
        for event in reversed(callback_context.session.events):
            if event.content and event.content.parts:
                texts = [part.text for part in event.content.parts if part.text]
                if texts:
                    last_result = "\n".join(texts).strip()
                    break

        if break_condition(callback_context, last_result):
            callback_context._event_actions.escalate = True
            callback_context.state["verdict"] = "PASSED"

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
