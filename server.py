# server.py
from typing import Dict
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from main import HealthcareAgentApp, safe_process_request
from observability import logger, redact_pii, tracer

app = FastAPI(
    title="ADK Healthcare Scheduling Agent API",
    description="Enterprise Cloud Run API for the ADK Healthcare Scheduling Agent.",
    version="1.0.0",
)

agent_app = HealthcareAgentApp()


class ScheduleRequest(BaseModel):
    """Request payload for scheduling a patient appointment."""

    session_id: str = Field(
        ...,
        min_length=1,
        description="Unique session identifier for the patient conversation.",
    )
    patient_data: Dict[str, str] = Field(
        ...,
        description="Patient metadata including patient_id and patient_name.",
    )
    prompt: str = Field(
        ...,
        min_length=1,
        description="Natural language scheduling request from the patient.",
    )


class ScheduleResponse(BaseModel):
    """Response payload returned by the scheduling endpoint."""

    session_id: str
    result: str


@app.get("/health")
async def health_check() -> Dict[str, str]:
    """Liveness and readiness probe endpoint for Cloud Run."""
    return {"status": "healthy", "service": "adk-healthcare-agent"}


@app.post("/schedule", response_model=ScheduleResponse)
async def schedule_appointment(request: ScheduleRequest) -> ScheduleResponse:
    """Processes a patient scheduling request through the Hill Climbing ADK workflow."""
    with tracer.start_as_current_span("api.schedule_appointment") as span:
        span.set_attribute("session.id", request.session_id)
        try:
            result = await safe_process_request(
                app=agent_app,
                session_id=request.session_id,
                patient_data=request.patient_data,
                prompt=request.prompt,
            )
            return ScheduleResponse(session_id=request.session_id, result=result)
        except Exception as e:
            logger.error(
                redact_pii(f"API request failed: {str(e)}"),
                extra={
                    "intent": "handle_http_schedule_request",
                    "outcome": "failure",
                    "session_id": request.session_id,
                },
            )
            raise HTTPException(
                status_code=503,
                detail="Scheduling service temporarily unavailable.",
            ) from e
