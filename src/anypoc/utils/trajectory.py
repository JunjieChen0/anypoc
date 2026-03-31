"""Trajectory file utilities — format detection, completion checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _extract_text_from_content(content: Any) -> str:
    """Extract text from various content formats (old trajectory format)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        if content.get("type") == "text":
            return content.get("text", "")
        return ""
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))
        return "\n".join(texts)
    return ""


def is_trajectory_complete(traj_path: Path | str) -> bool:
    """Check completion - supports both old (.traj.json) and new (caw trajectory.json) formats."""
    traj_path = Path(traj_path)
    if not traj_path.exists():
        return False

    try:
        data = json.loads(traj_path.read_text())
    except (json.JSONDecodeError, IOError):
        return False

    # Old format (AgentTrajectoryLogger): has metadata/info with end_time
    metadata = data.get("metadata") or data.get("info") or {}
    if "end_time" in metadata:
        if metadata.get("status") == "error":
            return False
        if metadata.get("error_type") == "usage_limit":
            return False
        # Legacy fallback: check last assistant message for limit keywords
        for msg in reversed(data.get("messages", [])):
            if msg.get("role") == "assistant":
                text = _extract_text_from_content(msg.get("content"))
                if text and "limit" in text.lower() and "resets" in text.lower():
                    return False
                break
        return True

    # If no end_time at all in old format, it's incomplete
    if "messages" in data:
        return False

    # New format (caw Trajectory)
    try:
        from caw import Trajectory

        traj = Trajectory.from_dict(data)
        return traj.is_complete
    except Exception:
        return False
