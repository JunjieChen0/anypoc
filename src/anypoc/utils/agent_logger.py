import json
from pathlib import Path
from typing import Any, Dict, List


class AgentLogger:
    def __init__(self, task_name: str, output_path: Path):
        self.task_name = task_name
        self.output_path = output_path
        self.messages: List[Dict[str, Any]] = []
        if not self.output_path.exists():
            self.output_path.mkdir(parents=True, exist_ok=True)

    def get_hooks(self, print_tool_usage: bool = True):
        # Return empty dict as hooks for now
        return {}

    def save_all(self):
        json_path = self.output_path / "trajectory.json"

        data = {"task_name": self.task_name, "messages": self.messages}

        with open(json_path, "w") as f:
            json.dump(data, f, indent=2)

        return {"json": str(json_path)}


async def process_agent_messages(response_stream, logger, print_to_stdout=True):
    """
    Process messages from the agent response stream.
    """
    async for message in response_stream:
        # Log the raw message for now
        # In a real implementation we would parse AssistantMessage etc.
        logger.messages.append({"content": str(message)})
        if print_to_stdout:
            # We don't print here to avoid cluttering stdout as the test already prints
            pass
