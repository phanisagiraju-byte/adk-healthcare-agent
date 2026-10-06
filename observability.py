# observability.py
import logging
import re
from typing import Any, Dict, Optional
from google.adk.agents.callback_context import CallbackContext
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from pythonjsonlogger import jsonlogger

# 1. Setup Structured JSON Logger
logger = logging.getLogger("adk_healthcare_agent")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    log_handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    log_handler.setFormatter(formatter)
    logger.addHandler(log_handler)

# 2. Setup OpenTelemetry Distributed Tracing
_tracer_provider: Optional[TracerProvider] = None


def init_tracer(service_name: str = "adk.healthcare.tracer") -> trace.Tracer:
    """Initializes the OpenTelemetry TracerProvider and returns a configured tracer."""
    global _tracer_provider
    if _tracer_provider is None and not isinstance(
        trace.get_tracer_provider(), TracerProvider
    ):
        _tracer_provider = TracerProvider()
        processor = SimpleSpanProcessor(ConsoleSpanExporter())
        _tracer_provider.add_span_processor(processor)
        trace.set_tracer_provider(_tracer_provider)
    return trace.get_tracer(service_name)


tracer = init_tracer()


# 3. Setup PII/PHI Redactor
def redact_pii(text: str) -> str:
    """Masks Patient IDs, names, emails, and SSNs to protect PHI/PII in logs."""
    if not isinstance(text, str):
        return str(text)
    # Mask Patient ID pattern (e.g., P-98765 -> P-XXXXX)
    text = re.sub(r"P-\d{5}", "P-XXXXX", text)
    # Mask email addresses
    text = re.sub(
        r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
        "[REDACTED_EMAIL]",
        text,
    )
    # Mask SSN patterns
    text = re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED_SSN]", text)
    # Mask known patient names
    text = text.replace("Phani Sagiraju", "[REDACTED_NAME]")
    return text


def redact_pii_data(data: Any) -> Any:
    """Recursively redacts PII/PHI across dictionaries, lists, and strings."""
    if isinstance(data, str):
        return redact_pii(data)
    if isinstance(data, dict):
        redacted: Dict[str, Any] = {}
        for k, v in data.items():
            if k in {"patient_name", "name", "ssn", "dob"} and isinstance(v, str):
                redacted[k] = "[REDACTED_NAME]" if "name" in k else "[REDACTED_PII]"
            else:
                redacted[k] = redact_pii_data(v)
        return redacted
    if isinstance(data, list):
        return [redact_pii_data(item) for item in data]
    return data


_TOOL_INTENT_MAP = {
    "check_availability": "check_doctor_availability",
    "book_appointment": "commit_patient_appointment_booking",
    "verify_booking": "verify_booking_transaction_state",
}


class TracingObservabilityCallback:
    """Handles structured JSON logging, PII redaction, intent/outcome tracking, and OTel tracing."""

    def before_agent_run(
        self, callback_context: CallbackContext
    ) -> Optional[types.Content]:
        agent_name = callback_context.agent_name
        session_id = getattr(callback_context.session, "id", "unknown_session")
        redacted_state = redact_pii_data(callback_context.state.to_dict())

        with tracer.start_as_current_span(f"agent.start.{agent_name}") as span:
            span.set_attribute("agent.name", agent_name)
            span.set_attribute("session.id", session_id)
            logger.info(
                redact_pii(f"Agent '{agent_name}' starting execution"),
                extra={
                    "event_type": "agent_start",
                    "agent_name": agent_name,
                    "session_id": session_id,
                    "session_state": redacted_state,
                },
            )
        return None

    def after_agent_run(
        self, callback_context: CallbackContext
    ) -> Optional[types.Content]:
        agent_name = callback_context.agent_name
        session_id = getattr(callback_context.session, "id", "unknown_session")
        result = self._extract_last_agent_output(callback_context, agent_name)
        redacted_result = redact_pii(result)

        with tracer.start_as_current_span(f"agent.finish.{agent_name}") as span:
            span.set_attribute("agent.name", agent_name)
            span.set_attribute("session.id", session_id)
            logger.info(
                redact_pii(f"Agent '{agent_name}' finished execution"),
                extra={
                    "event_type": "agent_complete",
                    "agent_name": agent_name,
                    "session_id": session_id,
                    "agent_output": redacted_result,
                },
            )
        return None

    def before_tool_run(
        self,
        tool: BaseTool,
        args: Dict[str, Any],
        tool_context: ToolContext,
    ) -> Optional[Dict[str, Any]]:
        session_id = getattr(tool_context.session, "id", "unknown_session")
        intent = _TOOL_INTENT_MAP.get(tool.name, f"invoke_{tool.name}")
        redacted_args = redact_pii_data(args)

        with tracer.start_as_current_span(f"tool.intent.{tool.name}") as span:
            span.set_attribute("tool.name", tool.name)
            span.set_attribute("tool.intent", intent)
            span.set_attribute("session.id", session_id)
            logger.info(
                "Agent Tool Invocation Intent",
                extra={
                    "intent": intent,
                    "target_tool": tool.name,
                    "tool_args": redacted_args,
                    "session_id": session_id,
                },
            )
        return None

    def after_tool_run(
        self,
        tool: BaseTool,
        args: Dict[str, Any],
        tool_context: ToolContext,
        tool_response: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        session_id = getattr(tool_context.session, "id", "unknown_session")
        response_text = str(tool_response)
        is_error = "TOOL ERROR" in response_text or "error" in tool_response
        outcome = "failure" if is_error else "success"

        with tracer.start_as_current_span(f"tool.outcome.{tool.name}") as span:
            span.set_attribute("tool.name", tool.name)
            span.set_attribute("tool.outcome", outcome)
            span.set_attribute("session.id", session_id)
            logger.info(
                "Agent Tool Invocation Outcome",
                extra={
                    "outcome": outcome,
                    "target_tool": tool.name,
                    "result_summary": redact_pii(response_text),
                    "session_id": session_id,
                },
            )
        return None

    def on_tool_error_run(
        self,
        tool: BaseTool,
        args: Dict[str, Any],
        tool_context: ToolContext,
        error: Exception,
    ) -> Optional[Dict[str, Any]]:
        session_id = getattr(tool_context.session, "id", "unknown_session")
        error_msg = (
            f"TOOL ERROR in '{tool.name}': {str(error)}. "
            "Please adjust the tool arguments and try again."
        )

        with tracer.start_as_current_span(f"tool.error.{tool.name}") as span:
            span.set_attribute("tool.name", tool.name)
            span.set_attribute("tool.outcome", "failure")
            span.set_attribute("session.id", session_id)
            logger.error(
                "Agent Tool Invocation Outcome",
                extra={
                    "outcome": "failure",
                    "target_tool": tool.name,
                    "result_summary": redact_pii(error_msg),
                    "session_id": session_id,
                },
            )
        return {"error": error_msg}

    @staticmethod
    def _extract_last_agent_output(
        callback_context: CallbackContext, agent_name: str
    ) -> str:
        """Finds the most recent text response emitted by the given agent."""
        for event in reversed(callback_context.session.events):
            if event.author == agent_name and event.content and event.content.parts:
                texts = [part.text for part in event.content.parts if part.text]
                if texts:
                    return "\n".join(texts).strip()
        return "(completed)"
