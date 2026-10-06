import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from agents import CriticEvaluatorLlm
from main import HealthcareAgentApp
from observability import redact_pii, redact_pii_data
from tools import (
    background_save_state,
    book_appointment,
    check_availability,
    get_scheduler_tools,
    verify_booking_requirements,
)


class TestHealthcareAgent(unittest.IsolatedAsyncioTestCase):
    """Unit tests for the ADK Healthcare Scheduling Agent."""

    def setUp(self):
        self.mock_ctx = MagicMock()
        self.mock_ctx.state = {
            "patient_id": "P-98765",
            "patient_name": "Phani Sagiraju",
        }
        self.mock_ctx.session.id = "test_session_001"

    def test_tool_json_schemas_include_descriptions(self):
        """Verifies that every FunctionTool exposes explicit JSON Schema parameter descriptions."""
        for tool in get_scheduler_tools():
            decl = tool._get_declaration()
            props = decl.parameters_json_schema["properties"]
            for param_name, schema in props.items():
                self.assertIn(
                    "description",
                    schema,
                    f"Missing description for parameter '{param_name}' in '{tool.name}'",
                )

    def test_graceful_error_recovery_on_invalid_inputs(self):
        """Verifies tools catch validation and domain errors without raising exceptions."""
        past_date_res = book_appointment(
            self.mock_ctx, "Dr. Smith", "2020-01-01", "4:00 PM"
        )
        self.assertTrue(past_date_res.startswith("TOOL ERROR:"))

        bad_format_res = check_availability(
            self.mock_ctx, "Dr. Smith", "invalid-date"
        )
        self.assertTrue(bad_format_res.startswith("TOOL ERROR:"))

    def test_hitl_security_gate_rejection(self):
        """Verifies Human-in-the-Loop gate blocks booking when supervisor rejects."""
        with patch("builtins.input", return_value="N"):
            res = book_appointment(
                self.mock_ctx, "Dr. Smith", "2026-10-10", "4:00 PM"
            )
            self.assertIn("Human supervisor rejected the booking", res)
            self.assertNotEqual(
                self.mock_ctx.state.get("booking_status"), "COMPLETE"
            )

    def test_pii_redaction(self):
        """Verifies Patient IDs and names are masked in strings and dictionaries."""
        text = "Patient P-98765 (Phani Sagiraju) booked an appointment."
        redacted = redact_pii(text)
        self.assertNotIn("P-98765", redacted)
        self.assertNotIn("Phani Sagiraju", redacted)
        self.assertIn("P-XXXXX", redacted)
        self.assertIn("[REDACTED_NAME]", redacted)

        redacted_dict = redact_pii_data(self.mock_ctx.state)
        self.assertEqual(redacted_dict["patient_id"], "P-XXXXX")
        self.assertEqual(redacted_dict["patient_name"], "[REDACTED_NAME]")

    async def test_booking_and_async_firestore_persistence(self):
        """Verifies happy-path booking with HITL approval, state mutation, and async Firestore consolidation."""
        mock_client = MagicMock()
        mock_doc = MagicMock()
        mock_doc.set = AsyncMock()
        mock_client.collection.return_value.document.return_value = mock_doc

        with patch("tools.get_firestore_client", return_value=mock_client), patch(
            "builtins.input", return_value="Y"
        ):
            avail = check_availability(self.mock_ctx, "Dr. Smith", "2026-10-10")
            self.assertIn("4:00 PM", avail)

            booked = book_appointment(
                self.mock_ctx, "Dr. Smith", "2026-10-10", "4:00 PM"
            )
            self.assertIn("Success!", booked)
            self.assertEqual(self.mock_ctx.state["booking_status"], "COMPLETE")

            verified = verify_booking_requirements(self.mock_ctx)
            self.assertIn("verified", verified)

            await background_save_state(
                "test_session_001", self.mock_ctx.state
            )
            mock_doc.set.assert_awaited()

    def test_strategic_model_routing_and_adk_compaction(self):
        """Verifies distinct model classes/tiers for worker vs critic and ADK native compaction."""
        app = HealthcareAgentApp()
        self.assertEqual(app.compaction_config.token_threshold, 4000)
        self.assertEqual(app.compaction_config.event_retention_size, 5)
        self.assertEqual(app.compaction_config.compaction_interval, 3)
        self.assertEqual(app.compaction_config.overlap_size, 1)

        scheduler_agent, critic_agent = app.workflow.sub_agents[0].sub_agents
        self.assertEqual(scheduler_agent.model.model, "gemini-3.5-flash-lite")
        self.assertEqual(critic_agent.model.model, "gemini-3.6-flash")
        self.assertIsInstance(critic_agent.model, CriticEvaluatorLlm)
        self.assertNotEqual(
            type(scheduler_agent.model), type(critic_agent.model)
        )

        for agent in (scheduler_agent, critic_agent):
            self.assertEqual(agent.model.retry_options.attempts, 5)


if __name__ == "__main__":
    unittest.main()
