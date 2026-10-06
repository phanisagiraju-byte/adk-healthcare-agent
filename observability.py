# observability.py
from typing import Any, Dict, Optional
from google.adk.agents.callback_context import CallbackContext
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types


class TracingObservabilityCallback:
    """Handles logging and tracing for all agent and tool executions."""

    def before_agent_run(
        self, callback_context: CallbackContext
    ) -> Optional[types.Content]:
        agent_name = callback_context.agent_name
        print(f"\n[OBSERVABILITY] 🚀 Agent '{agent_name}' starting execution...")
        print(
            f"[OBSERVABILITY] 🧠 Current Session State: {callback_context.state.to_dict()}"
        )
        return None

    def after_agent_run(
        self, callback_context: CallbackContext
    ) -> Optional[types.Content]:
        agent_name = callback_context.agent_name
        result = self._extract_last_agent_output(callback_context, agent_name)
        print(f"[OBSERVABILITY] ✅ Agent '{agent_name}' finished.")
        print(f"[OBSERVABILITY] 📄 Output: {result}")
        return None

    def before_tool_run(
        self,
        tool: BaseTool,
        args: Dict[str, Any],
        tool_context: ToolContext,
    ) -> Optional[Dict[str, Any]]:
        print(f"[OBSERVABILITY] 🛠️ Tool '{tool.name}' invoked with params: {args}")
        return None

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
