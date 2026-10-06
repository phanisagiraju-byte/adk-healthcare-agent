# agents.py
from google.adk.agents import LlmAgent
from google.adk.models import BaseLlm, Gemini
from google.genai import types
from tools import get_evaluator_tools, get_scheduler_tools


def _default_retry_options() -> types.HttpRetryOptions:
    """Standard exponential backoff retry configuration for 503/429 resiliency."""
    return types.HttpRetryOptions(
        attempts=5,
        initial_delay=2.0,
        max_delay=10.0,
        exp_base=2.0,
        http_status_codes=[408, 429, 500, 502, 503, 504],
    )


class CriticEvaluatorLlm(Gemini):
    """Dedicated evaluator LLM class for the Critic agent, decoupled from the general worker model."""

    model: str = "gemini-3.6-flash"


def _create_resilient_model(model_name: str = "gemini-3.5-flash-lite") -> BaseLlm:
    """Builds a cost-efficient model instance configured with exponential backoff retries."""
    return Gemini(
        model=model_name,
        retry_options=_default_retry_options(),
    )


def create_execution_model() -> Gemini:
    """Fast, ultra-low-cost Flash-Lite model for high-frequency tool calling and routing."""
    return Gemini(
        model="gemini-3.5-flash-lite",
        retry_options=_default_retry_options(),
    )


def create_reasoning_model() -> CriticEvaluatorLlm:
    """Cost-effective reasoning/critic model class for independent verification and judging."""
    return CriticEvaluatorLlm(
        model="gemini-3.6-flash",
        retry_options=_default_retry_options(),
    )


# Strategic Model Routing instances
execution_model = create_execution_model()
reasoning_model = create_reasoning_model()


def create_scheduler_agent(callbacks: list) -> LlmAgent:
    """Factory method for the scheduling worker agent (routed to Flash-Lite execution_model)."""
    return LlmAgent(
        name="Healthcare_Scheduler",
        description="A patient scheduling assistant designed to find and book medical appointments.",
        model=create_execution_model(),
        tools=get_scheduler_tools(),
        instruction="""
        You are a helpful healthcare scheduler.
        1. If the user wants to book an appointment, use 'check_availability' first.
        2. Once you find a time they want, use 'book_appointment' to lock it in.
        3. You must use the tools to finalize the state.
        4. If a tool returns a 'TOOL ERROR', do not fail—read the error details carefully and either correct the tool parameters or ask the user for valid information.
        """,
        before_agent_callback=[cb.before_agent_run for cb in callbacks],
        after_agent_callback=[cb.after_agent_run for cb in callbacks],
        before_tool_callback=[cb.before_tool_run for cb in callbacks],
        after_tool_callback=[cb.after_tool_run for cb in callbacks],
        on_tool_error_callback=[cb.on_tool_error_run for cb in callbacks],
    )


def create_evaluator_agent(callbacks: list) -> LlmAgent:
    """Factory method for the Critic agent (routed to dedicated CriticEvaluatorLlm reasoning_model)."""
    return LlmAgent(
        name="Booking_Critic",
        description="Evaluates if the appointment booking process is fully finalized.",
        model=create_reasoning_model(),
        tools=get_evaluator_tools(),
        instruction="""
        Run the 'verify_booking' tool.
        If the tool returns that the booking is verified, output exactly: 'VERDICT: PASSED'.
        If the tool returns that the booking is incomplete or a TOOL ERROR occurred, output exactly: 'VERDICT: FAILED. Tell the scheduler to try again and collect missing information.'
        """,
        before_agent_callback=[cb.before_agent_run for cb in callbacks],
        after_agent_callback=[cb.after_agent_run for cb in callbacks],
        before_tool_callback=[cb.before_tool_run for cb in callbacks],
        after_tool_callback=[cb.after_tool_run for cb in callbacks],
        on_tool_error_callback=[cb.on_tool_error_run for cb in callbacks],
    )
