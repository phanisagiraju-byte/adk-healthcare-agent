# tools.py
from google.adk.agents import Context
from google.adk.tools import FunctionTool


# 1. Core Functions
def check_availability(context: Context, doctor_name: str, date: str) -> str:
    """Checks the schedule for a specific doctor on a given date."""
    if doctor_name.lower() == "dr. smith" and date == "2026-10-10":
        return "Dr. Smith has availability at 2:00 PM and 4:00 PM."
    return f"{doctor_name} has no availability on {date}."


def book_appointment(
    context: Context, doctor_name: str, date: str, time: str
) -> str:
    """Books an appointment and stores the confirmation in the global session context."""
    patient_id = context.state.get("patient_id", "UNKNOWN_PATIENT")
    confirmation_string = (
        f"Confirmed with {doctor_name} on {date} at {time} for Patient {patient_id}."
    )

    # Update ADK Context State
    context.state["last_booking"] = confirmation_string
    context.state["booking_status"] = "COMPLETE"

    return f"Success! Appointment booked. Details: {confirmation_string}"


def verify_booking_requirements(context: Context) -> str:
    """Checks the system state to ensure the booking transaction is fully finalized."""
    if context.state.get("booking_status") == "COMPLETE":
        return "Booking is verified and committed to the backend."
    return "Booking transaction is incomplete. Missing patient data or time slot."


# Expose the function as 'verify_booking' to match the evaluator agent's tool name
verify_booking_requirements.__name__ = "verify_booking"


# 2. ADK Tool Factory Methods (Dependency Injection Providers)
def get_scheduler_tools() -> list[FunctionTool]:
    return [
        FunctionTool(func=check_availability),
        FunctionTool(func=book_appointment),
    ]


def get_evaluator_tools() -> list[FunctionTool]:
    return [
        FunctionTool(func=verify_booking_requirements),
    ]
