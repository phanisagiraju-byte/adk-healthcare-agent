# agents.py
from google.adk.agents import LlmAgent
from tools import get_evaluator_tools, get_scheduler_tools


def create_scheduler_agent(callbacks: list) -> LlmAgent:
    """Factory method for the scheduling worker agent."""
    return LlmAgent(
        name="Healthcare_Scheduler",
        description="A patient scheduling assistant designed to find and book medical appointments.",
        model="gemini-3.6-flash",
        tools=get_scheduler_tools(),
        instruction="""
        You are a helpful healthcare scheduler.
        1. If the user wants to book an appointment, use 'check_availability' first.
        2. Once you find a time they want, use 'book_appointment' to lock it in.
        3. You must use the tools to finalize the state.
        """,
        before_agent_callback=[cb.before_agent_run for cb in callbacks],
        after_agent_callback=[cb.after_agent_run for cb in callbacks],
        before_tool_callback=[cb.before_tool_run for cb in callbacks],
    )


def create_evaluator_agent(callbacks: list) -> LlmAgent:
    """Factory method for the Critic agent."""
    return LlmAgent(
        name="Booking_Critic",
        description="Evaluates if the appointment booking process is fully finalized.",
        model="gemini-3.6-flash",
        tools=get_evaluator_tools(),
        instruction="""
        Run the 'verify_booking' tool.
        If the tool returns that the booking is verified, output exactly: 'VERDICT: PASSED'.
        If the tool returns that the booking is incomplete, output exactly: 'VERDICT: FAILED. Tell the scheduler to try again and collect missing information.'
        """,
        before_agent_callback=[cb.before_agent_run for cb in callbacks],
        after_agent_callback=[cb.after_agent_run for cb in callbacks],
        before_tool_callback=[cb.before_tool_run for cb in callbacks],
    )
