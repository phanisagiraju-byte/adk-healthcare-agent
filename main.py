# main.py
import asyncio
import os
import warnings
from typing import Dict
from dotenv import load_dotenv
from google.adk.runners import InMemoryRunner
from google.genai import types

from observability import TracingObservabilityCallback
from workflow import create_hill_climbing_workflow

warnings.filterwarnings("ignore", category=UserWarning, module="google.adk")
load_dotenv(override=True)

if os.path.exists("key.json") and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.abspath("key.json")


class HealthcareAgentApp:
    """Main Application class for the Healthcare Agent."""

    def __init__(self):
        # Initialize dependencies (Callbacks)
        self.callbacks = [TracingObservabilityCallback()]
        # Inject dependencies into the workflow factory
        self.workflow = create_hill_climbing_workflow(self.callbacks)
        self.app_name = "adk_healthcare_app"
        self.runner = InMemoryRunner(
            agent=self.workflow,
            app_name=self.app_name,
        )

    async def process_patient_request(
        self, session_id: str, patient_data: Dict[str, str], prompt: str
    ):
        """Executes a request for a given patient session."""
        print(f"🏥 Starting ADK Session: {session_id} 🏥\n")

        user_id = patient_data.get("patient_id", "default_user")

        # 1. Initialize ADK Session & 2. Load initial context state
        session = await self.runner.session_service.create_session(
            app_name=self.app_name,
            user_id=user_id,
            session_id=session_id,
            state=dict(patient_data),
        )

        print(f"👤 User: {prompt}\n")

        # 3. Execute Workflow via ADK Runner
        user_message = types.Content(
            role="user",
            parts=[types.Part.from_text(text=prompt)],
        )

        final_result = ""
        async for event in self.runner.run_async(
            user_id=user_id,
            session_id=session.id,
            new_message=user_message,
        ):
            if event.content and event.content.parts:
                texts = [part.text for part in event.content.parts if part.text]
                if texts:
                    final_result = "\n".join(texts).strip()

        updated_session = await self.runner.session_service.get_session(
            app_name=self.app_name,
            user_id=user_id,
            session_id=session.id,
        )

        print("\n=======================================================")
        print("🏆 FINAL WORKFLOW RESULT")
        print("=======================================================")
        print(final_result)
        print("\n💾 FINAL SESSION MEMORY STATE")
        print(updated_session.state if updated_session else session.state)


async def main():
    # Setup App
    app = HealthcareAgentApp()

    # Setup mock patient data
    patient_data = {
        "patient_id": "P-98765",
        "patient_name": "Phani Sagiraju",
    }
    prompt = "I need an appointment with Dr. Smith on 2026-10-10 at 4:00 PM."

    # Run the App
    await app.process_patient_request(
        session_id="patient_123_session",
        patient_data=patient_data,
        prompt=prompt,
    )


if __name__ == "__main__":
    asyncio.run(main())
