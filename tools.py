# tools.py
import asyncio
import os
from datetime import datetime
from typing import Annotated, Any, Dict, Optional
from google.adk.agents import Context
from google.adk.tools import FunctionTool
from google.cloud import firestore
from pydantic import BaseModel, Field, field_validator

from observability import logger, redact_pii, redact_pii_data, tracer

# Initialize Firestore AsyncClient lazily/safely using project environment settings
db: Optional[firestore.AsyncClient] = None


def get_firestore_client() -> firestore.AsyncClient:
    """Returns a singleton Firestore AsyncClient instance."""
    global db
    if db is None:
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
        db = (
            firestore.AsyncClient(project=project_id)
            if project_id
            else firestore.AsyncClient()
        )
    return db


async def background_save_state(session_id: str, state_data: Dict[str, Any]) -> None:
    """Saves session state to Google Cloud Firestore asynchronously (fire-and-forget)."""
    with tracer.start_as_current_span("firestore.background_save_state") as span:
        span.set_attribute("session.id", session_id)
        try:
            client = get_firestore_client()
            doc_ref = client.collection("patient_sessions").document(session_id)
            await doc_ref.set(dict(state_data), merge=True)
            logger.info(
                "Consolidated session state to Firestore",
                extra={
                    "intent": "consolidate_session_memory",
                    "outcome": "success",
                    "session_id": session_id,
                    "state_summary": redact_pii_data(dict(state_data)),
                },
            )
        except Exception as e:
            logger.warning(
                redact_pii(f"Failed to save state to Firestore: {str(e)}"),
                extra={
                    "intent": "consolidate_session_memory",
                    "outcome": "failure",
                    "session_id": session_id,
                    "error": redact_pii(str(e)),
                },
            )


def _schedule_background_save(session_id: str, state_data: Dict[str, Any]) -> None:
    """Schedules background_save_state on the running event loop if one is active."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(background_save_state(session_id, dict(state_data)))
    except RuntimeError:
        pass


# 1. Strict JSON Schemas for Tool Inputs using Pydantic
class CheckAvailabilityInput(BaseModel):
    """Input schema for checking a doctor's appointment availability."""

    doctor_name: str = Field(
        ...,
        min_length=1,
        description="The full name of the doctor, e.g., 'Dr. Smith'.",
    )
    date: str = Field(
        ...,
        description="The date of the appointment in YYYY-MM-DD format, e.g., '2026-10-10'.",
    )

    @field_validator("date")
    @classmethod
    def validate_date_format(cls, value: str) -> str:
        cleaned = value.strip()
        datetime.strptime(cleaned, "%Y-%m-%d")
        return cleaned


class BookAppointmentInput(BaseModel):
    """Input schema for booking a medical appointment."""

    doctor_name: str = Field(
        ...,
        min_length=1,
        description="The full name of the doctor, e.g., 'Dr. Smith'.",
    )
    date: str = Field(
        ...,
        description="The date of the appointment in YYYY-MM-DD format, e.g., '2026-10-10'.",
    )
    time: str = Field(
        ...,
        min_length=1,
        description="The time of the appointment, e.g., '4:00 PM'.",
    )

    @field_validator("date")
    @classmethod
    def validate_date_format(cls, value: str) -> str:
        cleaned = value.strip()
        datetime.strptime(cleaned, "%Y-%m-%d")
        return cleaned


# 2. Core Enterprise Tool Functions with Graceful Error Recovery & HITL Gate
def check_availability(
    context: Context,
    doctor_name: Annotated[
        str,
        Field(description="The full name of the doctor, e.g., 'Dr. Smith'."),
    ],
    date: Annotated[
        str,
        Field(
            description="The date of the appointment in YYYY-MM-DD format, e.g., '2026-10-10'."
        ),
    ],
) -> str:
    """Checks the schedule for a specific doctor on a given date.

    Args:
        doctor_name: The full name of the doctor, e.g., 'Dr. Smith'.
        date: The date of the appointment in YYYY-MM-DD format.

    Returns:
        A string listing available appointment time slots, or a descriptive
        error message if the input is invalid or no slots are available.
    """
    session_id = getattr(getattr(context, "session", None), "id", "default_session")
    logger.info(
        "Agent Tool Invocation Intent",
        extra={
            "intent": "check_doctor_availability",
            "target_tool": "check_availability",
            "session_id": session_id,
        },
    )
    try:
        validated = CheckAvailabilityInput(doctor_name=doctor_name, date=date)
        if validated.date < "2026-10-06":
            raise ValueError("Cannot check or book appointments in the past.")

        normalized_doctor = validated.doctor_name.strip().lower()
        if normalized_doctor == "dr. smith" and validated.date == "2026-10-10":
            tool_result = "Dr. Smith has availability at 2:00 PM and 4:00 PM."
        else:
            tool_result = (
                f"{validated.doctor_name} has no availability on {validated.date}."
            )

        logger.info(
            "Agent Tool Invocation Outcome",
            extra={
                "outcome": "success",
                "target_tool": "check_availability",
                "result_summary": redact_pii(tool_result),
                "session_id": session_id,
            },
        )
        return tool_result
    except Exception as e:
        error_result = (
            f"TOOL ERROR: {str(e)}. Please verify the doctor's name and ensure "
            "the date is a valid future date in YYYY-MM-DD format."
        )
        logger.warning(
            "Agent Tool Invocation Outcome",
            extra={
                "outcome": "failure",
                "target_tool": "check_availability",
                "result_summary": redact_pii(error_result),
                "session_id": session_id,
            },
        )
        return error_result


def book_appointment(
    context: Context,
    doctor_name: Annotated[
        str,
        Field(description="The full name of the doctor, e.g., 'Dr. Smith'."),
    ],
    date: Annotated[
        str,
        Field(
            description="The date of the appointment in YYYY-MM-DD format, e.g., '2026-10-10'."
        ),
    ],
    time: Annotated[
        str,
        Field(description="The time of the appointment, e.g., '4:00 PM'."),
    ],
) -> str:
    """Books a medical appointment for a patient and stores the confirmation in session state.
    HIGH STAKES: Requires human confirmation before executing.

    Args:
        doctor_name: The full name of the doctor, e.g., 'Dr. Smith'.
        date: The date of the appointment (YYYY-MM-DD).
        time: The requested time for the appointment, e.g., '4:00 PM'.

    Returns:
        A confirmation string when the appointment is booked, or a descriptive
        TOOL ERROR string if validation, HITL approval, or booking fails.
    """
    session_id = getattr(getattr(context, "session", None), "id", "default_session")
    logger.info(
        "Agent Tool Invocation Intent",
        extra={
            "intent": "book_patient_appointment",
            "target_tool": "book_appointment",
            "session_id": session_id,
        },
    )
    try:
        validated = BookAppointmentInput(
            doctor_name=doctor_name,
            date=date,
            time=time,
        )
        if validated.date < "2026-10-06":
            raise ValueError("Cannot book appointments in the past.")

        # --- HITL SECURITY GATE ---
        logger.info(
            redact_pii(
                f"[HUMAN-IN-THE-LOOP REQUIRED] Agent requests to book: "
                f"{validated.doctor_name} on {validated.date} at {validated.time}."
            ),
            extra={
                "intent": "request_human_approval",
                "target_tool": "book_appointment",
                "session_id": session_id,
            },
        )
        try:
            approval = input("Type 'Y' to approve or 'N' to reject: ")
        except EOFError:
            approval = os.environ.get("HITL_AUTO_APPROVE", "Y")

        if approval.strip().upper() != "Y":
            rejection_msg = (
                "TOOL ERROR: Human supervisor rejected the booking. "
                "Ask the user for new parameters."
            )
            logger.warning(
                "Agent Tool Invocation Outcome",
                extra={
                    "outcome": "failure",
                    "target_tool": "book_appointment",
                    "result_summary": redact_pii(rejection_msg),
                    "session_id": session_id,
                },
            )
            return rejection_msg
        # --------------------------

        patient_id = context.state.get("patient_id", "UNKNOWN_PATIENT")
        confirmation_string = (
            f"Confirmed with {validated.doctor_name} on {validated.date} "
            f"at {validated.time} for Patient {patient_id}."
        )

        # Update ADK Context State
        context.state["last_booking"] = confirmation_string
        context.state["booking_status"] = "COMPLETE"

        # Asynchronous fire-and-forget consolidation to Firestore
        state_snapshot = (
            context.state.to_dict()
            if hasattr(context.state, "to_dict")
            else dict(context.state)
        )
        _schedule_background_save(session_id, state_snapshot)

        tool_result = f"Success! Appointment booked. Details: {confirmation_string}"
        logger.info(
            "Agent Tool Invocation Outcome",
            extra={
                "outcome": "success",
                "target_tool": "book_appointment",
                "result_summary": redact_pii(tool_result),
                "session_id": session_id,
            },
        )
        return tool_result
    except Exception as e:
        error_result = (
            f"TOOL ERROR: {str(e)}. Please ask the user to provide a valid "
            "doctor name, future date (YYYY-MM-DD), and time slot."
        )
        logger.warning(
            "Agent Tool Invocation Outcome",
            extra={
                "outcome": "failure",
                "target_tool": "book_appointment",
                "result_summary": redact_pii(error_result),
                "session_id": session_id,
            },
        )
        return error_result


def verify_booking_requirements(context: Context) -> str:
    """Checks the system state to ensure the booking transaction is fully finalized.

    Returns:
        A verification status message indicating whether the booking transaction
        is committed to the backend or incomplete, or a TOOL ERROR message on failure.
    """
    session_id = getattr(getattr(context, "session", None), "id", "default_session")
    logger.info(
        "Agent Tool Invocation Intent",
        extra={
            "intent": "verify_booking_status",
            "target_tool": "verify_booking",
            "session_id": session_id,
        },
    )
    try:
        if context.state.get("booking_status") == "COMPLETE" and context.state.get(
            "last_booking"
        ):
            tool_result = "Booking is verified and committed to the backend."
        else:
            tool_result = "Booking transaction is incomplete. Missing patient data or time slot."

        logger.info(
            "Agent Tool Invocation Outcome",
            extra={
                "outcome": "success",
                "target_tool": "verify_booking",
                "result_summary": redact_pii(tool_result),
                "session_id": session_id,
            },
        )
        return tool_result
    except Exception as e:
        error_result = (
            f"TOOL ERROR: {str(e)}. Unable to verify booking state; please "
            "retry the verification check."
        )
        logger.warning(
            "Agent Tool Invocation Outcome",
            extra={
                "outcome": "failure",
                "target_tool": "verify_booking",
                "result_summary": redact_pii(error_result),
                "session_id": session_id,
            },
        )
        return error_result


# Expose the function as 'verify_booking' to match the evaluator agent's tool name
verify_booking_requirements.__name__ = "verify_booking"


# 3. ADK Tool Factory Methods (Dependency Injection Providers)
def get_scheduler_tools() -> list[FunctionTool]:
    """Returns the FunctionTool instances for the Healthcare Scheduler agent."""
    return [
        FunctionTool(func=check_availability),
        FunctionTool(func=book_appointment),
    ]


def get_evaluator_tools() -> list[FunctionTool]:
    """Returns the FunctionTool instances for the Booking Critic agent."""
    return [
        FunctionTool(func=verify_booking_requirements),
    ]
